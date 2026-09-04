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
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

DEFAULT_KEEP = 10
DEFAULT_ABANDONED_AFTER_SECONDS = 30 * 24 * 60 * 60
RUN_ID_LENGTH = 32
FINISHED_PHASES = {"done"}


def runs_dir(project: Path) -> Path:
    return project / ".tao" / "runs"


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
    now: float | None = None,
) -> dict:
    directory = runs_dir(project)
    if not directory.is_dir():
        return {
            "finished": [],
            "unfinished": [],
            "abandoned": [],
            "unclassified": [],
            "kept": [],
            "removable": [],
        }

    moment = time.time() if now is None else now
    cutoff = moment - max(0, int(abandoned_after_seconds))
    finished: list[Path] = []
    unfinished: list[Path] = []
    abandoned: list[Path] = []
    # Named rather than skipped. This directory also holds run evidence under
    # human-chosen names, and a report that counts only the opaque ids reads as
    # a total when it is not one.
    unclassified: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not is_run_directory(path):
            unclassified.append(path)
            continue
        if phase_of(path) in FINISHED_PHASES:
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
        "unclassified": unclassified,
        "kept": finished[:keep],
        "removable": [*finished[keep:], *abandoned],
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
    apply: bool = True,
) -> dict[str, int]:
    """Remove what nothing can resume, and report what was left behind.

    The counts are what a maintenance pass prints. `unclassified_bytes` is
    reported and never removed, because that is the part a person has to decide
    about and it was invisible until it was counted.
    """

    report = plan(project, keep=keep, abandoned_after_seconds=abandoned_after_seconds)
    removable = report["removable"]
    freed = directory_bytes(removable) if removable else 0
    removed = apply_plan(removable) if apply and removable else 0
    return {
        "finished": len(report["finished"]),
        "unfinished": len(report["unfinished"]),
        "abandoned": len(report["abandoned"]),
        "removed": removed,
        "freed_bytes": freed if removed else 0,
        "removable_bytes": freed,
        "unclassified": len(report["unclassified"]),
        "unclassified_bytes": directory_bytes(report["unclassified"]),
    }
