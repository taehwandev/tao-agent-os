"""A recurring lesson signature must be named, not just counted.

`candidates=37` was reported alongside a clean finish while one signature had
already recurred 89 times without repair. The count alone reads as bookkeeping,
so the summary now names the worst offender once it crosses the notice
threshold. These tests pin that behavior and its privacy boundary.
"""

from __future__ import annotations

import json
import sys
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_global_lessons
from agent_global_lessons import RECURRENCE_NOTICE_THRESHOLD, _inbox_summary


def _top_recurring_candidate(path):
    """The notice half of the single inbox pass, for the tests written on it."""

    return _inbox_summary(path)["top_recurrence"]


ALLOWED_KEYS = {"lesson_id", "failure_type", "occurrence_count", "promotion_status"}


def _candidate(lesson_id, count, failure_type="finish_gate_failure", **extra):
    record = {
        "lesson_id": lesson_id,
        "occurrence_count": count,
        "failure_type": failure_type,
        "promotion_status": "repair_required",
        "status": "candidate",
    }
    record.update(extra)
    return record


class TopRecurringCandidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = Path(self.tmp.name) / "lessons" / "inbox"
        self.inbox.mkdir(parents=True)

    def _write(self, *records):
        for record in records:
            path = self.inbox / f"{record['lesson_id']}.json"
            path.write_text(json.dumps(record), encoding="utf-8")

    def test_missing_inbox_is_silent(self):
        self.assertEqual(_top_recurring_candidate(self.inbox.parent / "absent"), {})

    def test_empty_inbox_is_silent(self):
        self.assertEqual(_top_recurring_candidate(self.inbox), {})

    def test_below_threshold_stays_silent(self):
        self._write(_candidate("aaaa", RECURRENCE_NOTICE_THRESHOLD - 1))
        self.assertEqual(_top_recurring_candidate(self.inbox), {})

    def test_at_threshold_is_named(self):
        self._write(_candidate("aaaa", RECURRENCE_NOTICE_THRESHOLD))
        top = _top_recurring_candidate(self.inbox)
        self.assertEqual(top.get("lesson_id"), "aaaa")
        self.assertEqual(top.get("occurrence_count"), RECURRENCE_NOTICE_THRESHOLD)

    def test_reports_the_highest_count(self):
        self._write(
            _candidate("low", 4),
            _candidate("high", 89, failure_type="missed_required_gate"),
            _candidate("mid", 22),
        )
        top = _top_recurring_candidate(self.inbox)
        self.assertEqual(top.get("lesson_id"), "high")
        self.assertEqual(top.get("occurrence_count"), 89)
        self.assertEqual(top.get("failure_type"), "missed_required_gate")

    def test_unreadable_and_malformed_records_are_skipped(self):
        (self.inbox / "broken.json").write_text("{not json", encoding="utf-8")
        (self.inbox / "list.json").write_text("[1, 2]", encoding="utf-8")
        (self.inbox / "nocount.json").write_text(
            json.dumps({"lesson_id": "nocount"}), encoding="utf-8"
        )
        self._write(_candidate("good", 7))
        self.assertEqual(_top_recurring_candidate(self.inbox).get("lesson_id"), "good")

    def test_non_integer_and_boolean_counts_are_ignored(self):
        (self.inbox / "str.json").write_text(
            json.dumps({"lesson_id": "str", "occurrence_count": "99"}), encoding="utf-8"
        )
        (self.inbox / "bool.json").write_text(
            json.dumps({"lesson_id": "bool", "occurrence_count": True}), encoding="utf-8"
        )
        self.assertEqual(_top_recurring_candidate(self.inbox), {})

    def test_only_safe_fields_are_exposed(self):
        self._write(
            _candidate(
                "aaaa",
                9,
                request="secret request text",
                path="/Users/someone/private/repo",
            )
        )
        top = _top_recurring_candidate(self.inbox)
        self.assertEqual(set(top), ALLOWED_KEYS)


class LessonSummaryIncludesRecurrence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "lessons" / "inbox").mkdir(parents=True)
        record = _candidate("aaaa", 42)
        (root / "lessons" / "inbox" / "aaaa.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
        original = agent_global_lessons.state_home
        agent_global_lessons.state_home = lambda: root
        self.addCleanup(lambda: setattr(agent_global_lessons, "state_home", original))

    def test_summary_carries_top_recurrence(self):
        summary = agent_global_lessons.lesson_summary(limit=1)
        self.assertEqual(summary["top_recurrence"]["occurrence_count"], 42)
        self.assertEqual(summary["candidate_count"], 1)



class InboxSummaryIsOnePassTests(unittest.TestCase):
    """Counting the candidates and finding the worst one read the inbox twice.

    On the reference machine that is 904 files and 3.5 MB, walked twice on
    every preflight -- 37 ms warm, and it grows with the store rather than with
    the work. One pass answers both, and must answer them identically.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.inbox = Path(self.directory.name) / "inbox"
        self.inbox.mkdir()

    def _write(self, name: str, payload: dict) -> None:
        (self.inbox / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_both_answers_come_from_one_walk(self) -> None:
        opened: list[str] = []
        for index in range(4):
            self._write(f"lesson{index}", {
                "lesson_id": f"id{index}",
                "occurrence_count": index + RECURRENCE_NOTICE_THRESHOLD,
                "failure_type": "missed_required_gate",
                "promotion_status": "repair_required",
            })
        real = Path.read_text

        def counting(self, *args, **keywords):
            opened.append(self.name)
            return real(self, *args, **keywords)

        with patch.object(Path, "read_text", counting):
            summary = _inbox_summary(self.inbox)

        self.assertEqual(4, summary["candidate_count"])
        self.assertEqual("id3", summary["top_recurrence"]["lesson_id"])
        self.assertEqual(4, len(opened), opened)

    def test_repeated_lesson_ids_count_once(self) -> None:
        self._write("a", {"lesson_id": "same", "occurrence_count": 1})
        self._write("b", {"lesson_id": "same", "occurrence_count": 1})

        self.assertEqual(1, _inbox_summary(self.inbox)["candidate_count"])

    def test_an_absent_inbox_is_empty_not_an_error(self) -> None:
        summary = _inbox_summary(self.inbox.parent / "absent")

        self.assertEqual(0, summary["candidate_count"])
        self.assertEqual({}, summary["top_recurrence"])

    def test_an_unreadable_record_is_skipped_by_both_answers(self) -> None:
        self._write("good", {"lesson_id": "good", "occurrence_count": RECURRENCE_NOTICE_THRESHOLD})
        (self.inbox / "broken.json").write_text("{not json", encoding="utf-8")

        summary = _inbox_summary(self.inbox)

        self.assertEqual(1, summary["candidate_count"])
        self.assertEqual("good", summary["top_recurrence"]["lesson_id"])

if __name__ == "__main__":
    unittest.main()
