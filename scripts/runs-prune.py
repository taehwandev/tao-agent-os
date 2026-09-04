"""Report and remove finished run evidence that nothing can still resume.

Owner: the command line over the run-evidence retention policy.
Allowed imports: the standard library and ``agent_run_evidence``, which owns
the rules. This file decides nothing; it prints what that module planned and
applies it when asked.
Callers/tests: run by hand for a one-off report; the same policy runs
unattended from ``agent_os_maintenance``. Coverage lives in
``tests/test_runs_prune.py``.
Verification: run this script with no ``--apply`` and compare its report
against the directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_run_evidence import (
    DEFAULT_ABANDONED_AFTER_SECONDS,
    DEFAULT_KEEP,
    apply_plan,
    directory_bytes,
    phase_of,
    plan,
    runs_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument(
        "--abandoned-after-seconds",
        type=int,
        default=DEFAULT_ABANDONED_AFTER_SECONDS,
        help=(
            "an unfinished run untouched for this long has been abandoned rather "
            "than paused, and becomes removable"
        ),
    )
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

    report = plan(
        args.project,
        keep=args.keep,
        abandoned_after_seconds=args.abandoned_after_seconds,
    )
    print(f"runs: {directory}")
    print(
        f"finished: {len(report['finished'])}  unfinished: {len(report['unfinished'])}"
        f"  abandoned: {len(report['abandoned'])}"
    )
    if report["unclassified"]:
        print(
            f"not named like a run id, never removed: {len(report['unclassified'])}"
            f" ({directory_bytes(report['unclassified'])} bytes)"
        )
    print(
        f"keeping the newest {len(report['kept'])} finished; "
        f"removable: {len(report['removable'])}"
    )
    if report["unfinished"]:
        print("unfinished runs are kept while they can still be resumed:")
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
    sys.exit(main())
