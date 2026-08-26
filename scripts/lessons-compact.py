"""Fold a lesson candidate inbox down to one record per lesson.

Owner: the global lesson store's maintenance boundary.
Allowed imports: the standard library, and the store's own merge rules, record
reader, and lock -- compaction must not invent a second definition of what a
merged candidate is, which files belong to a lesson, or how a lesson is locked.
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

from agent_lesson_files import _read_lesson_records  # noqa: E402
from agent_lesson_store import _merged_occurrence_keys  # noqa: E402
from agent_state_lock import state_lock  # noqa: E402
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


def _lesson_records_now(
    inbox: Path, lesson_id: str, known: list[Path]
) -> tuple[list[dict], list[Path]]:
    """Re-read one lesson's records while its lock is held.

    Two sources, because the two readers disagree by design. The store finds a
    lesson by filename, which is what the writer creates and therefore what can
    appear after a report was taken. This script groups by the `lesson_id`
    inside each record, which is how it finds legacy files whose names follow no
    convention. Merging fewer records than were read would drop occurrences, so
    the union is read and each record is checked against the lesson it claims.
    """

    records, paths = _read_lesson_records(inbox, lesson_id)
    seen = set(paths)
    for path in known:
        if path in seen:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and str(record.get("lesson_id") or "") == lesson_id:
            records.append(record)
            paths.append(path)
            seen.add(path)
    return records, paths


def apply_plan(inbox: Path, folds: list[dict]) -> int:
    """Merge and replace each lesson under the lock the writer already uses.

    A report's merge is advisory. It was computed from a read taken before any
    lock was held, and the writer can add a candidate for that lesson
    afterwards; applying the old merge would delete that candidate unread and
    take its occurrences with it. Each lesson is re-read inside
    `state_lock(inbox/<lesson_id>.json)` -- the exact path
    `upsert_retrospective_candidate` locks -- so what gets merged is what is
    there, and what gets removed is what got merged.
    """

    written = 0
    for fold in folds:
        lesson_id = fold["lesson_id"]
        target = inbox / f"{lesson_id}.json"
        with state_lock(target):
            records, paths = _lesson_records_now(inbox, lesson_id, fold["paths"])
            if not records:
                continue
            temporary = target.with_suffix(".compact.tmp")
            temporary.write_text(
                json.dumps(merge_group(records), indent=1, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(target)
            written += 1
            for path in paths:
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
