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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_global_lessons
from agent_global_lessons import RECURRENCE_NOTICE_THRESHOLD, _top_recurring_candidate


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


if __name__ == "__main__":
    unittest.main()
