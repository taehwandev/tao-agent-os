"""Decide which run evidence directories nothing can still resume.

Owner: the run evidence directory's retention boundary.
Allowed imports: the standard library only. Retention must keep working when
the runtime it prunes for cannot load.
Forbidden imports: the workflow route and the agent lifecycle -- a maintenance
pass must not be able to change what a run means.
Callers/tests: ``runs-prune.py`` and ``agent_os_maintenance.run_maintenance``;
coverage lives in ``tests/test_runs_prune.py``.
Verification: run that module, then ``runs-prune.py`` with no ``--apply`` and
compare its report against the directory.

A run directory holds the preflight, the gate ledger, the timings, and the
continuation packet that lets a later session resume it. On the reference
machine 103 of them had accumulated over three weeks, 32 MB, and only the
recent ones can still be resumed by anything.

This lives apart from the script that prints it because the script's name has a
hyphen in it and cannot be imported. That is not cosmetic: it is why nothing
ever called this policy. The maintenance pass pruned the registry's *records*
of runs on a thirty-day window while the directories those records pointed at
were kept forever, so the index shrank and the disk did not.

Three rules decide what stays. Finished runs: the newest ``keep`` stay, because
resuming the last few is what this directory is for. Unfinished runs: they stay
while they can still be resumed, because the packet is the only record of where
one stopped -- but "unfinished" is not "immortal", and one untouched for the
retention window has been abandoned, not paused. That window is the same one
the registry already applies to its own records, so the two halves of retention
agree. And anything not named like a run id stays, and is reported: this
directory also holds evidence under human-chosen names, which a person made on
purpose and no automatic pass should remove.

The registry is consulted when it can be read, so the two halves of retention
agree about what a run is. A directory whose record is settled (completed or
cancelled) is finished even when its packet never reached ``done``; one whose
record still holds a claim is never removed; and one the registry no longer
records at all -- an orphan, which nothing can claim or checkpoint -- is
removed once it has been left alone for ``orphan_after_seconds``. A registry
that is absent or unreadable is not evidence that every run is an orphan, so
without one the registry-aware rules are simply not applied.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Iterable

DEFAULT_KEEP = 10
DEFAULT_ABANDONED_AFTER_SECONDS = 30 * 24 * 60 * 60
DEFAULT_ORPHAN_AFTER_SECONDS = 14 * 24 * 60 * 60
RUN_ID_LENGTH = 32
FINISHED_PHASES = {"done"}
# Mirrors agent_run_registry without importing it: a run in one of these
# states is held by an owner and is never removed here.
CLAIM_HOLDING_STATES = frozenset({"running", "paused", "resuming", "claiming"})
SETTLED_STATES = frozenset({"completed", "cancelled"})
REGISTRY_SCHEMA_VERSION = 1


def runs_dir(project: Path) -> Path:
    return project / ".tao" / "runs"


def read_registry_states(project: Path) -> dict[str, str] | None:
    """Return run id -> state from the registry, or None when it cannot be read.

    Read without the registry lock: it is replaced atomically, and a retention
    report must not create lock files in a checkout it only inspects.
    """

    path = project / ".tao" / "run-registry.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION
        or not isinstance(payload.get("runs"), list)
    ):
        return None
    states: dict[str, str] = {}
    for run in payload["runs"]:
        if isinstance(run, dict) and run.get("run_id"):
            states[str(run["run_id"])] = str(run.get("state") or "")
    return states


def is_run_directory(path: Path) -> bool:
    """A run id is the directory name, so anything else is not ours to remove."""

    return (
        path.is_dir()
        and len(path.name) == RUN_ID_LENGTH
        and all(character in "0123456789abcdef" for character in path.name)
    )


def phase_of(path: Path) -> str:
    """Return the recorded phase, or "" when it cannot be read.

    An unreadable or absent packet is deliberately not `done`. Retention has to
    fail towards keeping a run whose state it cannot establish.
    """

    packet = path / "continuation.json"
    try:
        payload = json.loads(packet.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("phase") or "") if isinstance(payload, dict) else ""


def _touched_at(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        # Unreadable is not evidence of age, and retention fails towards
        # keeping what it cannot establish.
        return time.time()


def plan(
    project: Path,
    *,
    keep: int = DEFAULT_KEEP,
    abandoned_after_seconds: int = DEFAULT_ABANDONED_AFTER_SECONDS,
    orphan_after_seconds: int = DEFAULT_ORPHAN_AFTER_SECONDS,
    registry_states: dict[str, str] | None = None,
    use_registry: bool = True,
    protected: Iterable[str] = (),
    now: float | None = None,
) -> dict:
    """Classify every entry of the run directory.

    ``registry_states`` overrides the registry read from disk; with
    ``use_registry`` false the registry is ignored entirely. ``protected``
    names runs a caller has established are still owned (a live owner that was
    active moments ago) and that nothing here may remove.
    """

    directory = runs_dir(project)
    if not directory.is_dir():
        return {
            "finished": [],
            "unfinished": [],
            "abandoned": [],
            "orphaned": [],
            "unclassified": [],
            "kept": [],
            "removable": [],
        }

    if registry_states is None and use_registry:
        registry_states = read_registry_states(project)
    held = set(protected)
    moment = time.time() if now is None else now
    cutoff = moment - max(0, int(abandoned_after_seconds))
    orphan_cutoff = moment - max(0, int(orphan_after_seconds))
    finished: list[Path] = []
    unfinished: list[Path] = []
    abandoned: list[Path] = []
    orphaned: list[Path] = []
    removable_orphans: list[Path] = []
    # Named rather than skipped. This directory also holds run evidence under
    # human-chosen names, and a report that counts only the opaque ids reads as
    # a total when it is not one.
    unclassified: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not is_run_directory(path):
            unclassified.append(path)
            continue
        state = None if registry_states is None else registry_states.get(path.name)
        if path.name in held or state in CLAIM_HOLDING_STATES:
            unfinished.append(path)
        elif registry_states is not None and state is None:
            # Nothing can claim or checkpoint a packet whose record is gone.
            orphaned.append(path)
            if _touched_at(path) < orphan_cutoff:
                removable_orphans.append(path)
        elif phase_of(path) in FINISHED_PHASES or state in SETTLED_STATES:
            finished.append(path)
        elif _touched_at(path) < cutoff:
            abandoned.append(path)
        else:
            unfinished.append(path)

    finished.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    keep = max(0, int(keep))
    return {
        "finished": finished,
        "unfinished": unfinished,
        "abandoned": abandoned,
        "orphaned": orphaned,
        "unclassified": unclassified,
        "kept": finished[:keep],
        "removable": [*finished[keep:], *abandoned, *removable_orphans],
    }


def apply_plan(removable: list[Path]) -> int:
    removed = 0
    for path in removable:
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed += 1
    return removed


def directory_bytes(paths: list[Path]) -> int:
    return sum(
        item.stat().st_size
        for path in paths
        for item in path.rglob("*")
        if item.is_file()
    )


def prune_run_evidence(
    project: Path,
    *,
    keep: int = DEFAULT_KEEP,
    abandoned_after_seconds: int = DEFAULT_ABANDONED_AFTER_SECONDS,
    orphan_after_seconds: int = DEFAULT_ORPHAN_AFTER_SECONDS,
    registry_states: dict[str, str] | None = None,
    protected: Iterable[str] = (),
    apply: bool = True,
) -> dict[str, int]:
    """Remove what nothing can resume, and report what was left behind.

    The counts are what a maintenance pass prints. `unclassified_bytes` is
    reported and never removed, because that is the part a person has to decide
    about and it was invisible until it was counted.
    """

    report = plan(
        project,
        keep=keep,
        abandoned_after_seconds=abandoned_after_seconds,
        orphan_after_seconds=orphan_after_seconds,
        registry_states=registry_states,
        protected=protected,
    )
    removable = report["removable"]
    freed = directory_bytes(removable) if removable else 0
    removed = apply_plan(removable) if apply and removable else 0
    return {
        "finished": len(report["finished"]),
        "unfinished": len(report["unfinished"]),
        "abandoned": len(report["abandoned"]),
        "orphaned": len(report["orphaned"]),
        "removable": len(removable),
        "removed": removed,
        "freed_bytes": freed if removed else 0,
        "removable_bytes": freed,
        "unclassified": len(report["unclassified"]),
        "unclassified_bytes": directory_bytes(report["unclassified"]),
    }
