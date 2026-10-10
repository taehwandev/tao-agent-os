"""Find a repository's other checkouts that hold Tao run state.

Owner: the bounded list of checkouts a session-wide settle may look at, and
the content-free question of whether a settled run's checkout still holds
unfinished work.
Allowed imports: the standard library.
Forbidden imports: the run registry and runtime-session modules; the caller
hands in each checkout and run id and does the settling itself.
Callers/tests: agent_runtime_session.settle_superseded_session_runs;
tests/test_settle_superseded_session_runs.py.
Verification: that test module and the runtime-session suite.

A session that leaves a run paused in the main checkout and moves on to a
linked worktree never settled the paused run: supersession only scanned the
checkout the new start ran in. Git already registers every checkout of one
repository, so asking it -- rather than walking the filesystem -- keeps the
scan to that repository, and only checkouts that already carry a run registry
are worth opening at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# A repository with more registered checkouts than this is not one a start
# should walk on every call; the excess is left to its own sessions.
MAX_CHECKOUTS = 64
REGISTRY_RELATIVE_PATH = Path(".tao") / "run-registry.json"


def checkouts_with_run_state(project: Path) -> list[Path]:
    """Every other checkout of ``project``'s repository with a run registry."""

    try:
        result = subprocess.run(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    own = _resolved(project)
    found: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = _resolved(Path(line[len("worktree "):]))
        if candidate is None or candidate == own or candidate in found:
            continue
        if (candidate / REGISTRY_RELATIVE_PATH).is_file():
            found.append(candidate)
        if len(found) >= MAX_CHECKOUTS:
            break
    return found


def checkout_keeps_unfinished_work(checkout: Path, run_id: str) -> bool:
    """Whether settling ``run_id`` leaves work behind that someone must see.

    True when the checkout has uncommitted tracked changes, or the run's
    continuation packet records changed scope, remaining work or a pending
    mutation. An unreadable status counts as work kept: the answer only
    decides whether to say so, and saying so needlessly costs one line.
    """

    try:
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if status.returncode != 0 or status.stdout.strip():
        return True
    return _packet_records_unfinished_work(checkout, run_id)


def _packet_records_unfinished_work(checkout: Path, run_id: str) -> bool:
    packet_path = checkout / ".tao" / "runs" / run_id / "continuation.json"
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(packet, dict):
        return False
    work = packet.get("work") if isinstance(packet.get("work"), dict) else {}
    checkpoint = packet.get("checkpoint") if isinstance(packet.get("checkpoint"), dict) else {}
    return bool(
        work.get("changed_scope")
        or work.get("remaining_work")
        or checkpoint.get("mutation_pending") is not None
    )


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None
