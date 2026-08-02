from __future__ import annotations

import json
import inspect
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

import agent_global_lessons
import agent_lesson_store
import agent_skill_learning
import agent_skill_maintenance
from agent_review_hook import review_outcome_failures
from agent_skill_catalog import (
    FEEDBACK_SIGNALS,
    LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION,
)
from agent_skill_learning import (
    curate_observations,
    record_observation,
    review_candidate,
)
from agent_skill_maintenance import complete_verified_skill_maintenance
from agent_skill_retention import prune_skill_learning_state
from agent_skill_state import candidate_id, observation_dir, opaque_key
from workflow_route import route_hooks


class AgentSkillLearningTests(unittest.TestCase):
    def test_legacy_single_hop_exports_are_removed(self) -> None:
        self.assertFalse(hasattr(agent_global_lessons, "process_skill_feedback"))
        self.assertFalse(hasattr(agent_global_lessons, "skill_feedback_candidate"))
        self.assertFalse(hasattr(agent_lesson_store, "upsert_candidate"))
        self.assertFalse(hasattr(agent_lesson_store, "promote_candidate"))
        self.assertFalse(hasattr(agent_skill_learning, "complete_maintenance"))
        self.assertFalse(hasattr(agent_skill_maintenance, "_record_verified_application"))
        self.assertEqual(
            ["complete_verified_skill_maintenance"],
            agent_skill_maintenance.__all__,
        )
        parameters = inspect.signature(
            agent_skill_maintenance.complete_verified_skill_maintenance
        ).parameters
        self.assertNotIn("runner", parameters)
        self.assertNotIn("verification_receipt", parameters)

    def test_one_run_stores_at_most_one_observation(self) -> None:
        """The contract binds the limit to the run, not to the candidate.

        Deduplicating per candidate let two different skill/signal pairs from
        the same run each pass their own existence check, so one run
        contributed two observations toward two separate recurrence counts.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            first = record_observation(
                root, occurrence_id="run-1",
                skill_id="verification_policy", signal="weak_verification",
            )
            second = record_observation(
                root, occurrence_id="run-1",
                skill_id="testing", signal="missing_rule",
            )

            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual("occurrence_already_observed", second["reason"])
            stored = list((root / "skill-learning" / "observations").rglob("*.json"))
            self.assertEqual(1, len(stored))

    def test_a_different_run_may_still_observe_the_same_gap(self) -> None:
        """Negative control: the limit is per run, not a global one."""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_observation(
                root, occurrence_id="run-1",
                skill_id="verification_policy", signal="weak_verification",
            )
            later = record_observation(
                root, occurrence_id="run-2",
                skill_id="verification_policy", signal="weak_verification",
            )

            self.assertTrue(later["created"])

    def test_observation_replay_is_idempotent_and_content_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            first = record_observation(
                root,
                occurrence_id="private-runtime-run-one",
                skill_id="verification_policy",
                signal="weak_verification",
            )
            replay = record_observation(
                root,
                occurrence_id="private-runtime-run-one",
                skill_id="verification_policy",
                signal="weak_verification",
            )
            distinct = record_observation(
                root,
                occurrence_id="private-runtime-run-two",
                skill_id="verification_policy",
                signal="weak_verification",
            )

            self.assertTrue(first["created"])
            self.assertFalse(first["idempotent"])
            self.assertFalse(replay["created"])
            self.assertTrue(replay["idempotent"])
            self.assertEqual(first["observation_id"], replay["observation_id"])
            self.assertTrue(distinct["created"])
            self.assertNotEqual(first["observation_id"], distinct["observation_id"])

            persisted = "\n".join(
                path.read_text(encoding="utf-8") for path in root.rglob("*.json")
            )
            self.assertNotIn("private-runtime-run-one", persisted)
            self.assertNotIn("private-runtime-run-two", persisted)

    def test_curator_queues_review_only_after_two_distinct_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_observation(
                root,
                occurrence_id="run-one",
                skill_id="verification_policy",
                signal="weak_verification",
            )

            first = curate_observations(root, min_occurrences=2)
            self.assertEqual([], first["queued"])
            self.assertEqual(0, first["ready_count"])

            # A replay of the same run is not a second occurrence.
            record_observation(
                root,
                occurrence_id="run-one",
                skill_id="verification_policy",
                signal="weak_verification",
            )
            replay = curate_observations(root, min_occurrences=2)
            self.assertEqual([], replay["queued"])
            self.assertEqual(0, replay["ready_count"])

            record_observation(
                root,
                occurrence_id="run-two",
                skill_id="verification_policy",
                signal="weak_verification",
            )
            ready = curate_observations(root, min_occurrences=2)

            self.assertEqual(1, len(ready["queued"]))
            self.assertEqual(1, ready["ready_count"])
            self.assertGreaterEqual(ready["scanned"], 1)

            repeated_curation = curate_observations(root, min_occurrences=2)
            self.assertEqual([], repeated_curation["queued"])
            self.assertEqual(0, repeated_curation["ready_count"])

    def test_legacy_observations_use_exact_mapping_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = [
                self._write_legacy_observation(
                    root,
                    occurrence_id=occurrence_id,
                    skill_id="verification_policy",
                    signal="worker_self_reported_counts_unverified",
                )
                for occurrence_id in ("run-one", "run-two")
            ]
            original_bytes = [path.read_bytes() for path in paths]

            curated = curate_observations(root)

            self.assertEqual(1, LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION)
            self.assertEqual(2, curated["legacy_mapped_count"])
            self.assertEqual(0, curated["legacy_unmapped_count"])
            self.assertEqual(1, curated["ready_count"])
            canonical_candidate = candidate_id(
                "verification_policy",
                "weak_verification",
            )
            self.assertEqual([canonical_candidate], curated["queued"])
            queued = json.loads(
                (
                    root
                    / "skill-learning"
                    / "review-queue"
                    / f"{canonical_candidate}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("weak_verification", queued["signal"])
            self.assertEqual(original_bytes, [path.read_bytes() for path in paths])
            prune_skill_learning_state(root)
            self.assertTrue(
                (
                    root
                    / "skill-learning"
                    / "review-queue"
                    / f"{canonical_candidate}.json"
                ).exists()
            )
            self.assertTrue(
                review_candidate(root, canonical_candidate, decision="no_change")[
                    "updated"
                ]
            )

    def test_unmapped_legacy_observations_are_retained_and_diagnosed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = [
                self._write_legacy_observation(
                    root,
                    occurrence_id=occurrence_id,
                    skill_id="verification_policy",
                    signal="unrecognized_old_signal",
                )
                for occurrence_id in ("run-one", "run-two")
            ]
            original_bytes = [path.read_bytes() for path in paths]

            curated = curate_observations(root)

            self.assertEqual(0, curated["legacy_mapped_count"])
            self.assertEqual(2, curated["legacy_unmapped_count"])
            self.assertEqual(0, curated["scanned"])
            self.assertEqual([], curated["queued"])
            self.assertEqual(original_bytes, [path.read_bytes() for path in paths])

    def test_feedback_signal_vocabulary_is_discoverable_in_cli_and_route_hooks(self) -> None:
        help_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "agent-hook.py"),
                "skill-feedback",
                "--help",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        hook_command = next(
            hook["command"]
            for hook in route_hooks("bugfix")
            if hook["hook"] == "skill-feedback"
        )
        for signal in FEEDBACK_SIGNALS:
            with self.subTest(signal=signal):
                self.assertIn(signal, help_result.stdout)
                self.assertIn(signal, hook_command)

        invalid = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "agent-hook.py"),
                "skill-feedback",
                "--feedback-signal",
                "custom_evidence_binding",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(2, invalid.returncode)
        self.assertIn("invalid choice", invalid.stderr)

    def test_no_change_review_closes_candidate_without_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="missing_rule")

            reviewed = review_candidate(root, candidate_id, decision="no_change")

            self.assertTrue(reviewed["updated"])
            self.assertEqual(candidate_id, reviewed["candidate_id"])
            self.assertEqual("no_change", reviewed["status"])
            refused = complete_verified_skill_maintenance(
                root,
                project=root,
                rules=root,
                candidate_id=candidate_id,
                outcome="applied",
                verification_kind="unittest",
                target="missing/SKILL.md",
                test_selector="tests.test_agent_skill_learning",
            )
            self.assertFalse(refused["updated"])
            self.assertEqual("candidate_not_staged", refused["reason"])

    def test_stage_patch_is_staged_only_and_completion_requires_staged_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical_skill = (
                root / "common" / "skills" / "verification-policy" / "SKILL.md"
            )
            canonical_skill.parent.mkdir(parents=True)
            canonical_skill.write_text("canonical skill sentinel\n", encoding="utf-8")
            candidate_id = self._ready_candidate(root, signal="weak_verification")

            staged = review_candidate(
                root,
                candidate_id,
                decision="stage_patch",
                gap_type="missing_verification_rule",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )

            self.assertTrue(staged["updated"])
            self.assertEqual(candidate_id, staged["candidate_id"])
            self.assertEqual("staged_patch", staged["status"])
            self.assertEqual("canonical skill sentinel\n", canonical_skill.read_text())

            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", canonical_skill.relative_to(root)], cwd=root, check=True)
            with patch(
                "agent_skill_maintenance.run_verification_command",
                return_value={"returncode": 1},
            ):
                failed_verification = complete_verified_skill_maintenance(
                    root,
                    project=root,
                    rules=root,
                    candidate_id=candidate_id,
                    outcome="applied",
                    verification_kind="unittest",
                    target=str(canonical_skill.relative_to(root)),
                    test_selector="tests.test_skill_maintenance",
                )
            self.assertFalse(failed_verification["updated"])
            self.assertEqual("maintenance_verification_failed", failed_verification["reason"])
            def change_target_during_verification(_command: list[str], _cwd: Path):
                canonical_skill.write_text("changed during verification\n", encoding="utf-8")
                return {"returncode": 0}

            with patch(
                "agent_skill_maintenance.run_verification_command",
                side_effect=change_target_during_verification,
            ):
                raced = complete_verified_skill_maintenance(
                    root,
                    project=root,
                    rules=root,
                    candidate_id=candidate_id,
                    outcome="applied",
                    verification_kind="unittest",
                    target=str(canonical_skill.relative_to(root)),
                    test_selector="tests.test_skill_maintenance",
                )
            self.assertFalse(raced["updated"])
            self.assertEqual(
                "maintenance_target_changed_during_verification",
                raced["reason"],
            )
            canonical_skill.write_text("canonical skill sentinel\n", encoding="utf-8")
            (root / "test_skill_maintenance.py").write_text(
                "import unittest\n\n"
                "class LiveVerificationTest(unittest.TestCase):\n"
                "    def test_live_command(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            completed = complete_verified_skill_maintenance(
                root,
                project=root,
                rules=root,
                candidate_id=candidate_id,
                outcome="applied",
                verification_kind="unittest",
                target=str(canonical_skill.relative_to(root)),
                test_selector="test_skill_maintenance",
            )
            self.assertTrue(completed["updated"])
            self.assertEqual(candidate_id, completed["candidate_id"])
            self.assertEqual("applied", completed["status"])
            self.assertEqual("unittest", completed["verification_kind"])
            self.assertEqual("canonical skill sentinel\n", canonical_skill.read_text())

            rejected_id = self._ready_candidate(root, signal="ambiguous_decision")
            review_candidate(
                root,
                rejected_id,
                decision="stage_patch",
                gap_type="unsafe_default",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )
            rejected = complete_verified_skill_maintenance(
                root,
                project=root,
                rules=root,
                candidate_id=rejected_id,
                outcome="rejected",
            )
            self.assertTrue(rejected["updated"])
            self.assertEqual("rejected", rejected["status"])
            self.assertEqual("canonical skill sentinel\n", canonical_skill.read_text())

    def test_unsafe_slugs_are_rejected_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for skill_id, signal, reason in (
                ("../verification_policy", "missing_rule", "unsafe_observation_fields"),
                ("verification_policy", "contains private prose", "unknown_feedback_signal"),
                (
                    "verification_policy",
                    "worker_self_reported_counts_unverified",
                    "unknown_feedback_signal",
                ),
                ("VerificationPolicy", "missing_rule", "unsafe_observation_fields"),
            ):
                with self.subTest(skill_id=skill_id, signal=signal):
                    rejected = record_observation(
                        root,
                        occurrence_id="run-one",
                        skill_id=skill_id,
                        signal=signal,
                    )
                    self.assertFalse(rejected["created"])
                    self.assertEqual(reason, rejected["reason"])

            self.assertEqual([], list(root.rglob("*.json")))

    def test_unsafe_review_fields_and_missing_candidates_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_id = self._ready_candidate(root, signal="missing_rule")

            unsafe = review_candidate(
                root,
                candidate_id,
                decision="stage_patch",
                gap_type="../private-gap",
                change_type="guidance_patch",
                promotion_target="verification_policy",
            )
            self.assertFalse(unsafe["updated"])
            self.assertEqual("unsafe_review_fields", unsafe["reason"])

            missing_review = review_candidate(
                root,
                "0" * 16,
                decision="no_change",
            )
            self.assertFalse(missing_review["updated"])
            self.assertEqual("candidate_not_found", missing_review["reason"])

            missing_completion = complete_verified_skill_maintenance(
                root,
                project=root,
                rules=root,
                candidate_id="0" * 16,
                outcome="applied",
                verification_kind="unittest",
                target="missing/SKILL.md",
                test_selector="tests.test_agent_skill_learning",
            )
            self.assertFalse(missing_completion["updated"])
            self.assertEqual("candidate_not_found", missing_completion["reason"])

    def test_curator_rejects_tampered_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for occurrence_id in ("run-one", "run-two"):
                record_observation(
                    root,
                    occurrence_id=occurrence_id,
                    skill_id="verification_policy",
                    signal="missing_rule",
                )
            for path in (root / "skill-learning" / "observations").glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["candidate_id"] = "0" * 16
                path.write_text(json.dumps(payload), encoding="utf-8")

            curated = curate_observations(root)

            self.assertEqual([], curated["queued"])
            self.assertEqual(0, curated["ready_count"])

    def test_review_outcome_findings_are_blocking(self) -> None:
        self.assertEqual([], review_outcome_failures("pass"))
        self.assertTrue(review_outcome_failures("findings"))

    def _ready_candidate(self, root: Path, *, signal: str) -> str:
        # One run may store only one observation, so each candidate needs its
        # own runs rather than sharing a fixed pair across signals.
        for index in ("one", "two"):
            record_observation(
                root,
                occurrence_id=f"run-{signal}-{index}",
                skill_id="verification_policy",
                signal=signal,
            )
        result = curate_observations(root, min_occurrences=2)
        self.assertEqual(1, result["ready_count"])
        return str(result["queued"][0])

    def _write_legacy_observation(
        self,
        root: Path,
        *,
        occurrence_id: str,
        skill_id: str,
        signal: str,
    ) -> Path:
        occurrence_key = opaque_key(occurrence_id)
        legacy_candidate = candidate_id(skill_id, signal)
        observation_id = opaque_key(f"{legacy_candidate}:{occurrence_key}")
        path = root / observation_dir() / f"{observation_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "observation_id": observation_id,
                    "candidate_id": legacy_candidate,
                    "skill_id": skill_id,
                    "signal": signal,
                    "occurrence_key": occurrence_key,
                    "status": "observed",
                    "created_at": "2026-07-30T00:00:00+00:00",
                    "privacy": "safe_slugs_and_opaque_ids_only",
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
