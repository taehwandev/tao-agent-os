from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_skill_backlog import format_skill_backlog, skill_backlog_summary


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class SkillBacklogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for stage in ("observations", "review-queue", "staged"):
            (self.root / "skill-learning" / stage).mkdir(parents=True)

    def write(self, stage: str, name: str, payload: dict) -> Path:
        path = self.root / "skill-learning" / stage / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_empty_backlog_prints_nothing(self) -> None:
        summary = skill_backlog_summary(self.root)
        self.assertEqual(0, summary["waiting"])
        self.assertIsNone(summary["oldest_age_days"])
        self.assertEqual("", format_skill_backlog(summary))

    def test_missing_state_directories_report_empty_rather_than_raise(self) -> None:
        summary = skill_backlog_summary(self.root / "nothing-here")
        self.assertEqual(
            {"observed": 0, "queued": 0, "staged": 0, "waiting": 0}, {
                key: summary[key] for key in ("observed", "queued", "staged", "waiting")
            }
        )
        self.assertEqual("", format_skill_backlog(summary))

    def test_oldest_entry_wins_across_both_waiting_stages(self) -> None:
        old = "a" * 16
        newer = "b" * 16
        self.write("review-queue", newer, {"candidate_id": newer, "queued_at": ago(3)})
        # A staged record carries `queued_at` forward from its queued state, so
        # the age is measured from entry to the pipeline, not from the review.
        self.write("staged", old, {
            "candidate_id": old, "queued_at": ago(25), "reviewed_at": ago(1)
        })
        summary = skill_backlog_summary(self.root)
        self.assertEqual((1, 1, 2), (summary["queued"], summary["staged"], summary["waiting"]))
        self.assertEqual(25, summary["oldest_age_days"])
        self.assertEqual(old, summary["oldest_candidate"])
        line = format_skill_backlog(summary)
        self.assertIn("1 awaiting review, 1 staged", line)
        self.assertIn(f"oldest 25d (candidate {old})", line)

    def test_uncurated_observations_are_counted_but_never_aged(self) -> None:
        # An observation has no queue age of its own, and counting the files
        # avoids reading records whose remedy is identical either way.
        for index in range(3):
            self.write("observations", f"obs{index}", {"created_at": ago(90)})
        summary = skill_backlog_summary(self.root)
        self.assertEqual(3, summary["observed"])
        self.assertEqual(0, summary["waiting"])
        self.assertIsNone(summary["oldest_age_days"])
        self.assertEqual("", format_skill_backlog(summary))
        self.write("review-queue", "c" * 16, {"candidate_id": "c" * 16, "queued_at": ago(1)})
        self.assertIn("3 uncurated", format_skill_backlog(skill_backlog_summary(self.root)))

    def test_unusable_records_still_count_and_never_raise(self) -> None:
        good = "d" * 16
        self.write("review-queue", good, {"candidate_id": good, "queued_at": ago(9)})
        self.write("review-queue", "no-timestamp", {"candidate_id": "e" * 16})
        self.write("review-queue", "wrong-type", {"queued_at": 12345})
        self.write("review-queue", "unparseable", {"queued_at": "the day before"})
        (self.root / "skill-learning" / "review-queue" / "broken.json").write_text(
            "{not json", encoding="utf-8"
        )
        summary = skill_backlog_summary(self.root)
        self.assertEqual(5, summary["queued"])
        self.assertEqual(9, summary["oldest_age_days"])
        self.assertEqual(good, summary["oldest_candidate"])

    def test_naive_timestamp_is_read_as_utc_instead_of_raising(self) -> None:
        naive = (datetime.now(timezone.utc) - timedelta(days=4)).replace(tzinfo=None)
        self.write("review-queue", "f" * 16, {
            "candidate_id": "f" * 16, "queued_at": naive.isoformat()
        })
        self.assertEqual(4, skill_backlog_summary(self.root)["oldest_age_days"])

    def test_unsafe_candidate_id_is_dropped_from_the_line(self) -> None:
        self.write("review-queue", "odd", {
            "candidate_id": "../../etc/passwd", "queued_at": ago(6)
        })
        summary = skill_backlog_summary(self.root)
        self.assertEqual(6, summary["oldest_age_days"])
        self.assertEqual("", summary["oldest_candidate"])
        line = format_skill_backlog(summary)
        self.assertIn("oldest 6d;", line)
        self.assertNotIn("passwd", line)

    def test_future_timestamp_reports_zero_rather_than_a_negative_age(self) -> None:
        self.write("review-queue", "0" * 16, {
            "candidate_id": "0" * 16, "queued_at": ago(-5)
        })
        self.assertEqual(0, skill_backlog_summary(self.root)["oldest_age_days"])


if __name__ == "__main__":
    unittest.main()
