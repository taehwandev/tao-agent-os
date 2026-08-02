from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_skill_curator import curate_observations
from agent_skill_learning import record_observation, review_candidate


SPEC = importlib.util.spec_from_file_location(
    "agent_finish_skill_followup_under_test",
    SCRIPTS / "agent-finish-check.py",
)
assert SPEC and SPEC.loader
finish_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finish_check)


class AgentFinishSkillFollowupTests(unittest.TestCase):
    def test_current_threshold_candidate_blocks_clean_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            candidate = self._observe_twice(state)
            curate_observations(state)
            failures: list[str] = []
            signals: list[dict[str, str]] = []

            with patch.object(finish_check, "state_home", return_value=state):
                pending = finish_check.process_skill_followup(
                    preflight={"agent_run_id": "current-run"},
                    gate_signals=signals,
                    failures=failures,
                )

            expected = f"skill follow-up bounded review pending: candidate={candidate}"
            self.assertEqual([expected], pending)
            self.assertEqual([expected], failures)
            self.assertEqual("skill learning follow-up", signals[0]["gate"])
            self.assertEqual("FAIL", signals[0]["signal"])

    def test_no_change_terminal_outcome_allows_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            candidate = self._observe_twice(state)
            curate_observations(state)
            review_candidate(state, candidate, decision="no_change")
            failures: list[str] = []

            with patch.object(finish_check, "state_home", return_value=state):
                pending = finish_check.process_skill_followup(
                    preflight={"agent_run_id": "current-run"},
                    gate_signals=[],
                    failures=failures,
                )

            self.assertEqual([], pending)
            self.assertEqual([], failures)

    def test_unrelated_existing_failure_defers_skill_closeout_check(self) -> None:
        failures = ["missing required gate evidence: tests"]

        with patch.object(
            finish_check,
            "skill_followup_failures",
            side_effect=AssertionError("must not mask the first failed checkpoint"),
        ):
            pending = finish_check.process_skill_followup(
                preflight={"agent_run_id": "current-run"},
                gate_signals=[],
                failures=failures,
            )

        self.assertEqual([], pending)
        self.assertEqual(["missing required gate evidence: tests"], failures)

    def test_pending_closeout_has_distinct_finish_check_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            evidence = Path(directory) / "preflight.json"
            preflight = {"route": {"command": "task", "gates": []}}
            evidence.write_text(json.dumps(preflight), encoding="utf-8")
            code = finish_check._report_finish_failures(
                failures=["skill follow-up bounded review pending: candidate=0123456789abcdef"],
                gate_policy_failures=[],
                required_gates=[],
                missed_gates=[],
                gate_evidence={},
                evidence_path=evidence,
                preflight=preflight,
                pending_closeout=True,
            )

        self.assertEqual(3, code)

    def test_finish_main_refuses_current_threshold_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            preflight = {
                "agent_run_id": "current-run",
                "route": {"command": "task", "gates": []},
            }
            evidence.write_text(json.dumps(preflight), encoding="utf-8")
            state = root / "state"
            candidate = self._observe_twice(state)
            curate_observations(state)
            args = SimpleNamespace(
                project=project,
                rules=project,
                evidence=evidence,
                output=project / ".tao" / "finish.json",
                allow_vibeguard_review=None,
            )
            stderr = io.StringIO()

            parser = SimpleNamespace(parse_args=lambda: args)
            with (
                patch.object(finish_check, "build_parser", return_value=parser),
                patch.object(
                    finish_check,
                    "resolve_paths",
                    return_value=(project, project, evidence, args.output),
                ),
                patch.object(finish_check, "read_preflight", return_value=preflight),
                patch.object(finish_check, "read_delegation_plan", return_value={}),
                patch.object(
                    finish_check,
                    "_validated_gate_evidence",
                    return_value=({}, {}),
                ),
                patch.object(
                    finish_check,
                    "check_required_gates",
                    return_value=([], [], []),
                ),
                patch.object(
                    finish_check,
                    "route_gate_capsule_binding_failures",
                    return_value=[],
                ),
                patch.object(finish_check, "check_request_intake", return_value=False),
                patch.object(finish_check, "check_preflight_vibeguard"),
                patch.object(finish_check, "check_read_only_execution"),
                patch.object(
                    finish_check,
                    "run_final_checks",
                    return_value=({}, {}, {"overall": "Ready"}, "Ready"),
                ),
                patch.object(
                    finish_check,
                    "_revalidate_review_attestation_after_final_checks",
                ),
                patch.object(
                    finish_check,
                    "process_failure_learning",
                    return_value=(False, {}),
                ),
                patch.object(finish_check, "state_home", return_value=state),
                patch.object(finish_check, "canonical_skill_ids", return_value=set()),
                patch.object(finish_check, "write_json"),
                patch.object(finish_check, "print_result"),
                redirect_stderr(stderr),
            ):
                code = finish_check.main()

            self.assertEqual(3, code)
            self.assertIn(candidate, stderr.getvalue())

    def _observe_twice(self, state: Path) -> str:
        first = record_observation(
            state,
            occurrence_id="prior-run",
            skill_id="request_triage",
            signal="ambiguous_decision",
        )
        second = record_observation(
            state,
            occurrence_id="current-run",
            skill_id="request_triage",
            signal="ambiguous_decision",
        )
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        return str(second["candidate_id"])


if __name__ == "__main__":
    unittest.main()
