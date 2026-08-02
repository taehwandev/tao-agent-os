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
from agent_skill_learning import curate_observations, record_observation, review_candidate
from agent_skill_maintenance import complete_verified_skill_maintenance


class RetrospectiveSkillBindingTests(unittest.TestCase):
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
            record_gate_evidence(
                evidence_path=evidence,
                preflight=preflight,
                gate="retrospective check",
                evidence=(
                    "retrospective check; skills checked: retrospective-learning; "
                    "outcome: reusable_gap; observation: deferred"
                ),
                fields={
                    "skills_checked": "retrospective-learning",
                    "outcome": "reusable_gap",
                    "observation": "deferred",
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

            self.assertTrue(accepted["created"])
            self.assertEqual(1, accepted["curation"]["scanned"])
            self.assertEqual(0, accepted["curation"]["ready_count"])
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

    def test_recorded_gate_requires_current_matching_observation(self) -> None:
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
            args = SimpleNamespace(
                project=project,
                rules=rules,
                evidence=evidence,
            )
            fields = {
                "skills_checked": "retrospective-learning",
                "outcome": "reusable_gap",
                "observation": "recorded",
            }

            with patch("agent_hook_gate_records.state_home", return_value=state):
                with self.assertRaisesRegex(ValueError, "matching stored observation"):
                    record_hook_gate(
                        args,
                        "retrospective check",
                        "",
                        fields,
                        "test",
                    )
                record_observation(
                    state,
                    occurrence_id="opaque-runtime-run",
                    skill_id="retrospective_learning",
                    signal="weak_verification",
                )
                entry = record_hook_gate(
                    args,
                    "retrospective check",
                    "",
                    fields,
                    "test",
                )

            self.assertEqual("SUCCESS", entry["status"])

    def test_recorded_gate_rejects_noncanonical_persisted_signal(self) -> None:
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
            observation_path = next(
                (state / "skill-learning" / "observations").glob("*.json")
            )
            observation = json.loads(observation_path.read_text(encoding="utf-8"))
            observation["signal"] = " weak_verification "
            observation_path.write_text(json.dumps(observation), encoding="utf-8")
            args = SimpleNamespace(project=project, rules=rules, evidence=evidence)

            with patch("agent_hook_gate_records.state_home", return_value=state):
                with self.assertRaisesRegex(ValueError, "matching stored observation"):
                    record_hook_gate(
                        args,
                        "retrospective check",
                        "",
                        {
                            "skills_checked": "retrospective-learning",
                            "outcome": "reusable_gap",
                            "observation": "recorded",
                        },
                        "test",
                    )

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
