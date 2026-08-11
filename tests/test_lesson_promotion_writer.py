"""A verified repair must be able to retire a lesson candidate.

Only `lessons/inbox` was ever written, so `accepted=0 promoted=0` was permanent
and one signature reached 89 occurrences with no way to record that it had been
fixed. Promotion joins a candidate to a run through the opaque occurrence key
that candidate already stores, so these tests pin that join: this run's
candidates move, unrelated historical ones do not, and a signature that returns
after a repair keeps counting instead of restarting.
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

from agent_lesson_store import (
    _opaque_occurrence_key,
    promote_repaired_candidates,
    upsert_retrospective_candidate,
)


RECEIPT = "receipt0000000000000001"


def _lesson(lesson_id, **extra):
    # update_index reads these by key, so a fixture missing one raises KeyError
    # rather than exercising promotion.
    record = {
        "lesson_id": lesson_id,
        "created_at": "2026-08-05T00:00:00+00:00",
        "promotion_status": "repair_required",
        "status": "candidate",
        "failure_type": "finish_gate_failure",
        "root_cause": "finish_failed_before_completion",
    }
    record.update(extra)
    return record


class PromoteRepairedCandidates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "lessons" / "inbox"
        self.promoted = self.root / "lessons" / "promoted"

    def _seed(self, lesson_id, occurrence_id):
        return upsert_retrospective_candidate(
            self.root, _lesson(lesson_id), occurrence_id=occurrence_id
        )

    def _promoted_record(self, lesson_id):
        return json.loads(
            (self.promoted / f"{lesson_id}.json").read_text(encoding="utf-8")
        )

    def test_missing_binding_promotes_nothing(self):
        self._seed("aaaa", "run-1")
        for occurrence_id, receipt in (("", RECEIPT), ("run-1", ""), ("", "")):
            with self.subTest(occurrence_id=occurrence_id, receipt=receipt):
                result = promote_repaired_candidates(
                    self.root, occurrence_id=occurrence_id, receipt_id=receipt
                )
                self.assertEqual(result["promoted"], [])
                self.assertEqual(result["reason"], "missing_repair_binding")
        self.assertTrue((self.inbox / "aaaa.json").exists())

    def test_absent_inbox_is_reported_not_raised(self):
        result = promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        self.assertEqual(result, {"promoted": [], "reason": "no_candidates"})

    def test_this_runs_candidate_is_promoted(self):
        self._seed("aaaa", "run-1")
        result = promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        self.assertEqual(result["promoted"], ["aaaa"])
        self.assertFalse((self.inbox / "aaaa.json").exists())
        record = self._promoted_record("aaaa")
        self.assertEqual(record["status"], "promoted")
        self.assertEqual(record["promotion_status"], "repair_verified")
        self.assertEqual(record["repair_receipt_id"], RECEIPT)

    def test_unrelated_historical_candidate_is_untouched(self):
        self._seed("mine", "run-1")
        self._seed("theirs", "run-other")
        result = promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        self.assertEqual(result["promoted"], ["mine"])
        self.assertTrue((self.inbox / "theirs.json").exists())
        self.assertFalse((self.promoted / "theirs.json").exists())

    def test_occurrence_keys_survive_promotion(self):
        self._seed("aaaa", "run-1")
        promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        record = self._promoted_record("aaaa")
        self.assertIn(_opaque_occurrence_key("run-1"), record["occurrence_keys"])

    def test_recurrence_after_repair_keeps_counting(self):
        first = self._seed("aaaa", "run-1")
        self.assertEqual(first["occurrence_count"], 1)
        promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        again = self._seed("aaaa", "run-2")
        self.assertEqual(again["occurrence_count"], 2)

    def test_repeated_run_after_repair_does_not_double_count(self):
        self._seed("aaaa", "run-1")
        promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        replay = self._seed("aaaa", "run-1")
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["occurrence_count"], 1)

    def test_malformed_records_are_skipped(self):
        (self.inbox).mkdir(parents=True, exist_ok=True)
        (self.inbox / "broken.json").write_text("{not json", encoding="utf-8")
        (self.inbox / "listy.json").write_text("[1]", encoding="utf-8")
        (self.inbox / "noid.json").write_text(
            json.dumps({"occurrence_keys": [_opaque_occurrence_key("run-1")]}),
            encoding="utf-8",
        )
        (self.inbox / "badkeys.json").write_text(
            json.dumps({"lesson_id": "badkeys", "occurrence_keys": "not-a-list"}),
            encoding="utf-8",
        )
        self._seed("good", "run-1")
        result = promote_repaired_candidates(
            self.root, occurrence_id="run-1", receipt_id=RECEIPT
        )
        self.assertEqual(result["promoted"], ["good"])

    def test_promotion_is_reflected_in_the_summary(self):
        import agent_global_lessons

        self._seed("aaaa", "run-1")
        original = agent_global_lessons.state_home
        agent_global_lessons.state_home = lambda: self.root
        self.addCleanup(lambda: setattr(agent_global_lessons, "state_home", original))

        before = agent_global_lessons.lesson_summary(limit=5)
        self.assertEqual(before["candidate_count"], 1)
        self.assertEqual(before["promoted"], [])

        agent_global_lessons.promote_lessons_for_repair("run-1", RECEIPT)

        after = agent_global_lessons.lesson_summary(limit=5)
        self.assertEqual(after["candidate_count"], 0)
        self.assertEqual(len(after["promoted"]), 1)


if __name__ == "__main__":
    unittest.main()
