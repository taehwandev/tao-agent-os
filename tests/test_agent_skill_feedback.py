from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_skill_feedback as feedback


class AgentSkillFeedbackTests(unittest.TestCase):
    def test_routine_history_is_grouped_without_hiding_current_candidate(self):
        items = [
            {"candidate_id": f"old-{i}", "reason": "closed_review_no_new_gap"}
            for i in range(100)
        ] + [
            {"candidate_id": f"queued-{i}", "reason": "already_awaiting_review"}
            for i in range(100)
        ]
        original = copy.deepcopy(items)
        lines = feedback._declined_curation_details(
            items, focus_candidate_id="old-99"
        )
        self.assertEqual(3, len(lines))
        self.assertIn("observations not queued for review: 200", lines[0])
        self.assertIn("old-99", lines[1])
        self.assertIn("--feedback-gap", lines[1])
        self.assertIn("100 candidates total", lines[1])
        self.assertIn("already_awaiting_review", lines[2])
        self.assertEqual(original, items)

    def test_exceptional_and_unknown_diagnoses_stay_individual(self):
        for reason in (
            "unreadable_completed_record", "ambiguous_completed_aliases",
            "some_future_reason",
        ):
            with self.subTest(reason=reason):
                lines = feedback._declined_curation_details([
                    {"candidate_id": "first", "reason": reason},
                    {"candidate_id": "second", "reason": reason},
                ])
                self.assertEqual(3, len(lines))
                self.assertIn("first", lines[1])
                self.assertIn("second", lines[2])
                self.assertIn(reason, lines[1])
                self.assertNotIn("candidates total", "\n".join(lines))

    def test_feedback_retains_full_curation_data_and_current_remedy(self):
        items = [
            {"candidate_id": "old", "reason": "closed_review_no_new_gap"},
            {"candidate_id": "current", "reason": "closed_review_no_new_gap"},
        ]
        curation = {
            "scanned": 2, "ready_count": 0, "legacy_mapped_count": 0,
            "legacy_unmapped_count": 0, "not_queued": items, "queued": [],
        }
        with tempfile.TemporaryDirectory() as temp, patch.multiple(
            feedback,
            canonical_skill_ids=lambda *_: {"agent_operating_skill"},
            state_home=lambda: Path(temp),
            _retrospective_fields=lambda *_: {
                "skills_checked": "agent_operating_skill",
                "outcome": "reusable_gap", "observation": "recorded",
            },
            _occurrence_id=lambda *_: "test-run",
            record_observation=lambda *_args, **_kwargs: {
                "created": True, "candidate_id": "current", "status": "observed",
            },
            curate_observations=lambda *_args, **_kwargs: copy.deepcopy(curation),
            prune_skill_learning_state=lambda *_: {},
        ):
            result, lines = feedback.record_skill_feedback(
                project=Path(temp), rules=Path(temp), evidence_path=Path(temp) / "preflight.json",
                outcome="observed", skill_id="agent_operating_skill",
                signal="ambiguous_decision",
            )
        self.assertEqual(items, result["curation"]["not_queued"])
        printed = "\n".join(lines)
        self.assertIn("current: closed_review_no_new_gap", printed)
        self.assertIn("--feedback-gap", printed)
        self.assertNotIn("old: closed_review_no_new_gap", printed)


if __name__ == "__main__":
    unittest.main()
