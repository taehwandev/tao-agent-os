from __future__ import annotations

import json
import io
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_common import requires_retrospective
from agent_finish_gate_policy import (
    PLATFORM_SELECTION_GATE,
    PRD_DRAFT_GATE,
    REVIEW_READINESS_GATE,
    VALIDATED_GATES,
    validate_gate_evidence,
)
from agent_finish_check_steps import (
    check_request_intake,
    check_required_gates,
    validate_grill_me_skill_evidence,
)
from agent_gate_evidence import (
    gate_evidence_path_for_preflight,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    record_many_gate_evidence,
    reset_gate_evidence_ledger,
    synthesize_gate_evidence,
)
from agent_worker_evidence import worker_reservation_matches
from agent_delegation_plan import validate_delegation_plan_evidence
from agent_global_lessons import (
    lesson_summary,
    retrospective_candidate,
    write_retrospective_candidate,
)
from agent_lesson_store import upsert_retrospective_candidate
from agent_hook_runtime import hook_failure_policy, repair_context_failures
import agent_skill_hooks
from agent_preflight_runtime import (
    AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES as PREFLIGHT_AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES,
    _claude_spill_warnings,
)
from agent_review_hook import (
    record_review_failure,
    record_review_gate,
    record_review_prerequisite_readiness,
    review_hook,
    review_success_details,
    review_vibeguard_command,
    vibeguard_review_failure,
    workflow_validate_failure_detail,
)
from agent_review_structure import structure_review
from agent_vibeguard_cache import cached_vibeguard
from support.agy_setup import AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES, _agy_runtime_bridge_block
from support.claude_setup import _merge_claude_user_prompt_submit
from support.permission_entries import agy_permission_entries, claude_permission_entries, codex_prefix_rule_entries
from support.runtime_bridge import (
    CODEX_DISPATCH_BRIDGE_PHRASE,
    RUNTIME_BRIDGE_GRAPH_PHRASES,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.stable_launcher import stable_launcher_path
from workflow_catalog import COMMANDS, CONCERNS, SPILL_ACTION_LABELS
from workflow_gate_policy import (
    AGENTIC_RUN_STATE_GATE,
    AMBIGUITY_GATE,
    ALIGNMENT_BRIEF_GATE,
    BOUNDARY_PLAN_GATE,
    CYCLE_CONTRACT_GATE,
    DOCUMENTATION_IMPACT_GATE,
    DOCUMENTATION_GATE,
    MULTI_AGENT_GATE,
    PRODUCT_REENTRY_GATE,
    PRODUCT_REENTRY_COMMANDS,
    SKILL_FEEDBACK_HOOK,
    SIDE_EFFECT_AUDIT_GATE,
    SOURCE_DOCS_GATE,
    SOURCE_DOCS_COMMANDS,
    TEST_GATE,
    ALIGNMENT_BRIEF_COMMANDS,
    WORK_PRODUCING_COMMANDS,
)
from workflow_request import infer_concerns_from_request
from workflow_request import classify_request
from workflow_request import classified_route_block_reason
from workflow_request import route_block_reason
from workflow_dispatch import (
    build_dispatch_manifest,
    execute_dispatch_manifest,
    print_dispatch_manifest,
)
from workflow_dispatch_profiles import profile_for_work_kind, select_work_kind
from workflow_doc_surfaces import (
    extract_request_surface_paths,
    git_status_surface_paths,
    infer_surface_docs,
    load_doc_surface_rules,
    surface_rule_doc_refs,
)
from workflow_doc_graph import (
    clear_doc_graph_cache,
    expand_doc_matches,
    graph_required_docs,
)
from workflow_parallel_validate import validate_parallel_execution_plan
from workflow_route import resolve_docs, route_hooks
from workflow_search import SearchOutcome, search_docs, search_docs_outcome
from workflow_skill_paths import canonical_doc_path
from workflow_spill import spill_tool_label, validate_spill_label_contracts
from workflow import build_parser, print_dispatch
from workflow_validate import (
    STRICT_CARD_REQUIRED_HEADINGS,
    markdown_files_to_validate,
    removed_cli_option_failures,
)


_PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "agent_preflight_under_test", ROOT / "scripts" / "agent-preflight.py"
)
assert _PREFLIGHT_SPEC and _PREFLIGHT_SPEC.loader
agent_preflight = importlib.util.module_from_spec(_PREFLIGHT_SPEC)
_PREFLIGHT_SPEC.loader.exec_module(agent_preflight)

