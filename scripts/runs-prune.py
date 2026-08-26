"""Remove finished run evidence that nothing can still resume.

Owner: the run evidence directory's retention boundary.
Allowed imports: the standard library only. Retention must keep working when
the runtime it prunes for cannot load.
Forbidden imports: the workflow route and the agent lifecycle -- a maintenance
pass must not be able to change what a run means.
Callers/tests: run by hand; coverage lives in ``tests/test_runs_prune.py``.
Verification: run that module, then this script with no ``--apply`` and compare
its report against the directory.

A run directory holds the preflight, the gate ledger, the timings, and the
continuation packet that lets a later session resume it. On the reference
machine 96 of them had accumulated over two weeks, 31 MB, and only the recent
ones can still be resumed by anything.

Three rules decide what stays. A run that is not finished stays regardless of
age, because its packet is the only record of where it stopped -- that includes
a run with no packet at all, whose state cannot be read and therefore cannot be
called done. The newest ``--keep`` finished runs stay, because resuming the last
few is the case this directory exists for. And anything not named like a run id
stays and is reported: this directory also holds evidence under human-chosen
names, and a report that counted only the opaque ids would read as a total when
it is not one.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_KEEP = 10
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


def plan(project: Path, *, keep: int = DEFAULT_KEEP) -> dict:
    directory = runs_dir(project)
    if not directory.is_dir():
        return {
            "finished": [],
            "unfinished": [],
            "unclassified": [],
            "kept": [],
            "removable": [],
        }

    finished: list[Path] = []
    unfinished: list[Path] = []
    # Named rather than skipped. This directory also holds run evidence under
    # human-chosen names, and a report that counts only the opaque ids reads as
    # a total when it is not one.
    unclassified: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not is_run_directory(path):
            unclassified.append(path)
            continue
        (finished if phase_of(path) in FINISHED_PHASES else unfinished).append(path)

    finished.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    keep = max(0, int(keep))
    return {
        "finished": finished,
        "unfinished": unfinished,
        "unclassified": unclassified,
        "kept": finished[:keep],
        "removable": finished[keep:],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove the runs listed as removable; without it, only report",
    )
    args = parser.parse_args(argv)

    directory = runs_dir(args.project)
    if not directory.is_dir():
        print(f"no run directory at {directory}")
        return 0

    report = plan(args.project, keep=args.keep)
    print(f"runs: {directory}")
    print(
        f"finished: {len(report['finished'])}  unfinished: {len(report['unfinished'])}"
    )
    if report["unclassified"]:
        print(
            f"not named like a run id, never removed: {len(report['unclassified'])}"
        )
    print(
        f"keeping the newest {len(report['kept'])} finished; "
        f"removable: {len(report['removable'])}"
    )
    if report["unfinished"]:
        print("unfinished runs are never removed:")
        for path in report["unfinished"][:5]:
            print(f"    {path.name}  phase={phase_of(path) or 'unreadable'}")
        if len(report["unfinished"]) > 5:
            print(f"    ... and {len(report['unfinished']) - 5} more")
    if not report["removable"]:
        print("nothing to remove")
        return 0

    freed = directory_bytes(report["removable"])
    print(f"bytes to free: {freed}")
    if not args.apply:
        print("report only; pass --apply to remove them")
        return 0

    removed = apply_plan(report["removable"])
    print(f"removed {removed} run(s)")
    return 0 if removed == len(report["removable"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
