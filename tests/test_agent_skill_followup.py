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

from agent_skill_curator import curate_observations
from agent_skill_followup import skill_followup_failures
from agent_skill_learning import record_observation, review_candidate
from agent_skill_state import completed_path


class AgentSkillFollowupTests(unittest.TestCase):
    def test_one_occurrence_does_not_require_followup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._observe(root, "run-one")

            self.assertEqual([], self._failures(root, "run-one"))

    def test_second_occurrence_reports_curation_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe_twice(root)

            self.assertEqual(
                [f"skill follow-up curation pending: candidate={candidate}"],
                self._failures(root, "run-two"),
            )

    def test_unrelated_historical_queue_does_not_block_current_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._observe_twice(root, skill_id="testing", signal="weak_verification")
            curate_observations(root)
            self._observe(root, "current-run")

            self.assertEqual([], self._failures(root, "current-run"))

    def test_review_ready_reports_bounded_review_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe_twice(root)
            curate_observations(root)

            self.assertEqual(
                [f"skill follow-up bounded review pending: candidate={candidate}"],
                self._failures(root, "run-two"),
            )

    def test_staged_reports_verified_maintenance_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe_twice(root)
            curate_observations(root)
            reviewed = review_candidate(
                root,
                candidate,
                decision="stage_patch",
                gap_type="missing_rule",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )
            self.assertTrue(reviewed["updated"])

            self.assertEqual(
                [f"skill follow-up verified maintenance pending: candidate={candidate}"],
                self._failures(root, "run-two"),
            )

    def test_completed_terminal_states_satisfy_followup(self) -> None:
        for outcome in ("no_change", "applied", "rejected"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                candidate = self._observe_twice(root)
                curate_observations(root)
                if outcome == "no_change":
                    review_candidate(root, candidate, decision="no_change")
                else:
                    review_candidate(
                        root,
                        candidate,
                        decision="stage_patch",
                        gap_type="missing_rule",
                        change_type="guidance_patch",
                        promotion_target="verification_policy",
                    )
                    staged = root / "skill-learning" / "staged" / f"{candidate}.json"
                    payload = json.loads(staged.read_text(encoding="utf-8"))
                    payload.update(
                        status=outcome,
                        maintenance_outcome=outcome,
                        verification_kind=("unittest" if outcome == "applied" else "not_applicable"),
                        next_action="none",
                    )
                    completed = root / completed_path(candidate)
                    completed.parent.mkdir(parents=True, exist_ok=True)
                    completed.write_text(json.dumps(payload), encoding="utf-8")
                    staged.unlink()

                self.assertEqual([], self._failures(root, "run-two"))

    def test_matching_malformed_records_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe_twice(root)
            curate_observations(root)
            queued = root / "skill-learning" / "review-queue" / f"{candidate}.json"
            payload = json.loads(queued.read_text(encoding="utf-8"))
            payload["privacy"] = "unsafe"
            queued.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual(
                [f"skill follow-up state invalid: candidate={candidate}"],
                self._failures(root, "run-two"),
            )

    def test_malformed_current_observation_fails_without_exposing_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe(root, "private-current-run")
            observation = next((root / "skill-learning" / "observations").glob("*.json"))
            payload = json.loads(observation.read_text(encoding="utf-8"))
            payload["observation_id"] = "0" * 16
            observation.write_text(json.dumps(payload), encoding="utf-8")

            failures = self._failures(root, "private-current-run")

            self.assertEqual(
                [f"skill follow-up current observation invalid: candidate={candidate}"],
                failures,
            )
            self.assertNotIn("private-current-run", " ".join(failures))

    def test_negative_control_removing_completion_restores_pending_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = self._observe_twice(root)
            curate_observations(root)
            review_candidate(root, candidate, decision="no_change")
            self.assertEqual([], self._failures(root, "run-two"))

            (root / completed_path(candidate)).unlink()

            self.assertEqual(
                [f"skill follow-up curation pending: candidate={candidate}"],
                self._failures(root, "run-two"),
            )

    def _observe_twice(
        self,
        root: Path,
        *,
        skill_id: str = "verification_policy",
        signal: str = "missing_rule",
    ) -> str:
        self._observe(root, "run-one", skill_id=skill_id, signal=signal)
        return self._observe(root, "run-two", skill_id=skill_id, signal=signal)

    def _observe(
        self,
        root: Path,
        occurrence: str,
        *,
        skill_id: str = "verification_policy",
        signal: str = "missing_rule",
    ) -> str:
        result = record_observation(
            root,
            occurrence_id=occurrence,
            skill_id=skill_id,
            signal=signal,
        )
        return str(result["candidate_id"])

    def _failures(self, root: Path, occurrence: str) -> list[str]:
        return skill_followup_failures(
            state_root=root,
            preflight={"agent_run_id": occurrence},
        )


if __name__ == "__main__":
    unittest.main()
