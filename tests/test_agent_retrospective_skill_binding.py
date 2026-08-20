from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_gate_evidence import record_gate_evidence, reset_gate_evidence_ledger
from agent_hook_gate_records import record_hook_gate
from agent_skill_feedback import record_skill_feedback
from agent_skill_hooks import skill_feedback_hook
from agent_skill_draft import record_draft
from agent_skill_learning import curate_observations, record_observation, review_candidate
from agent_skill_maintenance import complete_verified_skill_maintenance


class RetrospectiveSkillBindingTests(unittest.TestCase):
    def test_no_change_feedback_directs_callers_to_the_required_gate(self) -> None:
        result, details = record_skill_feedback(
            project=ROOT,
            rules=ROOT,
            evidence_path=ROOT / "missing-preflight.json",
            outcome="no_change",
            skill_id="retrospective-learning",
            signal="",
        )

        self.assertEqual("retrospective_gate_required", result["reason"])
        self.assertTrue(any("retrospective check gate" in detail for detail in details))

    def test_no_change_feedback_hook_fails_as_an_invocation_error(self) -> None:
        args = SimpleNamespace(
            project=ROOT,
            rules=ROOT,
            evidence=ROOT / "missing-preflight.json",
            skill_feedback_outcome="no_change",
            skill_id="retrospective-learning",
            feedback_signal="",
            feedback_gap="",
            output=None,
        )
        with patch("agent_skill_hooks.finish_with_result", return_value=1) as finish:
            exit_code = skill_feedback_hook(args)

        self.assertEqual(1, exit_code)
        self.assertFalse(finish.call_args.args[1])
        self.assertTrue(finish.call_args.kwargs["invocation_error"])

    def test_retrospective_rejects_unknown_canonical_skill(self) -> None:
        evidence = (
            "retrospective check; skills checked: made-up-skill; "
            "outcome: no_reusable_gap; observation: not_needed"
        )
        failures = validate_retrospective_check(
            evidence,
            allowed_skill_ids={"retrospective_learning"},
        )
        self.assertTrue(any("unknown canonical skills" in item for item in failures))

    def test_feedback_requires_current_bound_retrospective(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            rules = root / "rules"
            state = root / "state"
            evidence = project / ".tao" / "runs" / "one" / "preflight.json"
            skill = rules / "workflows" / "skills" / "retrospective-learning" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("canonical\n", encoding="utf-8")
            evidence.parent.mkdir(parents=True)
            preflight = {
                "agent_run_id": "opaque-runtime-run",
                "route": {"command": "task", "gates": ["retrospective check"]},
            }
            evidence.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence, preflight)
            record_observation(
                state,
                occurrence_id="opaque-runtime-run",
                skill_id="retrospective_learning",
                signal="weak_verification",
            )
            record_gate_evidence(
                evidence_path=evidence,
                preflight=preflight,
                gate="retrospective check",
                evidence=(
                    "retrospective check; skills checked: retrospective-learning; "
                    "outcome: reusable_gap; observation: recorded"
                ),
                fields={
                    "skills_checked": "retrospective-learning",
                    "outcome": "reusable_gap",
                    "observation": "recorded",
                },
                status="SUCCESS",
                source="test",
            )

            with patch("agent_skill_feedback.state_home", return_value=state):
                accepted, _ = record_skill_feedback(
                    project=project,
                    rules=rules,
                    evidence_path=evidence,
                    outcome="observed",
                    skill_id="retrospective-learning",
                    signal="weak_verification",
                )
                rejected, _ = record_skill_feedback(
                    project=project,
                    rules=rules,
                    evidence_path=evidence,
                    outcome="observed",
                    skill_id="unrelated-skill",
                    signal="weak_verification",
                )
                unstable, _ = record_skill_feedback(
                    project=project,
                    rules=rules,
                    evidence_path=evidence,
                    outcome="observed",
                    skill_id="retrospective-learning",
                    signal="missing_binding_rule",
                )

            self.assertFalse(accepted["created"])
            self.assertTrue(accepted["idempotent"])
            self.assertEqual(1, accepted["curation"]["scanned"])
            self.assertEqual(1, accepted["curation"]["ready_count"])
            self.assertEqual("unknown_canonical_skill", rejected["reason"])
            self.assertEqual("unknown_feedback_signal", unstable["reason"])

    def test_second_bound_observation_is_curated_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            record_observation(
                state,
                occurrence_id="first-run",
                skill_id="retrospective_learning",
                signal="weak_verification",
            )

            with (
                patch("agent_skill_feedback.state_home", return_value=state),
                patch(
                    "agent_skill_feedback.canonical_skill_ids",
                    return_value={"retrospective_learning"},
                ),
                patch(
                    "agent_skill_feedback._retrospective_fields",
                    return_value={
                        "skills_checked": "retrospective-learning",
                        "outcome": "reusable_gap",
                        "observation": "recorded",
                    },
                ),
                patch("agent_skill_feedback._occurrence_id", return_value="second-run"),
            ):
                result, details = record_skill_feedback(
                    project=root,
                    rules=root,
                    evidence_path=root / ".tao" / "preflight.json",
                    outcome="observed",
                    skill_id="retrospective-learning",
                    signal="weak_verification",
                )

            candidate = result["candidate_id"]
            self.assertEqual([candidate], result["curation"]["queued"])
            self.assertTrue(
                (state / "skill-learning" / "review-queue" / f"{candidate}.json").is_file()
            )
            self.assertTrue(any(candidate in detail for detail in details))

    def test_recorded_gate_no_longer_blocks_on_a_missing_observation(self) -> None:
        """The observation-exists check moved to finish so the gate is reachable.

        Enforcing it when the gate is recorded deadlocked every reusable gap: the
        gate needed a stored observation, and the observation writer needed the
        gate to already be recorded.
        """

        import inspect

        import agent_hook_gate_records as records

        source = inspect.getsource(records)
        self.assertNotIn("recorded_observation_failures(", source)
        self.assertNotIn("from agent_retrospective_observation import", source)

    def test_finish_still_refuses_a_reusable_gap_without_its_observation(self) -> None:
        """The guarantee is preserved, only relocated to the finish check."""

        import inspect

        from agent_retrospective_observation import recorded_observation_failures
        from agent_skill_followup import skill_followup_failures

        self.assertIn(
            "recorded_observation_failures(",
            inspect.getsource(skill_followup_failures),
        )
        with tempfile.TemporaryDirectory() as directory:
            failures = recorded_observation_failures(
                preflight={"agent_run_id": "opaque-runtime-run"},
                fields={
                    "skills_checked": "retrospective-learning",
                    "outcome": "reusable_gap",
                    "observation": "recorded",
                },
                state_root=Path(directory),
            )
        self.assertEqual(1, len(failures))
        self.assertIn("matching stored observation", failures[0])

    def test_persisted_noncanonical_signal_is_not_accepted_as_the_observation(self) -> None:
        """A legacy signal must not satisfy the current occurrence at finish."""

        from agent_retrospective_observation import recorded_observation_failures
        from agent_skill_state import candidate_id, opaque_key

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            occurrence = opaque_key("opaque-runtime-run")
            candidate = candidate_id("retrospective_learning", "stale_cache_path_ids")
            path = state / "skill-learning" / "observations" / f"{candidate}.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_id": candidate,
                        "candidate_id": candidate,
                        "skill_id": "retrospective_learning",
                        "signal": "stale_cache_path_ids",
                        "occurrence_key": occurrence,
                        "status": "observed",
                        "privacy": "safe_slugs_and_opaque_ids_only",
                    }
                ),
                encoding="utf-8",
            )
            failures = recorded_observation_failures(
                preflight={"agent_run_id": "opaque-runtime-run"},
                fields={
                    "skills_checked": "retrospective-learning",
                    "outcome": "reusable_gap",
                    "observation": "recorded",
                },
                state_root=state,
            )
        self.assertEqual(1, len(failures))
        self.assertIn("matching stored observation", failures[0])

    def test_project_local_skill_maintenance_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            project = root / "project"
            rules = root / "rules"
            rules.mkdir()
            bundle = project / ".agents" / "shared" / "llm-skills" / "local-skill"
            bundle.mkdir(parents=True)
            (bundle / "SKILL.md").write_text("canonical\n", encoding="utf-8")
            target = bundle / "helper.py"
            target.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "add", "-A"], cwd=project, check=True)
            target.write_text("value = 2\n", encoding="utf-8")
            candidate = self._stage_candidate(state)

            result = complete_verified_skill_maintenance(
                state,
                project=project,
                rules=rules,
                candidate_id=candidate,
                outcome="applied",
                verification_kind="py_compile",
                target=".agents/shared/llm-skills/local-skill/helper.py",
            )

            self.assertTrue(result["updated"])

    def test_project_adapter_skill_is_not_a_maintenance_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            project = root / "project"
            rules = root / "rules"
            rules.mkdir()
            bundle = project / ".codex" / "skills" / "local-skill"
            bundle.mkdir(parents=True)
            (bundle / "SKILL.md").write_text("adapter\n", encoding="utf-8")
            target = bundle / "helper.py"
            target.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            candidate = self._stage_candidate(state)

            result = complete_verified_skill_maintenance(
                state,
                project=project,
                rules=rules,
                candidate_id=candidate,
                outcome="applied",
                verification_kind="py_compile",
                target=".codex/skills/local-skill/helper.py",
            )

            self.assertFalse(result["updated"])
            self.assertEqual("maintenance_target_mismatch", result["reason"])

    @staticmethod
    def _stage_candidate(state: Path) -> str:
        for occurrence in ("one", "two"):
            record_observation(
                state,
                occurrence_id=f"local_skill_{occurrence}",
                skill_id="local_skill",
                signal="missing_rule",
            )
        queued = curate_observations(state)["queued"]
        candidate = queued[0]
        bundle = state / "common" / "skills" / "local-skill"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "SKILL.md").write_text("test skill\n", encoding="utf-8")
        record_draft(
            state,
            project=state,
            rules=state,
            skill_id="local_skill",
            signal="missing_rule",
            proposal="A bounded test proposal describes the missing rule and its verification path.",
            occurrence_id="draft-local-skill",
        )
        review_candidate(
            state,
            candidate,
            decision="stage_patch",
            gap_type="missing_rule",
            change_type="guidance_patch",
            promotion_target="local_skill",
        )
        return candidate


if __name__ == "__main__":
    unittest.main()
