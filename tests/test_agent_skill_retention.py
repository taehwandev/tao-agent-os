from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_os_maintenance import run_maintenance
from agent_skill_learning import (
    curate_observations,
    record_observation,
    review_candidate,
)
from agent_skill_maintenance import complete_verified_skill_maintenance
from agent_skill_draft import record_draft
from agent_skill_retention import prune_skill_learning_state


class AgentSkillRetentionTests(unittest.TestCase):
    def test_periodic_maintenance_runs_token_free_curation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            state_home = Path(temp_dir) / "state"
            project.mkdir()
            for occurrence_id in ("run-one", "run-two"):
                record_observation(
                    state_home,
                    occurrence_id=occurrence_id,
                    skill_id="verification_policy",
                    signal="weak_verification",
                )
            with patch.dict("os.environ", {"TAO_STATE_HOME": str(state_home)}):
                result = run_maintenance(project)

            self.assertEqual(1, result["skill_curation"]["ready_count"])
            self.assertEqual(1, len(result["skill_curation"]["queued"]))

    def test_curator_queue_and_passive_history_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(5):
                record_observation(
                    root,
                    occurrence_id=f"run-{index}",
                    skill_id=f"verification_policy_{index}",
                    signal="missing_rule",
                )
            retention = prune_skill_learning_state(root, max_observations=3)
            self.assertEqual(2, retention["removed_observations"])
            self.assertEqual(3, retention["kept_observations"])

            for skill_id in ("queue_one", "queue_two"):
                for occurrence_id in ("run-one", "run-two"):
                    record_observation(
                        root,
                        occurrence_id=f"{skill_id}_{occurrence_id}",
                        skill_id=skill_id,
                        signal="missing_rule",
                    )
            with patch("agent_skill_curator.MAX_REVIEW_QUEUE", 1):
                curated = curate_observations(root)
            self.assertEqual(1, curated["ready_count"])

    def test_review_rejects_tampered_queue_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="missing_rule")
            queue_path = root / "skill-learning" / "review-queue" / f"{candidate_id}.json"
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            payload.update(skill_id="PRIVATE USER TEXT", signal="/secret/path")
            queue_path.write_text(json.dumps(payload), encoding="utf-8")

            result = review_candidate(root, candidate_id, decision="no_change")
            self.assertFalse(result["updated"])
            self.assertFalse(
                (root / "skill-learning" / "completed" / f"{candidate_id}.json").exists()
            )

    def test_review_transition_rolls_back_without_split_brain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="execution_error")
            queue_path = root / "skill-learning" / "review-queue" / f"{candidate_id}.json"
            completed_path = root / "skill-learning" / "completed" / f"{candidate_id}.json"
            original_replace = Path.replace

            def fail_queue_move(path: Path, target: Path):
                if path == queue_path:
                    raise OSError("forced transition failure")
                return original_replace(path, target)

            with patch.object(Path, "replace", fail_queue_move):
                failed = review_candidate(root, candidate_id, decision="no_change")
            self.assertFalse(failed["updated"])
            self.assertTrue(queue_path.exists())
            self.assertFalse(completed_path.exists())
            self.assertEqual("review_ready", json.loads(queue_path.read_text())["status"])
            self.assertTrue(review_candidate(root, candidate_id, decision="no_change")["updated"])

    def test_maintenance_rejects_tampered_staged_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="stale_guidance")
            review_candidate(
                root,
                candidate_id,
                decision="stage_patch",
                gap_type="missing_rule",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )
            staged_path = root / "skill-learning" / "staged" / f"{candidate_id}.json"
            payload = json.loads(staged_path.read_text())
            payload["signal"] = "/private/path"
            staged_path.write_text(json.dumps(payload))
            result = complete_verified_skill_maintenance(
                root,
                project=root,
                rules=root,
                candidate_id=candidate_id,
                outcome="rejected",
            )
            self.assertFalse(result["updated"])

    def test_maintenance_applies_when_target_verifies_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "state"
            rules = Path(temp_dir) / "rules"
            (rules / "workflows" / "skills" / "verification_policy").mkdir(parents=True)
            target = rules / "workflows" / "skills" / "verification_policy" / "helper.py"
            target.write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=str(rules), check=True)
            subprocess.run(
                ["git", "add", "-A"], cwd=str(rules), check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "init"], cwd=str(rules), check=True
            )
            target.write_text("x = 2\n", encoding="utf-8")

            candidate_id = self._ready_candidate(root, signal="missing_rule")
            review_candidate(
                root,
                candidate_id,
                decision="stage_patch",
                gap_type="missing_rule",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )

            result = complete_verified_skill_maintenance(
                root,
                project=rules,
                rules=rules,
                candidate_id=candidate_id,
                outcome="applied",
                verification_kind="py_compile",
                target="workflows/skills/verification_policy/helper.py",
            )

            self.assertTrue(result["updated"])
            self.assertEqual("applied", result["status"])
            self.assertTrue(
                (root / "skill-learning" / "completed" / f"{candidate_id}.json").exists()
            )
            self.assertFalse(
                (root / "skill-learning" / "staged" / f"{candidate_id}.json").exists()
            )

    def test_maintenance_rejects_target_changed_during_verification(self) -> None:
        # Regression coverage for a TOCTOU window: the target's hash is
        # captured before running the verification command and re-checked
        # right after. If the file changes while the (possibly slow)
        # verification command is running -- e.g. another concurrent process
        # touches it -- the stale hash must not be allowed to back an
        # "applied" receipt.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "state"
            rules = Path(temp_dir) / "rules"
            (rules / "workflows" / "skills" / "verification_policy").mkdir(parents=True)
            target = rules / "workflows" / "skills" / "verification_policy" / "helper.py"
            target.write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=str(rules), check=True)
            subprocess.run(["git", "add", "-A"], cwd=str(rules), check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "init"], cwd=str(rules), check=True
            )
            target.write_text("x = 2\n", encoding="utf-8")

            candidate_id = self._ready_candidate(root, signal="weak_verification")
            review_candidate(
                root,
                candidate_id,
                decision="stage_patch",
                gap_type="missing_rule",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )

            def racy_runner(command, cwd):
                # Simulate the target changing again while the verification
                # command is "running".
                target.write_text("x = 3\n", encoding="utf-8")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with patch("agent_skill_maintenance.run_verification_command", racy_runner):
                result = complete_verified_skill_maintenance(
                    root,
                    project=rules,
                    rules=rules,
                    candidate_id=candidate_id,
                    outcome="applied",
                    verification_kind="py_compile",
                    target="workflows/skills/verification_policy/helper.py",
                )

            self.assertFalse(result["updated"])
            self.assertEqual("maintenance_target_changed_during_verification", result["reason"])
            self.assertTrue(
                (root / "skill-learning" / "staged" / f"{candidate_id}.json").exists()
            )
            self.assertFalse(
                (root / "skill-learning" / "completed" / f"{candidate_id}.json").exists()
            )

    def test_retention_is_strict_and_completed_candidates_do_not_resurrect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed_ids = []
            for index in range(2):
                candidate_id = self._ready_candidate(
                    root,
                    skill_id=f"verification_policy_{index}",
                    signal="missing_rule",
                )
                review_candidate(root, candidate_id, decision="no_change")
                completed_ids.append(candidate_id)
            retention = prune_skill_learning_state(root, max_observations=3, max_completed=1)
            curated = curate_observations(root)
            self.assertLessEqual(retention["kept_observations"], 3)
            self.assertTrue(set(completed_ids).isdisjoint(curated["queued"]))

    def test_evicted_completed_candidate_can_recur_from_new_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_skills: dict[str, str] = {}
            for skill_id in ("verification_policy_one", "verification_policy_two"):
                candidate_id = self._ready_candidate(
                    root,
                    skill_id=skill_id,
                    signal="missing_rule",
                )
                self.assertTrue(
                    review_candidate(root, candidate_id, decision="no_change")["updated"]
                )
                candidate_skills[candidate_id] = skill_id

            retention = prune_skill_learning_state(
                root,
                max_observations=10,
                max_completed=1,
            )
            evicted = [
                candidate_id
                for candidate_id in candidate_skills
                if not (
                    root
                    / "skill-learning"
                    / "completed"
                    / f"{candidate_id}.json"
                ).exists()
            ]
            self.assertEqual(1, retention["removed_completed"])
            self.assertEqual(1, len(evicted))

            candidate_id = evicted[0]
            for occurrence_id in ("new-run-one", "new-run-two"):
                record_observation(
                    root,
                    occurrence_id=occurrence_id,
                    skill_id=candidate_skills[candidate_id],
                    signal="missing_rule",
                )

            curated = curate_observations(root)

            self.assertIn(candidate_id, curated["queued"])

    def test_staged_queue_and_observations_have_hard_caps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="missing_rule")
            with patch("agent_skill_learning.MAX_STAGED", 0):
                result = review_candidate(
                    root,
                    candidate_id,
                    decision="stage_patch",
                    gap_type="missing_rule",
                    change_type="guidance_patch",
                    promotion_target="verification_policy",
                )
            self.assertEqual("staged_queue_full", result["reason"])

            for index in range(6):
                staged_id = self._ready_candidate(
                    root,
                    skill_id=f"staged_{index}",
                    signal="missing_rule",
                )
                review_candidate(
                    root,
                    staged_id,
                    decision="stage_patch",
                    gap_type="missing_rule",
                    change_type="guidance_patch",
                    promotion_target="verification_policy",
                )
            retention = prune_skill_learning_state(root, max_observations=3)
            self.assertEqual(3, retention["kept_observations"])

    def _ready_candidate(
        self,
        root: Path,
        *,
        skill_id: str = "verification_policy",
        signal: str,
    ) -> str:
        # One run may store only one observation, so each candidate needs its
        # own runs. Sharing "run-one"/"run-two" across candidates described a
        # history that cannot occur.
        for index in ("one", "two"):
            record_observation(
                root,
                occurrence_id=f"run-{skill_id}-{signal}-{index}",
                skill_id=skill_id,
                signal=signal,
            )
        result = curate_observations(root, min_occurrences=2)
        self.assertEqual(1, result["ready_count"])
        bundle = root / "common" / "skills" / skill_id.replace("_", "-")
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "SKILL.md").write_text("test skill\n", encoding="utf-8")
        record_draft(
            root,
            project=root,
            rules=root,
            skill_id=skill_id,
            signal=signal,
            proposal="A bounded test proposal describes the missing rule and its verification path.",
            occurrence_id=f"draft-{skill_id}-{signal}",
        )
        return str(result["queued"][0])


if __name__ == "__main__":
    unittest.main()
