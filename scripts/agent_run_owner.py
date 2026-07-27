"""Process-liveness evidence for the owner of a Tao Agent OS run.

A run outlives every process that reports on it, so the registry cannot tell a
slow agent from a dead one by timestamps alone. This module answers the one
question that separates them -- is the process that owns this run still there?
-- and it deliberately knows nothing about how runs are stored.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


# A living owner buys a run more silence, never unlimited silence. Letting
# liveness veto recovery outright would hand the shared evidence path back to
# the deadlock the sweep exists to break, because a crashed agent can leave an
# owner that outlives it. Past this multiple of the staleness window the run is
# failed whatever its owner looks like, so the path always frees itself.
LIVE_OWNER_GRACE_MULTIPLIER = 12


def process_owner() -> dict[str, Any]:
    """Identify the process that launched this agent session.

    Neither end of the process tree works as a liveness anchor. The hook and
    the shell that ran it exit within the same tool call, so they look dead
    while the agent is still working; the terminal above them survives the
    agent, so it looks alive after the agent is gone. Between them sits the
    launcher of the current job -- the parent of the session leader -- which
    for a real hook invocation resolves to the agent runtime itself: it spans
    every hook of the session and disappears when that session ends.

    Only POSIX hosts can probe another process safely, so elsewhere the run
    records no owner and keeps the older timestamp-only recovery contract
    rather than an identity nothing can ever check.
    """

    if os.name != "posix":
        return {}
    pid, start_token = _owner_identity()
    if pid < 1:
        return {}
    return {"pid": pid, "start_token": start_token}


def owner_is_gone(owner: Any) -> bool:
    """Report only proof of death, never mere suspicion.

    Ambiguity on a host that can probe processes -- a missing start time, a
    permission error -- resolves to "still alive", because wrongly preserving a
    dead record costs one stale entry while wrongly failing a live run destroys
    an agent's in-flight work. Two cases carry no owner evidence at all and keep
    the older timestamp-only contract so they cannot hold the shared evidence
    path forever: records written before owners existed, and hosts where
    probing a pid would terminate it instead of testing it.
    """

    if os.name != "posix" or not isinstance(owner, dict):
        return True
    try:
        pid = int(owner.get("pid"))
    except (TypeError, ValueError):
        return True
    if pid < 1 or not _pid_exists(pid):
        return True
    recorded = str(owner.get("start_token") or "")
    current = _process_start_token(pid)
    return bool(recorded and current and recorded != current)


def owner_death_is_proven(owner: Any) -> bool:
    """Answer the stricter question: did we record an owner, and is it gone?

    ``owner_is_gone`` folds "no evidence" into "gone" so records that never
    carried an owner keep falling through to the timestamp contract. A caller
    that acts on death alone, with no waiting period behind it, needs evidence
    to have existed in the first place -- otherwise every run on a host that
    cannot identify an owner would be declared dead the moment it registered.
    """

    if os.name != "posix" or not _owner_is_recorded(owner):
        return False
    return owner_is_gone(owner)


def _owner_is_recorded(owner: Any) -> bool:
    if not isinstance(owner, dict):
        return False
    try:
        return int(owner.get("pid")) >= 1
    except (TypeError, ValueError):
        return False


@functools.lru_cache(maxsize=1)
def _owner_identity() -> tuple[int, str]:
    """Resolve the owner once; it cannot change while this process runs."""

    pid = _owner_pid()
    return pid, _process_start_token(pid) if pid > 0 else ""


def _owner_pid() -> int:
    getsid = getattr(os, "getsid", None)
    if getsid is None:
        return 0
    try:
        leader = int(getsid(0))
    except OSError:
        return 0
    launcher = _parent_pid(leader)
    # A launcher of ``init`` means the job was reparented or daemonised, and
    # init never exits, so the session leader is the narrower honest anchor.
    if launcher == 1:
        return leader
    # Zero means every safe lookup was unavailable. Recording the short-lived
    # session leader here would make a live agent look dead after the hook exits,
    # so preserve the timestamp-only contract instead.
    return launcher if launcher > 1 else 0


def _parent_pid(pid: int) -> int:
    """Read one process's parent without /proc, which macOS does not have."""

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        return int(stat.rpartition(")")[2].split()[1])
    except (OSError, IndexError, ValueError):
        pass
    parent = _darwin_parent_pid(pid)
    if parent:
        return parent
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return int(result.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _darwin_parent_pid(pid: int) -> int:
    """Read a Darwin parent pid in-process so sandboxed hooks do not need ``ps``."""

    if sys.platform != "darwin" or pid < 1:
        return 0

    import ctypes

    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [
            ("pbi_flags", ctypes.c_uint32),
            ("pbi_status", ctypes.c_uint32),
            ("pbi_xstatus", ctypes.c_uint32),
            ("pbi_pid", ctypes.c_uint32),
            ("pbi_ppid", ctypes.c_uint32),
            ("pbi_uid", ctypes.c_uint32),
            ("pbi_gid", ctypes.c_uint32),
            ("pbi_ruid", ctypes.c_uint32),
            ("pbi_rgid", ctypes.c_uint32),
            ("pbi_svuid", ctypes.c_uint32),
            ("pbi_svgid", ctypes.c_uint32),
            ("rfu_1", ctypes.c_uint32),
            ("pbi_comm", ctypes.c_char * 16),
            ("pbi_name", ctypes.c_char * 32),
            ("pbi_nfiles", ctypes.c_uint32),
            ("pbi_pgid", ctypes.c_uint32),
            ("pbi_pjobc", ctypes.c_uint32),
            ("e_tdev", ctypes.c_uint32),
            ("e_tpgid", ctypes.c_uint32),
            ("pbi_nice", ctypes.c_int32),
            ("pbi_start_tvsec", ctypes.c_uint64),
            ("pbi_start_tvusec", ctypes.c_uint64),
        ]

    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pidinfo = libproc.proc_pidinfo
        proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        proc_pidinfo.restype = ctypes.c_int
        info = ProcBsdInfo()
        size = ctypes.sizeof(info)
        written = proc_pidinfo(pid, 3, 0, ctypes.byref(info), size)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0
    return int(info.pbi_ppid) if written == size else 0


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError, OverflowError):
        return True
    return True


def _process_start_token(pid: int) -> str:
    """Bind a recorded pid to one process so pid reuse cannot fake liveness.

    Only ``/proc`` exposes this without a dependency. Where it is missing the
    empty token simply drops the reuse check, which keeps a run alive rather
    than failing one that might be working.
    """

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    fields = stat.rpartition(")")[2].split()
    return fields[19] if len(fields) > 19 else ""
