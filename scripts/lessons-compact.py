"""Fold a lesson candidate inbox down to one record per lesson.

Owner: the global lesson store's maintenance boundary.
Allowed imports: the standard library, and the store's own merge rules --
compaction must not invent a second definition of what a merged candidate is.
Forbidden imports: the workflow route, the agent lifecycle, and anything that
would let a maintenance pass change what a lesson means.
Callers/tests: run by hand; coverage lives in
``tests/test_lessons_compact.py``.
Verification: run that module's merge and refusal tests, then this script with
no `--apply` against a real store and compare its report to the store.

The writer already keeps one record per lesson: it writes
``inbox/<lesson_id>.json`` and removes that lesson's older files. But it only
does so when that lesson recurs, so a lesson that stopped happening keeps
whatever files it had. On the reference machine that left 824 legacy
timestamped files beside 80 canonical ones -- 904 records for 296 lessons,
read in full by every preflight.

Folding them cannot be a plain delete. A lesson's occurrence count is the sum
across its records, so dropping the older ones would silently reduce it. This
merges by the store's own rules and then removes what it merged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_lesson_store import _merged_occurrence_keys  # noqa: E402
from support.global_state import global_state_dir  # noqa: E402


def inbox_path(state_home: Path) -> Path:
    return state_home / "lessons" / "inbox"


def read_records(inbox: Path) -> tuple[dict[str, list[tuple[Path, dict]]], list[Path]]:
    """Group readable records by lesson id, and report the ones that are not."""

    groups: dict[str, list[tuple[Path, dict]]] = {}
    unreadable: list[Path] = []
    for path in sorted(inbox.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable.append(path)
            continue
        if not isinstance(record, dict):
            unreadable.append(path)
            continue
        lesson_id = str(record.get("lesson_id") or "")
        if not lesson_id:
            unreadable.append(path)
            continue
        groups.setdefault(lesson_id, []).append((path, record))
    return groups, unreadable


def merge_group(records: list[dict]) -> dict:
    """Merge one lesson's records the way the store's own writer would.

    The count is the sum across records, because that is what
    ``upsert_retrospective_candidate`` reads from the inbox; the newest record
    supplies every other field, and the keys are merged in first-seen order by
    the store's own helper.
    """

    ordered = sorted(records, key=lambda item: str(item.get("created_at") or ""))
    newest = ordered[-1]
    return {
        **newest,
        "first_seen_at": min(
            str(item.get("first_seen_at") or item.get("created_at") or "")
            for item in ordered
        ),
        "last_seen_at": max(
            str(item.get("last_seen_at") or item.get("created_at") or "")
            for item in ordered
        ),
        "occurrence_count": sum(
            max(1, int(item.get("occurrence_count", 1)))
            for item in ordered
            if isinstance(item.get("occurrence_count", 1), int)
            and not isinstance(item.get("occurrence_count", 1), bool)
        ),
        "occurrence_keys": _merged_occurrence_keys(ordered),
    }


def plan(inbox: Path) -> dict:
    groups, unreadable = read_records(inbox)
    folds = []
    for lesson_id, items in sorted(groups.items()):
        if len(items) == 1 and items[0][0].name == f"{lesson_id}.json":
            continue
        folds.append(
            {
                "lesson_id": lesson_id,
                "paths": [path for path, _ in items],
                "merged": merge_group([record for _, record in items]),
            }
        )
    return {
        "records": sum(len(items) for items in groups.values()),
        "lessons": len(groups),
        "unreadable": unreadable,
        "folds": folds,
    }


def apply_plan(inbox: Path, folds: list[dict]) -> int:
    """Write each merged record, then remove the files it was merged from."""

    written = 0
    for fold in folds:
        target = inbox / f"{fold['lesson_id']}.json"
        temporary = target.with_suffix(".compact.tmp")
        temporary.write_text(
            json.dumps(fold["merged"], indent=1, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(target)
        written += 1
        for path in fold["paths"]:
            if path != target:
                path.unlink(missing_ok=True)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-home", type=Path, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the merged records and remove the files they replace; "
        "without it, only report what would change",
    )
    args = parser.parse_args(argv)
    state_home = args.state_home or global_state_dir()
    inbox = inbox_path(state_home)
    if not inbox.is_dir():
        print(f"no candidate inbox at {inbox}")
        return 0

    report = plan(inbox)
    removed = sum(len(fold["paths"]) for fold in report["folds"]) - len(report["folds"])
    print(f"inbox: {inbox}")
    print(f"records: {report['records']}  lessons: {report['lessons']}")
    print(f"lessons to fold: {len(report['folds'])}  files to remove: {removed}")
    if report["unreadable"]:
        print(f"unreadable, left untouched: {len(report['unreadable'])}")
        for path in report["unreadable"][:5]:
            print(f"    {path.name}")
    for fold in sorted(report["folds"], key=lambda item: -len(item["paths"]))[:5]:
        print(
            f"    {fold['lesson_id']}: {len(fold['paths'])} files -> 1, "
            f"occurrences {fold['merged']['occurrence_count']}"
        )
    if not args.apply:
        print("nothing written; pass --apply to fold")
        return 0
    written = apply_plan(inbox, report["folds"])
    print(f"folded {written} lessons; {removed} files removed")
    return 0


main_with_arguments = main


if __name__ == "__main__":
    sys.exit(main())