_FINISH_CHECK_SPEC = importlib.util.spec_from_file_location(
    "agent_finish_check_under_test", ROOT / "scripts" / "agent-finish-check.py"
)
assert _FINISH_CHECK_SPEC and _FINISH_CHECK_SPEC.loader
agent_finish_check = importlib.util.module_from_spec(_FINISH_CHECK_SPEC)
_FINISH_CHECK_SPEC.loader.exec_module(agent_finish_check)

_AGENT_HOOK_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_under_test", ROOT / "scripts" / "agent-hook.py"
)
assert _AGENT_HOOK_SPEC and _AGENT_HOOK_SPEC.loader
agent_hook = importlib.util.module_from_spec(_AGENT_HOOK_SPEC)
_AGENT_HOOK_SPEC.loader.exec_module(agent_hook)


def route_doc(path: str) -> str:
    return canonical_doc_path(path)


class ReviewHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_review_hook_rejects_missing_pre_review_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "command": "task",
                    "gates": [
                        "request intake",
                        "orient",
                        "source docs",
                        "review hook",
                        "retrospective check",
                    ],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate="request intake",
                evidence="request provided to preflight",
            )
            args = SimpleNamespace(project=project, evidence=evidence_path)
            checks: dict[str, object] = {}
            failures: list[str] = []

            record_review_prerequisite_readiness(args, checks, failures)

            self.assertEqual(["orient", "source docs"], checks["review_prerequisite_missing"])
            self.assertTrue(
                any(
                    "review prerequisites are incomplete before review hook: orient, source docs"
                    in failure
                    for failure in failures
                )
            )
            self.assertFalse(any("retrospective check" in failure for failure in failures))

    def test_review_hook_rejects_rules_root_that_differs_from_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            expected_rules = project / "runtime"
            actual_rules = project / "runtime" / ".agents" / "rules"
            actual_rules.mkdir(parents=True)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "rules": str(expected_rules),
                "route": {
                    "command": "review",
                    "gates": ["source docs", "review hook"],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            args = SimpleNamespace(
                project=project,
                evidence=evidence_path,
                rules=actual_rules,
            )
            checks: dict[str, object] = {}
            failures: list[str] = []

            record_review_prerequisite_readiness(args, checks, failures)

            self.assertEqual(
                {
                    "expected": str(expected_rules),
                    "actual": str(actual_rules),
                },
                checks["review_rules_root"],
            )
            self.assertEqual(
                [
                    "review --rules must match the rules root recorded by start; "
                    "rerun review with the preflight rules root"
                ],
                failures,
            )

    def test_review_hook_treats_missing_prerequisites_as_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "command": "review",
                    "gates": ["source docs", "review hook", "retrospective check"],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            args = SimpleNamespace(
                project=project,
                evidence=evidence_path,
                output=None,
                repair_cycle=0,
            )
            result_payload: dict[str, object] = {}
            invocation_rollbacks = 0

            def rollback_repair_attempt() -> None:
                nonlocal invocation_rollbacks
                invocation_rollbacks += 1

            def unexpected_command(*_args: object, **_kwargs: object) -> object:
                self.fail("review checks must not run before prerequisites are complete")

            def finish_with_result(
                name: str,
                success: bool,
                details: list[str],
                output: Path | None,
                payload: dict[str, object],
                repair_cycle: int,
                invocation_error: bool = False,
            ) -> int:
                result_payload.update(
                    name=name,
                    success=success,
                    details=details,
                    invocation_error=invocation_error,
                )
                return 0 if success else 1

            with patch("agent_review_hook.record_review_failure") as record_failure:
                result = review_hook(
                    args,
                    unexpected_command,
                    unexpected_command,
                    unexpected_command,
                    unexpected_command,
                    finish_with_result,
                    rollback_repair_attempt,
                )

            self.assertEqual(1, result)
            self.assertFalse(result_payload["success"])
            self.assertTrue(result_payload["invocation_error"])
            self.assertTrue(
                any(
                    "review did not start" in detail
                    for detail in result_payload["details"]
                )
            )
            self.assertEqual(1, invocation_rollbacks)
            record_failure.assert_not_called()

    def test_review_hook_accepts_complete_pre_review_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "command": "task",
                    "gates": ["request intake", "orient", "act", "review hook", "report"],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            for gate in ("request intake", "orient", "act"):
                record_gate_evidence(
                    evidence_path=evidence_path,
                    preflight=preflight,
                    gate=gate,
                    evidence=f"{gate} completed",
                )
            args = SimpleNamespace(project=project, evidence=evidence_path)
            checks: dict[str, object] = {}
            failures: list[str] = []

            record_review_prerequisite_readiness(args, checks, failures)

            self.assertEqual([], checks["review_prerequisite_missing"])
            self.assertEqual([], failures)

    def test_review_hook_ignores_failed_post_review_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "command": "review",
                    "gates": [
                        "source docs",
                        "review hook",
                        "retrospective check",
                        "commit readiness",
                    ],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate="source docs",
                evidence="required docs were read",
                fields={
                    "required_docs": "AGENTS.md",
                    "source": "project instructions",
                    "takeaway": "apply the project workflow",
                },
            )
            for gate in ("retrospective check", "commit readiness"):
                record_gate_evidence(
                    evidence_path=evidence_path,
                    preflight=preflight,
                    gate=gate,
                    evidence=f"{gate} failed before repair",
                    status="FAIL",
                )
            args = SimpleNamespace(project=project, evidence=evidence_path)
            checks: dict[str, object] = {}
            failures: list[str] = []

            record_review_prerequisite_readiness(args, checks, failures)

            self.assertEqual(["source docs"], checks["review_prerequisite_gates"])
            self.assertEqual([], checks["review_prerequisite_missing"])
            self.assertEqual([], failures)

    def test_failed_review_invalidates_an_earlier_successful_review_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "command": "review",
                    "gates": ["review hook"],
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate="review hook",
                evidence="earlier review hook completed successfully",
                status="SUCCESS",
                source="review",
            )

            record_review_failure(
                SimpleNamespace(project=project, evidence=evidence_path),
                ["review outcome reports unresolved findings"],
            )
            evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=preflight["route"],
                evidence_path=evidence_path,
            )

            self.assertNotIn("review hook", evidence)
            self.assertIn("review hook", diagnostics["failed_gates"])
            self.assertEqual(
                "review",
                diagnostics["failed_gates"]["review hook"]["source"],
            )

    def test_review_hook_detects_mutation_outside_pathspec(self) -> None:
        full_statuses = [
            " M outside.py\n",
            " M outside.py\n M outside2.py\n",
        ]
        outputs: list[dict[str, object]] = []

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            stdout = full_statuses.pop(0)
            result = {
                "command": ["git", "status", "--short", "--untracked-files=all"],
                "cwd": str(ROOT),
                "returncode": 0,
                "stdout": stdout,
                "stderr": "",
            }
            return result, [line for line in stdout.splitlines() if line.strip()]

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            if command[:3] == ["git", "status", "--short"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "abc\n", "stderr": ""}
            if command[:2] == ["git", "diff"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command[:2] == ["git", "ls-files"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command == ["vibeguard", "--help"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command[:3] == ["vibeguard", "audit", "."]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "Overall: Ready\n", "stderr": ""}
            return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            outputs.append({"name": name, "success": success, "details": details, "payload": payload})
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            rules=ROOT,
            evidence=None,
            review_outcome="pass",
            code_review_evidence="reviewed scoped change",
            docs_freshness_evidence="docs unchanged because no durable docs impact",
            structure_review_evidence="",
            boundary_plan_evidence="",
            side_effect_audit_evidence="side-effect audit checked diff; no unexpected changes",
            review_scope="pathspec",
            review_path=["scripts/agent-hook.py"],
            max_changed_paths=25,
            max_source_file_lines=500,
            max_function_lines=120,
            output=None,
            repair_cycle=0,
        )

        with (
            patch("agent_review_hook.record_review_failure"),
            patch("agent_review_hook.record_review_prerequisite_readiness"),
        ):
            result = review_hook(
                args,
                run_command,
                git_status,
                lambda _project, _rules: ["vibeguard", "audit", "."],
                lambda output: "Ready" if "Ready" in output else "unknown",
                finish_with_result,
            )

        self.assertEqual(1, result)
        self.assertFalse(outputs[0]["success"])
        self.assertTrue(
            any("outside the review pathspec" in detail for detail in outputs[0]["details"])
        )

    def test_review_hook_tolerates_omitted_structure_review_evidence(self) -> None:
        outputs: list[dict[str, object]] = []

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            result = {
                "command": ["git", "status", "--short", "--untracked-files=all"],
                "cwd": str(ROOT),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            }
            return result, []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            if command[:3] == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "Overall: Ready\n",
                    "stderr": "",
                }
            return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            outputs.append({"name": name, "success": success, "details": details})
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            rules=ROOT,
            evidence=None,
            review_outcome="pass",
            code_review_evidence="reviewed scoped change",
            docs_freshness_evidence="docs unchanged because no durable docs impact",
            structure_review_evidence=None,
            boundary_plan_evidence=None,
            side_effect_audit_evidence="side-effect audit checked diff",
            review_scope="pathspec",
            review_path=["scripts/agent-hook.py"],
            max_changed_paths=25,
            max_source_file_lines=500,
            max_function_lines=120,
            output=None,
            repair_cycle=0,
        )

        # Omitting the optional evidence flags must surface a normal gate result,
        # not crash the hook before it can report anything.
        with (
            patch("agent_review_hook.record_review_failure"),
            patch("agent_review_hook.record_review_gate"),
            patch("agent_review_hook.record_review_prerequisite_readiness"),
        ):
            review_hook(
                args,
                run_command,
                git_status,
                lambda _project, _rules: ["vibeguard", "audit", "."],
                lambda output: "Ready" if "Ready" in output else "unknown",
                finish_with_result,
            )

        self.assertTrue(outputs)

    def test_review_hook_does_not_merge_boundary_plan_into_structure_evidence(self) -> None:
        outputs: list[dict[str, object]] = []

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            result = {
                "command": ["git", "status", "--short", "--untracked-files=all"],
                "cwd": str(ROOT),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            }
            return result, []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            return {
                "command": command,
                "cwd": str(cwd),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            }

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            outputs.append(
                {
                    "name": name,
                    "success": success,
                    "details": details,
                    "payload": payload,
                }
            )
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            rules=ROOT,
            evidence=None,
            review_outcome="pass",
            code_review_evidence="reviewed scoped change",
            docs_freshness_evidence="reviewed affected workflow guidance",
            structure_review_evidence="",
            boundary_plan_evidence=(
                "owner: domain; allowed imports: contracts; forbidden imports: ui; "
                "callers/tests: app and domain tests; verification: focused tests"
            ),
            side_effect_audit_evidence="side-effect audit checked diff",
            review_scope="working-tree",
            review_path=[],
            max_changed_paths=25,
            max_source_file_lines=500,
            max_function_lines=120,
            output=None,
            repair_cycle=0,
        )
        structure = {
            "failures": [],
            "warnings": [],
            "boundary_note_requirements": [
                {"package": "src/domain", "reason": "existing multi-role package"},
            ],
            "checked_path_count": 1,
            "checked_paths": ["src/domain/owner.py"],
            "scope": "working tree",
            "max_added_lines": 300,
        }

        def record_workflow_validate(
            _args: object, checks: dict[str, object], _failures: list[str]
        ) -> None:
            checks["workflow_validate"] = {"returncode": 0}

        # The success path is stubbed as well, so a regression that merges the
        # boundary field into the structure field fails on this test's own
        # assertions rather than on a KeyError from evidence the patched
        # helpers never recorded.
        with (
            patch("agent_review_hook.record_review_failure"),
            patch("agent_review_hook.record_review_prerequisite_readiness"),
            patch(
                "agent_review_hook.record_review_workflow_validation",
                side_effect=record_workflow_validate,
            ),
            patch("agent_review_hook.record_review_vibeguard"),
            patch("agent_review_hook.record_successful_review_workflow_validation"),
            patch("agent_review_hook.record_review_gate"),
            patch("agent_review_hook.structure_review", return_value=structure),
        ):
            result = review_hook(
                args,
                run_command,
                git_status,
                lambda _project, _rules: ["vibeguard", "audit", "."],
                lambda _output: "Ready",
                finish_with_result,
            )

        self.assertEqual(1, result)
        self.assertFalse(outputs[0]["success"])
        self.assertEqual("", outputs[0]["payload"]["structure_review_evidence"])
        self.assertIn("owner: domain", outputs[0]["payload"]["boundary_plan_evidence"])
        self.assertTrue(
            any(
                "structure-review-evidence must explicitly include owner"
                in detail
                for detail in outputs[0]["details"]
            )
        )

    def test_review_failure_records_resumable_checkpoint(self) -> None:
        from agent_repair_ledger import checkpoint_has_recorded_failure
        from agent_review_hook import record_review_failure

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {"route": {"command": "review", "gates": ["review hook"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            args = SimpleNamespace(project=project, evidence=evidence_path)

            record_review_failure(args, ["structure review failed"])

            self.assertTrue(
                checkpoint_has_recorded_failure(
                    route=preflight["route"],
                    evidence_path=evidence_path,
                    checkpoint="review",
                )
            )

    def test_review_success_cannot_skip_an_unreadable_attestation_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            missing_evidence = project / ".tao" / "missing-preflight.json"
            args = SimpleNamespace(
                project=project,
                rules=project,
                evidence=missing_evidence,
            )

            with self.assertRaisesRegex(
                ValueError,
                "requires readable preflight evidence",
            ):
                record_review_gate(args, {})

    def test_review_hook_preserves_workflow_validate_diagnostic(self) -> None:
        detail = workflow_validate_failure_detail({
            "returncode": 1,
            "stdout": "",
            "stderr": "Invalid markdown frontmatter:\n- path.md: missing status\n",
        })

        self.assertEqual(
            "workflow validate failed: Invalid markdown frontmatter:; - path.md: missing status",
            detail,
        )

    def test_review_vibeguard_command_uses_pathspec_when_supported(self) -> None:
        calls: list[list[str]] = []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            return {
                "command": command,
                "cwd": str(cwd),
                "returncode": 0,
                "stdout": "usage: vibeguard audit [project] [--path <path>]\n",
                "stderr": "",
            }

        command = review_vibeguard_command(
            ROOT,
            ROOT,
            run_command,
            lambda _project, _rules: ["vibeguard", "audit", ".", "--rules", "."],
            ["scripts/agent_review_hook.py"],
        )

        self.assertEqual(["vibeguard", "--help"], calls[0])
        self.assertEqual(
            [
                "vibeguard",
                "audit",
                ".",
                "--rules",
                ".",
                "--changed-only",
                "--path",
                "scripts/agent_review_hook.py",
            ],
            command(ROOT, ROOT),
        )

    def test_review_vibeguard_command_falls_back_to_changed_only_without_path_support(self) -> None:
        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            return {
                "command": command,
                "cwd": str(cwd),
                "returncode": 0,
                "stdout": "usage: vibeguard audit [project] [--changed-only]\n",
                "stderr": "",
            }

        command = review_vibeguard_command(
            ROOT,
            ROOT,
            run_command,
            lambda _project, _rules: ["vibeguard", "audit", ".", "--rules", "."],
            ["scripts/agent_review_hook.py"],
        )

        self.assertEqual(
            [
                "vibeguard",
                "audit",
                ".",
                "--rules",
                ".",
                "--changed-only",
            ],
            command(ROOT, ROOT),
        )

    def test_vibeguard_review_accepts_explicit_review_reason(self) -> None:
        self.assertEqual(
            "",
            vibeguard_review_failure(
                "Needs review",
                ROOT,
                "Guardrail refresh requires explicit user approval; blocking gates are ready.",
            ),
        )
        self.assertEqual(
            "VibeGuard overall is Needs review",
            vibeguard_review_failure("Needs review", ROOT, ""),
        )

    def test_structure_review_warns_for_preexisting_oversized_block_without_growth(self) -> None:
        base_lines = ["def run_import():"]
        base_lines.extend(f"    value_{index} = {index}" for index in range(125))
        base_text = "\n".join(base_lines) + "\n"
        changed_text = base_text.replace("value_50 = 50", "value_50 = 51")

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "large.py"
            source.write_text(changed_text, encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "M\tlarge.py\n"
                elif command[:3] == ["git", "diff", "--numstat"]:
                    stdout = "1\t1\tlarge.py\n"
                elif command[:2] == ["git", "ls-files"]:
                    stdout = ""
                elif command[:2] == ["git", "show"]:
                    stdout = base_text
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            result = structure_review(project, 500, 120, run_command)

        self.assertFalse(any("large.py:1 block `run_import` spans" in failure for failure in result["failures"]))
        self.assertTrue(any("pre-existing oversized unit" in warning for warning in result["warnings"]))

    def test_review_hook_command_requests_code_work_evidence(self) -> None:
        route = resolve_docs("feature", None, ["testing"], request_classified=True)
        review_hook = next(hook for hook in route["hooks"] if hook["hook"] == "review")

        self.assertEqual(
            [
                "start",
                "review",
                "skill-feedback",
                "skill-draft",
                "skill-curate",
                "skill-review",
                "skill-maintenance",
                "finish",
            ],
            [hook["hook"] for hook in route["hooks"]],
        )
        self.assertIn("--review-scope working-tree", review_hook["command"])
        self.assertIn("--review-outcome <pass|findings>", review_hook["command"])
        self.assertIn("[--review-path <task-owned-path>]", review_hook["command"])
        self.assertIn("--allow-vibeguard-review", review_hook["command"])
        self.assertIn("--boundary-plan-evidence", review_hook["command"])
        self.assertIn("--side-effect-audit-evidence", review_hook["command"])

    def test_commit_review_hook_command_is_lightweight(self) -> None:
        route = resolve_docs("git_commit", None, [], request_classified=True)
        review_hook = next(hook for hook in route["hooks"] if hook["hook"] == "review")

        self.assertTrue(review_hook["required"])
        self.assertIn("--review-scope working-tree", review_hook["command"])
        self.assertIn("[--review-path <commit-owned-path>]", review_hook["command"])
        self.assertIn("--code-review-evidence", review_hook["command"])
        self.assertIn("--review-outcome <pass|findings>", review_hook["command"])
        self.assertIn("--docs-freshness-evidence", review_hook["command"])
        self.assertIn("--allow-vibeguard-review", review_hook["command"])
        self.assertNotIn("--boundary-plan-evidence", review_hook["command"])
        self.assertNotIn("--side-effect-audit-evidence", review_hook["command"])

        finish_hook = next(hook for hook in route["hooks"] if hook["hook"] == "finish")
        self.assertNotIn("--gate", finish_hook["command"])

    def test_review_success_requires_finish_before_commit(self) -> None:
        details = review_success_details(
            {"checked_path_count": 1, "scope": "working-tree"},
            "working-tree",
        )

        self.assertTrue(
            any(
                "run finish before commit, push, release, or handoff" in detail
                and "invalidates this review attestation" in detail
                for detail in details
            )
        )


class RaisedAdditionLimitEvidenceTests(unittest.TestCase):
    """A raised per-file addition limit must be justified, not silent."""

    def test_default_limit_needs_no_addition_justification(self) -> None:
        from agent_review_hook import raised_addition_limit_failures
        from agent_review_structure import REVIEW_ADDED_LINE_LIMIT

        structure = {"max_added_lines": REVIEW_ADDED_LINE_LIMIT}

        self.assertEqual([], raised_addition_limit_failures(structure, ""))

    def test_raised_limit_without_a_reason_fails(self) -> None:
        from agent_review_hook import raised_addition_limit_failures

        failures = raised_addition_limit_failures(
            {"max_added_lines": 600}, "owner=domain; verification=focused tests"
        )

        self.assertEqual(1, len(failures))
        self.assertIn("per-file addition limit was raised to 600", failures[0])

    def test_raised_limit_with_a_single_file_artifact_reason_passes(self) -> None:
        from agent_review_hook import raised_addition_limit_failures

        failures = raised_addition_limit_failures(
            {"max_added_lines": 600},
            "adapters/codex/spill-importer.mjs is installed as a single standalone artifact and cannot be split",
        )

        self.assertEqual([], failures)


class StructuralLimitRepairHintTests(unittest.TestCase):
    def test_structural_size_failure_explains_standalone_override_flags(self) -> None:
        from agent_review_hook import review_failure_details

        details = review_failure_details(
            ["structure review: scripts/tool.py has 600 lines; new-file hard limit is 500"],
            {"checked_paths": ["scripts/tool.py"], "checked_path_count": 1, "scope": "test"},
            "commit range",
        )

        hint = next(detail for detail in details if detail.startswith("structure repair hint:"))
        self.assertIn("--max-source-file-lines", hint)
        self.assertIn("--max-function-lines", hint)
        self.assertIn("--max-added-lines", hint)
        self.assertIn("--structure-review-evidence", hint)


class ContentLossIsReviewableTests(unittest.TestCase):
    """A large removal must be accounted for whatever file type it happened in.

    Structural review reads development sources only, so a doc rewrite that
    dropped a documented deploy procedure produced no signal from any check in
    the review hook: whitespace was clean, the remaining markdown still
    validated, and VibeGuard scanned what the change added.
    """

    def _structure(self, metadata: dict[str, dict[str, object]]) -> dict[str, object]:
        from agent_review_structure import REVIEW_NET_DELETION_LIMIT, net_deletion_findings

        return {
            "net_deletion_limit": REVIEW_NET_DELETION_LIMIT,
            "net_deletions": net_deletion_findings(metadata),
        }

    def test_a_markdown_rewrite_that_loses_content_fails_review(self) -> None:
        from agent_review_hook import net_deletion_failures

        structure = self._structure(
            {"docs/deploy.md": {"additions": 98, "deletions": 171}}
        )
        failures = net_deletion_failures(structure, "final diff checked; no unexpected files")

        self.assertTrue(failures)
        # The measured counts belong in the message: the agent that overwrote a
        # stale copy did not know anything had disappeared.
        self.assertIn("docs/deploy.md", failures[0])
        self.assertIn("net -73", failures[0])

    def test_naming_the_path_in_the_side_effect_audit_clears_it(self) -> None:
        from agent_review_hook import net_deletion_failures

        structure = self._structure(
            {"docs/deploy.md": {"additions": 98, "deletions": 171}}
        )

        self.assertEqual(
            [],
            net_deletion_failures(
                structure,
                "docs/deploy.md loses the local-gradle fallback section; "
                "superseded by the pipeline trigger documented above",
            ),
        )

    def test_missing_net_deletion_evidence_is_a_correctable_invocation(self) -> None:
        from agent_review_hook import (
            net_deletion_failures,
            review_input_invocation_failure,
            review_input_invocation_failure_details,
        )

        structure = self._structure(
            {"docs/deploy.md": {"additions": 98, "deletions": 171}}
        )
        failures = net_deletion_failures(structure, "final diff checked")

        self.assertTrue(review_input_invocation_failure(failures))
        details = review_input_invocation_failure_details(
            failures,
            {"scope": "changed-files", "checked_paths": ["docs/deploy.md"]},
            "full worktree",
        )
        self.assertIn("--side-effect-audit-evidence", details[-1])
        self.assertIn("no lifecycle checkpoint failed", details[-1])
        self.assertNotIn("repair-verify", " ".join(details))

    def test_an_ordinary_edit_and_a_growing_file_stay_silent(self) -> None:
        from agent_review_hook import net_deletion_failures

        quiet = self._structure(
            {
                "scripts/thing.py": {"additions": 120, "deletions": 4},
                "docs/notes.md": {"additions": 10, "deletions": 30},
                "docs/binary.png": {"additions": None, "deletions": None},
            }
        )

        self.assertEqual([], net_deletion_failures(quiet, ""))


class StaleBaseBlocksReviewTests(unittest.TestCase):
    """Rewriting a path the base already moved is how a stale read reaches disk."""

    def _args(self, boundary_evidence: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            project=Path("/repo"),
            boundary_plan_evidence=boundary_evidence,
        )

    def _runner(
        self,
        moved: str,
        behind: str = "21",
        upstream: str = "",
        merge_head: str = "",
        unresolved: str = "",
        base_is_merged: bool = True,
    ):
        def run_command(command: list[str], _cwd: Path) -> dict[str, object]:
            if command == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                return {"returncode": 0, "stdout": "feature\n", "stderr": ""}
            if command[:2] == ["git", "rev-parse"] and "@{upstream}" in command:
                if upstream:
                    return {"returncode": 0, "stdout": f"{upstream}\n", "stderr": ""}
                return {"returncode": 1, "stdout": "", "stderr": ""}
            if command[:2] == ["git", "rev-parse"]:
                target = command[-1]
                if target == "MERGE_HEAD":
                    return {
                        "returncode": 0 if merge_head else 1,
                        "stdout": f"{merge_head}\n" if merge_head else "",
                        "stderr": "",
                    }
                ok = target == "origin/develop"
                return {"returncode": 0 if ok else 1, "stdout": target if ok else "", "stderr": ""}
            if command[1] == "merge-base":
                if "--is-ancestor" in command:
                    return {
                        "returncode": 0 if base_is_merged else 1,
                        "stdout": "",
                        "stderr": "",
                    }
                return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
            if command[1] == "rev-list":
                return {"returncode": 0, "stdout": f"{behind}\n", "stderr": ""}
            if command[1] == "diff":
                if "--diff-filter=U" in command:
                    return {"returncode": 0, "stdout": unresolved, "stderr": ""}
                return {"returncode": 0, "stdout": moved, "stderr": ""}
            raise AssertionError(command)

        return run_command

    def _structure(self, changed: list[str]) -> dict[str, object]:
        return {"discovery": {"path_metadata": {name: {} for name in changed}}}

    def test_rewriting_a_path_the_base_moved_fails_review(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0src/other.py\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertEqual(["docs/deploy.md"], checks["base_drift"]["drifted_paths"])
        self.assertTrue(failures)
        self.assertIn("21 commits behind origin/develop", failures[0])
        self.assertIn("docs/deploy.md", failures[0])

    def test_stale_base_refusal_is_an_invocation_failure(self) -> None:
        from agent_review_hook import (
            record_review_base_drift,
            review_input_invocation_failure,
        )

        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            {},
            failures,
        )

        self.assertTrue(review_input_invocation_failure(failures))

    def test_stale_base_invocation_requests_base_integration_without_repair(self) -> None:
        from agent_review_hook import (
            record_review_base_drift,
            review_input_invocation_failure_details,
        )

        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            {},
            failures,
        )

        details = review_input_invocation_failure_details(
            failures,
            {"scope": "changed-files", "checked_paths": ["docs/deploy.md"]},
            "full worktree",
        )

        self.assertIn("integrate the current base", details[-1])
        self.assertIn("no lifecycle checkpoint failed", details[-1])
        self.assertNotIn("repair-verify", " ".join(details))

    def test_stale_base_does_not_hide_a_real_review_failure(self) -> None:
        from agent_review_hook import (
            record_review_base_drift,
            review_input_invocation_failure,
        )

        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            {},
            failures,
        )
        failures.append("code review evidence is required")

        self.assertFalse(review_input_invocation_failure(failures))

    def test_an_up_to_date_checkout_is_silent(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0", behind="0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertEqual([], failures)

    def test_a_resolved_in_progress_merge_of_the_base_is_silent(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner(
                "docs/deploy.md\0",
                behind="26",
                merge_head="def456",
            ),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertEqual([], failures)
        self.assertEqual(
            "resolved in-progress merge already incorporates the current base ref",
            checks["base_drift"]["skipped"],
        )

    def test_an_unresolved_in_progress_merge_does_not_hide_stale_paths(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner(
                "docs/deploy.md\0",
                merge_head="def456",
                unresolved="docs/deploy.md\n",
            ),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertTrue(failures)
        self.assertEqual(
            ["docs/deploy.md"],
            checks["base_drift"]["unresolved_merge_paths"],
        )

    def test_a_path_the_base_left_alone_is_silent(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("src/unrelated.py\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertEqual([], failures)

    def test_recording_the_base_and_the_path_does_not_waive_the_block(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args("base revision origin/develop; re-read docs/deploy.md there; worktree owns it"),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertTrue(failures)
        self.assertIn("cannot waive this stale-base overlap", failures[0])

    def test_recording_a_commit_sha_does_not_waive_the_block(self) -> None:
        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args("re-read docs/deploy.md at 2903b6091 before rewriting it"),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertTrue(failures)
        self.assertIn("Integrate the current base", failures[0])

    def test_scope_evidence_does_not_waive_the_block(self) -> None:
        """An ordinary scope sentence cannot make a stale overlap reviewable."""

        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args("owned scope is docs/deploy.md; verification is a manual read"),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertTrue(failures)
        self.assertIn("Integrate the current base", failures[0])
        self.assertIn("cannot waive this stale-base overlap", failures[0])

    def test_a_branch_tracking_its_own_mirror_is_still_measured_against_the_base(self) -> None:
        """`@{upstream}` on a pushed work branch is that branch's own remote copy.

        Measured on a real branch: 0 commits behind its own mirror, 26 behind the
        integration base, 7 changed paths shared with it. Trusting the mirror
        would silence the check in exactly the case it exists for.
        """

        from agent_review_hook import record_review_base_drift, resolve_base_ref

        runner = self._runner("docs/deploy.md\0", upstream="origin/feature")

        self.assertEqual("origin/develop", resolve_base_ref(Path("/repo"), runner))

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(), runner, self._structure(["docs/deploy.md"]), checks, failures
        )

        self.assertTrue(failures)
        self.assertIn("origin/develop", failures[0])

    def test_a_real_base_upstream_is_honoured(self) -> None:
        from agent_review_hook import resolve_base_ref

        self.assertEqual(
            "origin/release-2026",
            resolve_base_ref(Path("/repo"), self._runner("", upstream="origin/release-2026")),
        )

    def test_the_refusal_requires_base_integration_before_review(self) -> None:
        """The refusal must not advertise evidence text as a stale-base waiver."""

        from agent_review_hook import record_review_base_drift

        checks: dict[str, object] = {}
        failures: list[str] = []
        record_review_base_drift(
            self._args(),
            self._runner("docs/deploy.md\0"),
            self._structure(["docs/deploy.md"]),
            checks,
            failures,
        )

        self.assertIn("Stop before review", failures[0])
        self.assertIn("Integrate the current base", failures[0])
        self.assertNotIn("for example", failures[0])


if __name__ == "__main__":
    unittest.main()
