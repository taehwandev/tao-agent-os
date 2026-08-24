"""Folding a candidate inbox must be invisible to the store that reads it.

The writer already keeps one record per lesson, but only for lessons that
recur; a lesson that stopped happening keeps whatever files it had. On the
reference machine that left 824 legacy files beside 80 canonical ones -- 904
records for 296 lessons, read in full by every preflight.

The danger is that a lesson's occurrence count is the *sum* across its
records, so a plain delete would quietly reduce it. These tests hold the fold
to the store's own arithmetic: after folding, the next upsert must count what
it would have counted before.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_lesson_store import upsert_retrospective_candidate

_spec = importlib.util.spec_from_file_location("lessons_compact", SCRIPTS / "lessons-compact.py")
compact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compact)


def _candidate(lesson_id: str, created_at: str, **overrides) -> dict:
    record = {
        "schema_version": 1,
        "lesson_id": lesson_id,
        "created_at": created_at,
        "first_seen_at": created_at,
        "last_seen_at": created_at,
        "occurrence_count": 1,
        "occurrence_keys": [f"key-{created_at}"],
        "failure_type": "finish_gate_failure",
        "root_cause": "finish_failed_before_completion",
        "promotion_status": "candidate",
        "status": "candidate",
    }
    record.update(overrides)
    return record


class CompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.inbox = compact.inbox_path(self.state)
        self.inbox.mkdir(parents=True)

    def _write(self, name: str, record: dict) -> Path:
        path = self.inbox / name
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def _files(self) -> set[str]:
        return {path.name for path in self.inbox.glob("*.json")}

    def test_the_merged_count_is_the_sum_the_store_reads(self) -> None:
        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )

        merged = compact.merge_group(
            [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.inbox.glob("*.json"))]
        )

        self.assertEqual(3, merged["occurrence_count"])
        self.assertEqual("2026-01-01T00:00:00Z", merged["first_seen_at"])
        self.assertEqual("2026-01-03T00:00:00Z", merged["last_seen_at"])
        self.assertEqual(3, len(merged["occurrence_keys"]))

    def test_the_next_upsert_counts_what_it_would_have_counted(self) -> None:
        """The fold has to be invisible to the store, not merely tidy."""

        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )
        before = upsert_retrospective_candidate(
            self.state,
            _candidate("abc", "2026-02-01T00:00:00Z"),
            occurrence_id="fresh-one",
        )["occurrence_count"]

        self.setUp()
        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )
        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])
        after = upsert_retrospective_candidate(
            self.state,
            _candidate("abc", "2026-02-01T00:00:00Z"),
            occurrence_id="fresh-one",
        )["occurrence_count"]

        self.assertEqual(before, after)

    def test_folding_leaves_one_canonical_file(self) -> None:
        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        self._write("20260101-def.json", _candidate("def", "2026-01-01T00:00:00Z"))

        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])

        self.assertEqual({"abc.json", "def.json"}, self._files())

    def test_a_lesson_already_canonical_and_alone_is_left_alone(self) -> None:
        self._write("abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        self.assertEqual([], compact.plan(self.inbox)["folds"])

    def test_a_report_writes_nothing(self) -> None:
        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        before = self._files()

        compact.plan(self.inbox)

        self.assertEqual(before, self._files())

    def test_an_unreadable_record_is_reported_and_untouched(self) -> None:
        (self.inbox / "broken.json").write_text("{not json", encoding="utf-8")
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertEqual([self.inbox / "broken.json"], report["unreadable"])
        self.assertIn("broken.json", self._files())

    def test_a_record_without_a_lesson_id_is_never_merged_into_another(self) -> None:
        self._write("nameless.json", _candidate("", "2026-01-01T00:00:00Z"))
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertIn("nameless.json", self._files())
        self.assertIn("abc.json", self._files())


    def test_the_command_without_apply_changes_nothing(self) -> None:
        """The dry run is the safety property, so it is tested through main."""

        import io
        from contextlib import redirect_stdout

        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        before = {path.name: path.read_text(encoding="utf-8") for path in self.inbox.glob("*.json")}

        output = io.StringIO()
        with redirect_stdout(output):
            code = compact.main_with_arguments(["--state-home", str(self.state)])

        after = {path.name: path.read_text(encoding="utf-8") for path in self.inbox.glob("*.json")}
        self.assertEqual(0, code)
        self.assertEqual(before, after)
        self.assertIn("nothing written", output.getvalue())

    def test_the_command_with_apply_folds(self) -> None:
        import io
        from contextlib import redirect_stdout

        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))

        with redirect_stdout(io.StringIO()):
            compact.main_with_arguments(["--state-home", str(self.state), "--apply"])

        self.assertEqual({"abc.json"}, self._files())

    def test_a_record_that_is_not_an_object_is_left_alone(self) -> None:
        """Valid JSON is not the same as a lesson."""

        (self.inbox / "list.json").write_text("[]", encoding="utf-8")
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertIn(self.inbox / "list.json", report["unreadable"])
        self.assertIn("list.json", self._files())

    def test_nothing_outside_the_inbox_is_read_or_written(self) -> None:
        promoted = self.state / "lessons" / "promoted"
        promoted.mkdir(parents=True)
        (promoted / "abc.json").write_text(
            json.dumps(_candidate("abc", "2026-01-01T00:00:00Z")), encoding="utf-8"
        )
        self._write("20260101-abc.json", _candidate("abc", "2026-01-02T00:00:00Z"))

        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])

        self.assertEqual({"abc.json"}, {path.name for path in promoted.glob("*.json")})
        self.assertEqual(
            1,
            json.loads((promoted / "abc.json").read_text(encoding="utf-8"))["occurrence_count"],
        )


if __name__ == "__main__":
    unittest.main()
