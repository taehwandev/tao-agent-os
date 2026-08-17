from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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
from agent_review_hook import review_hook, review_vibeguard_command, workflow_validate_failure_detail
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
    RETROSPECTIVE_CHECK_GATE,
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


class FinishGatePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_documentation_concern_routes_to_documentation_workflow(self) -> None:
        self.assertEqual(
            ("workflows/skills/documentation-update/SKILL.md",),
            CONCERNS["documentation"],
        )

    def test_preflight_reclassifies_short_confirmation_without_a_parent_capsule(self) -> None:
        # --request-classified is honored only when a valid parent execution
        # capsule proves a parent already resolved the request. Preflight has no
        # such capsule here, so "응" is classified like any other request and its
        # Grill-Me verdict stands. The capsule-backed true positive lives in
        # tests/test_workflow_classification_evidence.py.
        args = SimpleNamespace(
            command="refactor",
            request="응",
            request_classified=True,
            classification_evidence=(
                "clear-scoped: implement the confirmed workflow fixes"
            ),
            platform=[],
            concern=[],
            surface_path=[],
            project=ROOT,
        )

        route, error, returncode = agent_preflight.route_payload(args, {})

        self.assertIsNone(route)
        self.assertEqual(2, returncode)
        self.assertIn("intent envelope", error)

    def test_preflight_classified_without_request_or_capsule_is_rejected(self) -> None:
        # Today's fall-through returned None for the classification and then
        # sailed through route_block_reason(command, None) without blocking.
        args = SimpleNamespace(
            command="refactor",
            request=None,
            request_classified=True,
            classification_evidence="scope clarified: blockers resolved.",
            platform=[],
            concern=[],
            surface_path=[],
            project=ROOT,
        )

        route, error, returncode = agent_preflight.route_payload(args, {})

        self.assertIsNone(route)
        self.assertEqual(2, returncode)
        self.assertIn("intent envelope", error)

    def test_analysis_preflight_routes_once_and_defers_capsule_creation(self) -> None:
        route = resolve_docs("analysis", None, [], request_classified=True)
        route_result = {
            "returncode": 0,
            "stdout": json.dumps(route),
            "stderr": "",
        }
        vibeguard = {"returncode": 0, "overall": {"status": "Ready"}}
        git_status = {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            args = agent_preflight.build_parser(ROOT).parse_args(
                [
                    "--command",
                    "analysis",
                    "--request",
                    "Inspect routing only and summarize it.",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                ]
            )
            with patch.object(agent_preflight, "active_runtime_label", return_value="codex"), patch.object(
                agent_preflight, "run_command", return_value=git_status
            ), patch.object(agent_preflight, "route_result", return_value=route_result) as routed, patch.object(
                agent_preflight, "cached_vibeguard", return_value=vibeguard
            ), patch.object(agent_preflight, "lesson_summary", return_value={"accepted": [], "promoted": [], "candidate_count": 0}), patch.object(
                agent_preflight, "check_agent_hooks", return_value=([], [])
            ):
                self.assertEqual(0, agent_preflight.run_preflight(args, ROOT))

            evidence = json.loads((project / ".tao" / "preflight.json").read_text(encoding="utf-8"))

        self.assertEqual(1, routed.call_count)
        self.assertIn("execution_snapshot", evidence)
        self.assertNotIn("project_git", evidence["execution_snapshot"])
        self.assertFalse((project / ".tao" / "execution-capsule.json").exists())

    def test_finish_cli_has_no_gate_override_option(self) -> None:
        finish_options = {
            option
            for action in agent_finish_check.build_parser(ROOT)._actions
            for option in action.option_strings
        }
        wrapper_options = {
            option
            for action in agent_hook.build_parser()._actions
            for option in action.option_strings
        }

        self.assertNotIn("--gate", finish_options)
        self.assertNotIn("--gate", wrapper_options)

    def test_finish_legacy_gate_input_returns_migration_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent-hook.py"),
                "finish",
                "--gate",
                "report=done",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("finish no longer accepts --gate", result.stderr)
        self.assertIn("gate or gate-batch", result.stderr)
        self.assertNotIn("ambiguous option", result.stderr)

    def test_finish_word_in_other_hook_does_not_trigger_migration_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent-hook.py"),
                "start",
                "--request",
                "finish",
                "--gate",
                "report=done",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("unrecognized arguments: --gate report=done", result.stderr)
        self.assertNotIn("finish no longer accepts --gate", result.stderr)

    def test_finish_final_check_failure_requires_retrospective_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["TAO_STATE_HOME"] = temp_dir

            retrospective_required = requires_retrospective(
                missed_gates=[],
                gate_policy_failures=[],
                finish_failures=["workflow validate failed"],
            )
            result = write_retrospective_candidate(
                {
                    "retrospective_required": retrospective_required,
                    "missed_gates": [],
                    "gate_signals": [{"gate": "workflow validate", "signal": "FAIL"}],
                }
            )

            self.assertTrue(retrospective_required)
            self.assertTrue(result["created"])
            lesson_path = Path(temp_dir) / result["relative_path"]
            lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
            self.assertEqual("finish_gate_failure", lesson["failure_type"])
            self.assertEqual("finish_failed_before_completion", lesson["root_cause"])
            self.assertEqual(
                "repair_verify_then_resume_failed_checkpoint",
                lesson["next_action"],
            )

    def test_unattributed_read_only_revision_drift_requires_runtime_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["TAO_STATE_HOME"] = temp_dir
            failures = [
                "read-only execution was declared but the project root changed after "
                "start; a clean worktree cannot attribute the revision change to an "
                "external actor, so rerun the lifecycle without --read-only"
            ]

            retrospective_required, lesson = agent_finish_check.process_failure_learning(
                preflight={"agent_run_id": "read-only-revision-drift"},
                missed_gates=[],
                gate_policy_failures=[],
                gate_signals=[],
                failures=failures,
            )

            self.assertTrue(retrospective_required)
            self.assertTrue(lesson["created"])
            self.assertIn("retrospective repair is required", " ".join(failures))

    def test_required_doc_drift_failure_names_exact_documentation_receipt_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["TAO_STATE_HOME"] = temp_dir
            failures = ["execution capsule required doc hash changed: AGENTS.md"]

            agent_finish_check.process_failure_learning(
                preflight={"agent_run_id": "required-doc-drift-recovery"},
                missed_gates=[],
                gate_policy_failures=[],
                gate_signals=[],
                failures=failures,
            )

            joined_failures = " ".join(failures)
            self.assertIn("documentation SUCCESS", joined_failures)
            self.assertIn("exact route-relative required doc target", joined_failures)
            self.assertIn(
                "run repair-verify for the actual failed checkpoint first",
                joined_failures,
            )
            self.assertIn("repair_evidence", joined_failures)
            self.assertIn("resume_checkpoint", joined_failures)

    def test_source_docs_gate_covers_source_driven_routes_only(self) -> None:
        for command in sorted(SOURCE_DOCS_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(SOURCE_DOCS_GATE, route["gates"])

        for command in ("ambiguity", "commit", "git_commit", "retrospective", "test", "triage"):
            with self.subTest(restored_command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(SOURCE_DOCS_GATE, route["gates"])

    def test_workspace_scope_checkpoint_evidence_is_validated_when_present(self) -> None:
        failures = validate_gate_evidence(
            {
                "workspace scope checkpoint": (
                    "starting primary repo: app; secondary repo/source of truth: web; "
                    "mode: primary-led secondary write; verification: web test plus app smoke"
                )
            },
            [],
        )

        self.assertEqual([], failures)

        failures = validate_gate_evidence(
            {"workspace scope checkpoint": "primary repo: app; secondary repo: web"},
            [],
        )

        self.assertTrue(any("workspace scope checkpoint evidence" in failure for failure in failures))

    def test_finish_evidence_examples_for_doc_impact_and_multi_agent_pass(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "pre-code/pre-edit artifact selection: workflow card and README; "
                    "impact decision: not applicable; reason: no durable behavior, "
                    "no workflow policy, no public contract, no operator action, "
                    "and no acceptance criteria changed, so this does not require "
                    "creating/updating that artifact"
                ),
                MULTI_AGENT_GATE: (
                    "serial/single-agent decision; concrete reason: small "
                    "same-file/same-boundary scope with overlapping contract risk, "
                    "so parallel subagents were not safe; verification: workflow "
                    "validate plus focused unit tests"
                ),
            },
            [DOCUMENTATION_IMPACT_GATE, MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_multi_agent_serial_reason_accepts_hyphenated_same_file(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "serial/single-agent decision; concrete reason: same-file ownership "
                    "would overlap; verification: focused review"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_cycle_contract_evidence_requires_bounded_cycle_details(self) -> None:
        failures = validate_gate_evidence(
            {CYCLE_CONTRACT_GATE: "cycle contract completed"},
            [CYCLE_CONTRACT_GATE],
        )

        self.assertTrue(any("cycle contract evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                CYCLE_CONTRACT_GATE: (
                    "cycle_type=workflow_setup; input_scope=router workflow policy; "
                    "allowed_changes=workflow docs, route gates, finish-check validators, tests; "
                    "forbidden_changes=unrelated dirty files, external runtime config, deploys; "
                    "acceptance criteria=routes include a bounded cycle gate; "
                    "verification=unit tests and workflow validate; "
                    "stop condition=cycle gate is routed, documented, and validated; "
                    "checkpoint=handoff for separate review cycle"
                )
            },
            [CYCLE_CONTRACT_GATE],
        )

        self.assertEqual([], failures)

    def test_prd_and_product_routes_require_alignment_brief(self) -> None:
        prd_route = resolve_docs("prd", None, [], request_classified=True)
        product_route = resolve_docs("product", None, [], request_classified=True)

        self.assertIn(PLATFORM_SELECTION_GATE, product_route["gates"])
        self.assertLess(
            product_route["gates"].index(PLATFORM_SELECTION_GATE),
            product_route["gates"].index("PRD"),
        )
        self.assertIn(ALIGNMENT_BRIEF_GATE, prd_route["gates"])
        self.assertLess(
            prd_route["gates"].index(ALIGNMENT_BRIEF_GATE),
            prd_route["gates"].index("PRD draft"),
        )
        self.assertIn(ALIGNMENT_BRIEF_GATE, product_route["gates"])
        self.assertLess(
            product_route["gates"].index(ALIGNMENT_BRIEF_GATE),
            product_route["gates"].index("PRD"),
        )
        self.assertIn(route_doc("workflows/skills/prd-creation/SKILL.md"), prd_route["docs"])
        self.assertIn(route_doc("workflows/skills/prd-creation/SKILL.md"), product_route["docs"])

    def test_prd_and_spec_routes_get_documentation_enforcement_gates(self) -> None:
        for command in ("prd", "spec"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(SOURCE_DOCS_GATE, route["gates"])
                self.assertIn(DOCUMENTATION_IMPACT_GATE, route["gates"])
                self.assertIn(DOCUMENTATION_GATE, route["gates"])
                self.assertIn(PRD_DRAFT_GATE, route["gates"])
                self.assertLess(
                    route["gates"].index(SOURCE_DOCS_GATE),
                    route["gates"].index("PRD draft"),
                )
                self.assertLess(
                    route["gates"].index(DOCUMENTATION_IMPACT_GATE),
                    route["gates"].index("PRD draft"),
                )
                self.assertLess(
                    route["gates"].index(ALIGNMENT_BRIEF_GATE),
                    route["gates"].index("PRD draft"),
                )
                self.assertLess(
                    route["gates"].index("PRD draft"),
                    route["gates"].index(DOCUMENTATION_GATE),
                )
                self.assertIn(route_doc("workflows/skills/documentation-update/SKILL.md"), route["docs"])

    def test_docs_route_gets_documentation_enforcement_gates(self) -> None:
        route = resolve_docs("docs", None, [], request_classified=True)

        self.assertIn(SOURCE_DOCS_GATE, route["gates"])
        self.assertIn(DOCUMENTATION_IMPACT_GATE, route["gates"])
        self.assertIn(DOCUMENTATION_GATE, route["gates"])
        self.assertLess(route["gates"].index(SOURCE_DOCS_GATE), route["gates"].index("edit"))
        self.assertLess(route["gates"].index(DOCUMENTATION_IMPACT_GATE), route["gates"].index("edit"))
        self.assertIn(route_doc("common/skills/source-driven-development/SKILL.md"), route["docs"])

    def test_prd_draft_evidence_requires_artifact_and_content(self) -> None:
        failures = validate_gate_evidence(
            {PRD_DRAFT_GATE: "PRD draft completed"},
            [PRD_DRAFT_GATE],
        )

        self.assertTrue(any("PRD draft evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {PRD_DRAFT_GATE: "discussed acceptance criteria and scope in conversation"},
            [PRD_DRAFT_GATE],
        )

        self.assertTrue(any("PRD draft evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                PRD_DRAFT_GATE: (
                    "created docs/prd-login.md; in scope: login screen; "
                    "acceptance criteria: given valid credentials when submit then navigate home"
                )
            },
            [PRD_DRAFT_GATE],
        )

        self.assertEqual([], failures)

    def test_modify_and_analysis_routes_require_alignment_brief(self) -> None:
        for command in sorted(ALIGNMENT_BRIEF_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(ALIGNMENT_BRIEF_GATE, route["gates"])

    def test_feature_alignment_runs_before_acceptance_criteria(self) -> None:
        route = resolve_docs("feature", None, [], request_classified=True)

        self.assertLess(
            route["gates"].index(ALIGNMENT_BRIEF_GATE),
            route["gates"].index("PRD/ARD applicability"),
        )
        self.assertLess(
            route["gates"].index(ALIGNMENT_BRIEF_GATE),
            route["gates"].index("acceptance criteria"),
        )
        self.assertIn(route_doc("common/skills/task-intake-effort-routing/SKILL.md"), route["docs"])

    def test_analysis_and_setup_alignment_runs_before_work_gates(self) -> None:
        planning_route = resolve_docs("planning", None, [], request_classified=True)
        release_route = resolve_docs("release", None, [], request_classified=True)
        multi_agent_route = resolve_docs("multi-agent", None, [], request_classified=True)

        self.assertLess(
            planning_route["gates"].index(ALIGNMENT_BRIEF_GATE),
            planning_route["gates"].index("sources"),
        )
        self.assertLess(
            release_route["gates"].index(ALIGNMENT_BRIEF_GATE),
            release_route["gates"].index("package"),
        )
        self.assertLess(
            multi_agent_route["gates"].index(ALIGNMENT_BRIEF_GATE),
            multi_agent_route["gates"].index("roles"),
        )

    def test_triage_and_ambiguity_select_required_docs_without_code_work_gates(self) -> None:
        for command in ("triage", "ambiguity"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertTrue(route["required_docs"])
                self.assertNotIn(TEST_GATE, route["gates"])
                self.assertNotIn(MULTI_AGENT_GATE, route["gates"])

    def test_docs_review_checks_review_readiness(self) -> None:
        route = resolve_docs("docs-review", None, [], request_classified=True)

        self.assertIn(REVIEW_READINESS_GATE, route["gates"])
        self.assertLess(route["gates"].index(REVIEW_READINESS_GATE), route["gates"].index("source review"))

    def test_workflow_setup_selects_required_docs_before_repair(self) -> None:
        route = resolve_docs("workflow-setup", None, ["structure"], request_classified=True)

        self.assertTrue(route["required_docs"])
        self.assertIn(SOURCE_DOCS_GATE, route["gates"])

    def test_docs_route_selects_required_docs_without_confirmation_gate(self) -> None:
        route = resolve_docs("docs", None, ["structure"], request_classified=True)

        self.assertTrue(route["required_docs"])
        self.assertNotIn("route docs read", route["gates"])

    def test_finish_policy_rejects_empty_gate_phrases(self) -> None:
        failures = validate_gate_evidence(
            {
                AMBIGUITY_GATE: "done",
                ALIGNMENT_BRIEF_GATE: "done",
                DOCUMENTATION_IMPACT_GATE: "done",
                DOCUMENTATION_GATE: "done",
                SOURCE_DOCS_GATE: "done",
                PLATFORM_SELECTION_GATE: "done",
                REVIEW_READINESS_GATE: "done",
                PRD_DRAFT_GATE: "done",
                TEST_GATE: "done",
                BOUNDARY_PLAN_GATE: "done",
                MULTI_AGENT_GATE: "done",
                AGENTIC_RUN_STATE_GATE: "done",
                SIDE_EFFECT_AUDIT_GATE: "done",
            },
            [
                AMBIGUITY_GATE,
                ALIGNMENT_BRIEF_GATE,
                DOCUMENTATION_IMPACT_GATE,
                DOCUMENTATION_GATE,
                SOURCE_DOCS_GATE,
                PLATFORM_SELECTION_GATE,
                REVIEW_READINESS_GATE,
                PRD_DRAFT_GATE,
                TEST_GATE,
                BOUNDARY_PLAN_GATE,
                MULTI_AGENT_GATE,
                AGENTIC_RUN_STATE_GATE,
                SIDE_EFFECT_AUDIT_GATE,
            ],
        )

        self.assertEqual(13, len(failures))

    def test_required_gate_skip_evidence_fails_unless_gate_allows_skip(self) -> None:
        failures = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: "skipped because this looked small",
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertTrue(any("cannot pass by recording a skip" in failure for failure in failures))

        allowed = validate_gate_evidence(
            {
                TEST_GATE: "tests not run because docs-only change has no useful test",
            },
            [TEST_GATE],
        )

        self.assertEqual([], allowed)

    def test_required_gate_skip_guard_ignores_policy_implementation_language(self) -> None:
        failures = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: (
                    "boundary/scope: finish-check skip validation policy; nearest "
                    "verification/check: unit tests and workflow validate covered the "
                    "gate evidence validator; review budget: one public owner per runtime file"
                )
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertEqual([], failures)

        failures = validate_gate_evidence(
            {
                CYCLE_CONTRACT_GATE: (
                    "cycle_type=workflow_setup; input_scope=gate evidence policy; "
                    "allowed_changes=finish-check validator tests; "
                    "forbidden_changes=unrelated behavior; "
                    "acceptance criteria=required gates fail on real skipped or "
                    "deferred fixes; verification=unit tests; "
                    "stop condition=policy language does not count as a gate skip; "
                    "checkpoint=finish"
                )
            },
            [CYCLE_CONTRACT_GATE],
        )

        self.assertEqual([], failures)

    def test_required_gate_skip_guard_allows_non_skip_unable_language(self) -> None:
        failures = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: (
                    "boundary/scope: regression reproduction notes; nearest "
                    "verification/check: unable to reproduce further edge cases "
                    "after unit tests and workflow validate; no runtime source change"
                )
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertEqual([], failures)

    def test_required_gate_skip_guard_allows_scoped_review_caveat(self) -> None:
        failures = validate_gate_evidence(
            {
                SIDE_EFFECT_AUDIT_GATE: (
                    "side-effect audit checked final diff; scope/risk reviewed: "
                    "not reviewed by a second person but self-tested with focused "
                    "unit coverage; result: no side effects found"
                )
            },
            [SIDE_EFFECT_AUDIT_GATE],
        )

        self.assertEqual([], failures)

    def test_required_gate_skip_guard_blocks_explicit_not_applicable_required_gate(self) -> None:
        failures = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: (
                    "not applicable because this change looked small"
                )
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertTrue(any("cannot pass by recording a skip" in failure for failure in failures))

    def test_alignment_evidence_requires_user_visible_checkpoint(self) -> None:
        failures = validate_gate_evidence(
            {
                ALIGNMENT_BRIEF_GATE: (
                    "same understanding: explicit goal captured; possible differences: uncertain scope; "
                    "unsupported assumptions: default MVP unless blocker question changes it"
                )
            },
            [ALIGNMENT_BRIEF_GATE],
        )

        self.assertTrue(any("user-visible checkpoint" in failure for failure in failures))

    def test_alignment_evidence_accepts_choice_question_checkpoint(self) -> None:
        failures = validate_gate_evidence(
            {
                ALIGNMENT_BRIEF_GATE: (
                    "same understanding: rewrite requested; possible differences: genre and point of view; "
                    "unsupported assumptions: style cue alone does not choose retrospective mode; "
                    "choice question presented before edits"
                )
            },
            [ALIGNMENT_BRIEF_GATE],
        )

        self.assertEqual([], failures)

    def test_finish_policy_accepts_specific_evidence(self) -> None:
        failures = validate_gate_evidence(
            {
                AMBIGUITY_GATE: "no blockers; safe assumption recorded",
                ALIGNMENT_BRIEF_GATE: (
                    "same understanding: explicit goal captured; possible differences: uncertain scope; "
                    "unsupported assumptions: default MVP unless blocker question changes it; "
                    "user-visible checkpoint told the user before edits"
                ),
                DOCUMENTATION_IMPACT_GATE: (
                    "before implementation documentation impact decision: "
                    "artifact: workflow card; update workflows/README.md because workflow policy changed"
                ),
                DOCUMENTATION_GATE: (
                    "updated workflows/README.md because workflow policy changed; "
                    "source-of-truth updated for durable agent behavior"
                ),
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "searched PRD/spec/ARD source-of-truth docs; none found; "
                    "applied takeaway: used the user request as source of truth"
                ),
                PLATFORM_SELECTION_GATE: (
                    "selected platform: ios; loaded platforms/ios/skills/ios-architecture/SKILL.md "
                    "before PRD/ARD architecture work"
                ),
                REVIEW_READINESS_GATE: (
                    "review readiness checked markdown frontmatter status/type counts; "
                    "human-reviewed-needed review queue found"
                ),
                PRD_DRAFT_GATE: (
                    "created docs/prd-login.md; in scope: login screen with email/password; "
                    "acceptance criteria: given valid credentials when submit then navigate home"
                ),
                TEST_GATE: "unittest tests/test_workflow_routing.py passed",
                BOUNDARY_PLAN_GATE: (
                    "existing workflow gate policy boundary; review budget: one public owner "
                    "per runtime file; verification via unittest"
                ),
                MULTI_AGENT_GATE: (
                    "no subagent split: serial single-agent because small same-file policy change "
                    "with same-file scope"
                ),
                AGENTIC_RUN_STATE_GATE: (
                    "run state: scoped; next transition: scoped -> acting; "
                    "evidence: boundary gate and unittest verification command recorded; "
                    "checkpoint: implementation handoff; blocker status: no blockers"
                ),
                SIDE_EFFECT_AUDIT_GATE: "final diff checked; no unexpected generated files or lockfile changes",
            },
            [
                AMBIGUITY_GATE,
                ALIGNMENT_BRIEF_GATE,
                DOCUMENTATION_IMPACT_GATE,
                DOCUMENTATION_GATE,
                SOURCE_DOCS_GATE,
                PLATFORM_SELECTION_GATE,
                REVIEW_READINESS_GATE,
                PRD_DRAFT_GATE,
                TEST_GATE,
                BOUNDARY_PLAN_GATE,
                MULTI_AGENT_GATE,
                AGENTIC_RUN_STATE_GATE,
                SIDE_EFFECT_AUDIT_GATE,
            ],
        )

        self.assertEqual([], failures)

    def test_boundary_plan_requires_runtime_structure_decision(self) -> None:
        missing = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: (
                    "boundary/scope: feature UI owner migration; nearest verification/check: "
                    "focused unit tests and compile"
                )
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertTrue(any("top-level-owner review budget" in failure for failure in missing))

        accepted = validate_gate_evidence(
            {
                BOUNDARY_PLAN_GATE: (
                    "boundary/scope: feature UI owner migration; file split: one public owner "
                    "per runtime file; nearest verification/check: focused unit tests and compile"
                )
            },
            [BOUNDARY_PLAN_GATE],
        )

        self.assertEqual([], accepted)

    def test_source_docs_evidence_requires_source_artifact_discovery_before_work(self) -> None:
        failures = validate_gate_evidence(
            {SOURCE_DOCS_GATE: "checked docs"},
            [SOURCE_DOCS_GATE],
        )

        self.assertTrue(any("route required_docs" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "searched source-of-truth docs before implementation; "
                    "found docs/module/README.md and read it; "
                    "applied the module boundary to the work"
                )
            },
            [SOURCE_DOCS_GATE],
        )

        self.assertTrue(any("route required_docs" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "searched source-of-truth docs and found docs/module/README.md; "
                    "no task-specific rule was recorded"
                )
            },
            [SOURCE_DOCS_GATE],
        )

        self.assertTrue(any("task-specific takeaway" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read the route required_docs manifest directly before implementation; "
                    "searched source-of-truth docs and found docs/module/README.md; "
                    "applied takeaway: keep the module boundary unchanged in this work"
                )
            },
            [SOURCE_DOCS_GATE],
        )

        self.assertEqual([], failures)

    def test_source_docs_structured_fields_synthesize_finish_valid_evidence(self) -> None:
        evidence, missing = synthesize_gate_evidence(
            SOURCE_DOCS_GATE,
            "",
            {
                "required_docs": "all 27 route required_docs entries read directly",
                "source": "AGENTS.md and routed workflow/skill cards",
                "takeaway": "use one start hook and keep the parent as ledger owner",
            },
        )

        self.assertEqual([], missing)
        self.assertEqual(
            [],
            validate_gate_evidence({SOURCE_DOCS_GATE: evidence}, [SOURCE_DOCS_GATE]),
        )

        _, legacy_missing = synthesize_gate_evidence(
            SOURCE_DOCS_GATE,
            "",
            {"source": "AGENTS.md", "outcome": "applied one-start"},
        )
        self.assertEqual(["required_docs", "takeaway"], legacy_missing)

    def test_platform_selection_evidence_requires_platform_or_not_applicable_reason(self) -> None:
        failures = validate_gate_evidence(
            {PLATFORM_SELECTION_GATE: "done"},
            [PLATFORM_SELECTION_GATE],
        )

        self.assertTrue(any("platform selection evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                PLATFORM_SELECTION_GATE: (
                    "selected platform: web; loaded platforms/web/skills/web-architecture/SKILL.md "
                    "before PRD/ARD architecture work"
                )
            },
            [PLATFORM_SELECTION_GATE],
        )

        self.assertEqual([], failures)

        failures = validate_gate_evidence(
            {
                PLATFORM_SELECTION_GATE: (
                    "not applicable because workflow-only docs change has no platform-specific runtime"
                )
            },
            [PLATFORM_SELECTION_GATE],
        )

        self.assertEqual([], failures)

    def test_review_readiness_evidence_requires_status_type_queue(self) -> None:
        failures = validate_gate_evidence(
            {REVIEW_READINESS_GATE: "checked docs"},
            [REVIEW_READINESS_GATE],
        )

        self.assertTrue(any("review readiness evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                REVIEW_READINESS_GATE: (
                    "review readiness checked markdown frontmatter status/type counts; "
                    "human-reviewed-needed review queue found under common/ and workflows/"
                )
            },
            [REVIEW_READINESS_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_evidence_requires_target_and_reason(self) -> None:
        failures = validate_gate_evidence(
            {DOCUMENTATION_GATE: "updated docs"},
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("documentation decision" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "updated docs/prd.md because acceptance criteria changed; "
                    "source-of-truth updated for durable behavior"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_evidence_requires_pre_edit_decision(self) -> None:
        failures = validate_gate_evidence(
            {DOCUMENTATION_IMPACT_GATE: "will think about docs later"},
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("documentation impact evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: workflow card; "
                    "update workflows/README.md because workflow policy changed"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_rejects_non_creation_without_no_durable_reason(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "not applicable because new feature changed behavior"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("cannot use not-applicable/no-docs" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "not applicable because answer-only with no durable behavior"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_accepts_negated_durable_change_list(self) -> None:
        # Negated durable-change statements must read as negated. Scrubbing the
        # no-durable reasons as plain substrings failed two ways: a shorter
        # entry deleted the prefix of a longer one and left an orphaned verb
        # ("no workflow policy changed" -> " changed") that paired with any
        # later noun, and only the first item of a coordinated "no A, B, or C
        # changed" list was ever removed.
        for reason in (
            "no durable behavior, no public contract, no operator action, "
            "no acceptance criteria, no workflow policy changed; "
            "workflow_gate_policy.py already documents the retrospective-check "
            "requirement the script was fixed to match",
            "no durable behavior, public contract, workflow policy, or "
            "acceptance criteria changed",
        ):
            with self.subTest(reason=reason):
                failures = validate_gate_evidence(
                    {
                        DOCUMENTATION_IMPACT_GATE: (
                            "pre-code/pre-edit artifact selection: workflow card; "
                            "impact decision: not applicable; reason: " + reason
                        )
                    },
                    [DOCUMENTATION_IMPACT_GATE],
                )

                self.assertEqual([], failures)

        # Claiming no-docs while naming a real durable change must still fail.
        for reason in (
            "no durable behavior; updated the public contract and revised "
            "acceptance criteria",
            "no durable behavior, updated the public contract",
            "no durable behavior but we changed the workflow policy",
        ):
            with self.subTest(durable=reason):
                failures = validate_gate_evidence(
                    {
                        DOCUMENTATION_IMPACT_GATE: (
                            "pre-code/pre-edit artifact selection: workflow card; "
                            "impact decision: not applicable; reason: " + reason
                        )
                    },
                    [DOCUMENTATION_IMPACT_GATE],
                )

                self.assertTrue(
                    any("cannot use not-applicable/no-docs" in failure for failure in failures)
                )

    def test_documentation_impact_rejects_no_docs_for_requirements_change(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "not applicable because no public contract, but requirements changed "
                    "the acceptance criteria"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("cannot use not-applicable/no-docs" in failure for failure in failures))

    def test_documentation_impact_allows_unchanged_when_existing_doc_covers_change(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "unchanged docs/product/spec.md; inspected the existing doc and it "
                    "already covers the revised acceptance criteria"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_allows_unchanged_when_existing_doc_contains_change(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: "
                    "drafts/article.md; unchanged; opened and reviewed the exact "
                    "draft path, which already contains the requested wording and "
                    "acceptance coverage"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_unchanged_allows_multiple_opened_docs_with_plural_coverage(self) -> None:
        evidence = (
            "documentation decision: unchanged; docs/product/prd.md and "
            "docs/product/ard.md were opened and inspected; those already-read "
            "documents already cover the behavior and acceptance criteria"
        )

        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation artifact selection: release note; "
                    f"impact decision: unchanged; {evidence}"
                ),
                DOCUMENTATION_GATE: evidence,
            },
            [DOCUMENTATION_IMPACT_GATE, DOCUMENTATION_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_uses_explicit_updated_decision_before_reason_text(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "pre-edit documentation artifact selection: "
                    "workflows/skills/documentation-update/references/current-guidance.md; "
                    "impact decision: updated; reason: clarified the unchanged-evidence "
                    "contract"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_impact_rejects_unchanged_without_inspection_proof(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "unchanged docs/product/spec.md because it already covers the "
                    "revised acceptance criteria"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("can use unchanged only" in failure for failure in failures))

    def test_documentation_impact_rejects_vague_unchanged_decision(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: feature spec; "
                    "unchanged because requirements changed"
                )
            },
            [DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("can use unchanged only" in failure for failure in failures))

    def test_documentation_gate_rejects_no_docs_for_requirements_change(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "not applicable for docs/product/spec.md because no public contract, "
                    "but requirements changed the acceptance criteria"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("cannot use not-applicable/no-docs" in failure for failure in failures))

    def test_documentation_uses_explicit_updated_decision_before_reason_text(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "documentation decision: updated; source-of-truth target: "
                    "workflows/skills/documentation-update/references/current-guidance.md; "
                    "reason: documented the unchanged-evidence contract"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertEqual([], failures)

        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "unchanged docs/product/spec.md; inspected it and the existing doc "
                    "already covers the revised acceptance criteria"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_gate_rejects_unchanged_without_inspection_proof(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "unchanged docs/product/spec.md because it already covers the "
                    "revised acceptance criteria"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("can use unchanged only" in failure for failure in failures))

    def test_documentation_gate_rejects_unchanged_without_named_doc_path(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "unchanged; inspected the module readme and it already covers "
                    "the acceptance criteria"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("can use unchanged only" in failure for failure in failures))

    def test_required_documentation_gate_rejects_empty_evidence(self) -> None:
        failures = validate_gate_evidence(
            {DOCUMENTATION_GATE: ""},
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(
            any("required and cannot be empty" in failure for failure in failures)
        )

    def test_documentation_skip_requires_user_approval_not_reason(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "documentation decision: not applicable; target: module README; "
                    "reason: answer-only with no durable behavior"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("cannot be skipped" in failure for failure in failures))

    def test_documentation_skipped_phrase_requires_user_approval(self) -> None:
        failures = validate_gate_evidence(
            {DOCUMENTATION_GATE: "documentation skipped because the change was trivial"},
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("cannot be skipped" in failure for failure in failures))

    def test_documentation_skip_passes_with_recorded_user_approval(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "documentation decision: not applicable; target: module README; "
                    "reason: answer-only; asked the user 문서를 스킵할까요 and the user "
                    "approved skipping the doc"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertEqual([], failures)

    def test_documentation_skip_does_not_pass_when_user_was_only_asked(self) -> None:
        failures = validate_gate_evidence(
            {
                DOCUMENTATION_GATE: (
                    "documentation decision: not applicable; target: module README; "
                    "reason: answer-only; asked the user whether to skip the doc but "
                    "no approval was received"
                )
            },
            [DOCUMENTATION_GATE],
        )

        self.assertTrue(any("cannot be skipped" in failure for failure in failures))

    def test_triage_and_plan_routes_get_product_reentry_gate(self) -> None:
        for command in sorted(PRODUCT_REENTRY_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertIn(PRODUCT_REENTRY_GATE, route["gates"])

    def test_product_reentry_gate_requires_non_empty_evidence(self) -> None:
        failures = validate_gate_evidence(
            {PRODUCT_REENTRY_GATE: ""},
            [PRODUCT_REENTRY_GATE],
        )

        self.assertTrue(
            any("required and cannot be empty" in failure for failure in failures)
        )

    def test_product_reentry_gate_allows_no_implementation_proposed(self) -> None:
        failures = validate_gate_evidence(
            {
                PRODUCT_REENTRY_GATE: (
                    "recommendation only; no implementation proposed, this triage "
                    "stayed at status and classification"
                )
            },
            [PRODUCT_REENTRY_GATE],
        )

        self.assertEqual([], failures)

    def test_product_reentry_gate_rejects_roadmap_without_prd_coverage(self) -> None:
        failures = validate_gate_evidence(
            {
                PRODUCT_REENTRY_GATE: (
                    "proposed an implementation roadmap with three milestones and a "
                    "task list for the next feature"
                )
            },
            [PRODUCT_REENTRY_GATE],
        )

        self.assertTrue(any("PRD coverage" in failure for failure in failures))

    def test_product_reentry_gate_allows_roadmap_with_prd_coverage(self) -> None:
        failures = validate_gate_evidence(
            {
                PRODUCT_REENTRY_GATE: (
                    "proposed implementation roadmap; re-enter product route and map "
                    "each item to an Accepted PRD link, with an ARD link for module "
                    "boundary changes, before any implementation task or PR"
                )
            },
            [PRODUCT_REENTRY_GATE],
        )

        self.assertEqual([], failures)

    def test_product_reentry_gate_rejects_acceptance_criteria_without_prd(self) -> None:
        failures = validate_gate_evidence(
            {
                PRODUCT_REENTRY_GATE: (
                    "proposed an implementation roadmap with acceptance criteria for "
                    "each milestone"
                )
            },
            [PRODUCT_REENTRY_GATE],
        )

        self.assertTrue(any("PRD coverage" in failure for failure in failures))

    def test_product_reentry_gate_rejects_ard_link_without_prd(self) -> None:
        failures = validate_gate_evidence(
            {
                PRODUCT_REENTRY_GATE: (
                    "proposed an implementation roadmap with an ARD link for module "
                    "boundaries"
                )
            },
            [PRODUCT_REENTRY_GATE],
        )

        self.assertTrue(any("PRD coverage" in failure for failure in failures))

    def test_missing_source_docs_requires_artifact_creation_or_no_durable_reason(self) -> None:
        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "searched PRD/spec/ARD source-of-truth docs; none found; "
                    "applied takeaway: used the user request as source of truth"
                ),
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: module README; "
                    "not applicable because new module changed behavior"
                ),
            },
            [SOURCE_DOCS_GATE, DOCUMENTATION_IMPACT_GATE],
        )

        self.assertTrue(any("when source docs are missing" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "searched PRD/spec/ARD source-of-truth docs; none found; "
                    "applied takeaway: used the user request as source of truth"
                ),
                DOCUMENTATION_IMPACT_GATE: (
                    "before code documentation impact decision: artifact: module README; "
                    "create docs/module/README.md because new module behavior changed"
                ),
            },
            [SOURCE_DOCS_GATE, DOCUMENTATION_IMPACT_GATE],
        )

        self.assertEqual([], failures)

    def test_source_docs_gate_accepts_a_bound_empty_required_manifest(self) -> None:
        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "before implementation verified route required_docs manifest empty; "
                    "searched PRD/spec/ARD source-of-truth docs; none found; "
                    "applied takeaway: used the user request as source of truth"
                )
            },
            [SOURCE_DOCS_GATE],
        )

        self.assertEqual([], failures)

    def test_source_docs_empty_manifest_claim_cannot_bypass_route_required_docs(self) -> None:
        route = {
            "command": "workflow-setup",
            "required_docs": ["AGENTS.md", "common/skills/agent-operating-skill/SKILL.md"],
            "gates": [SOURCE_DOCS_GATE],
        }
        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "before implementation verified route required_docs manifest empty; "
                    "searched source-of-truth docs; none found; "
                    "applied takeaway: use the current route"
                )
            },
            [SOURCE_DOCS_GATE],
            route=route,
        )

        self.assertTrue(any("claims the required_docs manifest is empty" in failure for failure in failures))

    def test_source_docs_korean_nonzero_count_is_not_an_empty_manifest_claim(self) -> None:
        route = {
            "command": "commit",
            "required_docs": ["AGENTS.md"],
            "gates": [SOURCE_DOCS_GATE],
        }
        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "AGENTS.md; searched source-of-truth docs before implementation; "
                    "필수 문서 20개를 읽고 applied takeaway: use the current route"
                )
            },
            [SOURCE_DOCS_GATE],
            route=route,
        )

        self.assertEqual([], failures)

    def test_source_docs_route_validation_requires_the_actual_manifest_entries(self) -> None:
        route = {
            "command": "workflow-setup",
            "required_docs": ["AGENTS.md", "common/skills/agent-operating-skill/SKILL.md"],
            "gates": [SOURCE_DOCS_GATE],
        }
        failures = validate_gate_evidence(
            {
                SOURCE_DOCS_GATE: (
                    "read every route required_docs entry directly before implementation; "
                    "AGENTS.md; searched source-of-truth docs; none found; "
                    "applied takeaway: use the current route"
                )
            },
            [SOURCE_DOCS_GATE],
            route=route,
        )

        self.assertTrue(any("missing:" in failure for failure in failures))

    def test_retrospective_check_accepts_no_reusable_gap(self) -> None:
        failures = validate_gate_evidence(
            {
                RETROSPECTIVE_CHECK_GATE: (
                    "retrospective check; skills checked: retrospective-learning; "
                    "outcome: no_reusable_gap; observation: not_needed"
                )
            },
            [RETROSPECTIVE_CHECK_GATE],
        )

        self.assertEqual([], failures)

    def test_retrospective_check_accepts_recorded_gap(self) -> None:
        for observation in ("recorded",):
            with self.subTest(observation=observation):
                failures = validate_gate_evidence(
                    {
                        RETROSPECTIVE_CHECK_GATE: (
                            "retrospective check; skills checked: human-authored-writing; "
                            f"outcome: reusable_gap; observation: {observation}"
                        )
                    },
                    [RETROSPECTIVE_CHECK_GATE],
                )

                self.assertEqual([], failures)

    def test_retrospective_check_rejects_unrecorded_gap(self) -> None:
        failures = validate_gate_evidence(
            {
                RETROSPECTIVE_CHECK_GATE: (
                    "retrospective check; skills checked: human-authored-writing; "
                    "outcome: reusable_gap; observation: not_needed"
                )
            },
            [RETROSPECTIVE_CHECK_GATE],
        )

        self.assertTrue(any("must record one skill observation" in failure for failure in failures))

    def test_retrospective_structured_fields_synthesize_valid_evidence(self) -> None:
        evidence, missing = synthesize_gate_evidence(
            RETROSPECTIVE_CHECK_GATE,
            "",
            {
                "skills_checked": "retrospective-learning",
                "outcome": "no_reusable_gap",
                "observation": "not_needed",
            },
        )

        self.assertEqual([], missing)
        self.assertEqual(
            [],
            validate_gate_evidence(
                {RETROSPECTIVE_CHECK_GATE: evidence},
                [RETROSPECTIVE_CHECK_GATE],
            ),
        )


class RefusalNamesAcceptedWordingTests(unittest.TestCase):
    """A refusal that hides the wording it wants forces a source dive.

    These gates pass or fail on substring match, so an agent whose truthful
    sentence the matcher did not recognise had nowhere to look but the validator
    source -- once per refusal, every time. Each message now carries the phrases
    that decide it, and it reads them from the same constant the check uses so the
    advertised wording cannot drift from the enforced wording.
    """

    def test_skip_refusal_names_the_wording_it_tripped_on(self) -> None:
        from agent_finish_gate_skip_policy import (
            _SKIP_PHRASES,
            validate_required_gate_not_skipped,
        )

        failures = validate_required_gate_not_skipped("tests", "검증 미실행", set())
        self.assertTrue(failures)
        joined = " ".join(failures)
        # The phrase that fired, not the first few candidates: this one sits last
        # in the list, so a truncated listing would have shown none of the reason.
        self.assertIn("미실행", joined)
        self.assertIn("미실행", _SKIP_PHRASES)

    def test_unresolved_refusal_names_the_wording_that_clears_it(self) -> None:
        from agent_finish_gate_skip_policy import (
            _RESOLVED_PHRASES,
            validate_required_gate_not_skipped,
        )

        failures = validate_required_gate_not_skipped("handoff", "must fix later", set())
        self.assertTrue(failures)
        self.assertIn(_RESOLVED_PHRASES[0], " ".join(failures))

    def test_tests_refusal_names_an_accepted_signal(self) -> None:
        from agent_finish_gate_doc_test_validators import (
            TEST_SIGNAL_PHRASES,
            validate_tests,
        )

        failures = validate_tests("결과만 기록했다")
        self.assertTrue(failures)
        self.assertIn(TEST_SIGNAL_PHRASES[0], failures[0])

    def test_alignment_brief_refusal_names_the_missing_parts(self) -> None:
        from agent_finish_gate_core_validators import validate_alignment_brief

        failures = validate_alignment_brief("Shared understanding: 원인은 라우팅 표다")
        self.assertTrue(failures)
        # Naming which of the four is absent is the only thing a rewrite needs.
        self.assertIn("Missing:", failures[0])
        self.assertIn("possible differences", failures[0])
        self.assertNotIn("Missing: shared understanding", failures[0])

    def test_a_satisfied_gate_still_passes_silently(self) -> None:
        from agent_finish_gate_doc_test_validators import validate_tests

        self.assertEqual([], validate_tests("unittest 1153건 통과"))

    def test_a_pass_word_without_a_result_or_a_command_is_refused(self) -> None:
        """A pass claim must be falsifiable by the person reading it.

        Accepting "tests passed" is how a finish gate reported SUCCESS for work
        whose suite was never run: the wording is identical either way.
        """

        from agent_finish_gate_doc_test_validators import validate_tests

        for unfalsifiable in ("tests passed", "unit tests green", "unit test result: pass"):
            with self.subTest(unfalsifiable):
                failures = validate_tests(unfalsifiable)
                self.assertTrue(failures, unfalsifiable)
                self.assertIn("not falsifiable", failures[0])

        # Either half of the requirement clears it on its own: a produced result,
        # or the command a reader can rerun.
        for falsifiable in (
            "tests: 0 failures",
            "1163 tests ok",
            "unittest discover -s tests passed",
            "./gradlew testDebugUnitTest 통과",
            "regression tests -> exit 0",
        ):
            with self.subTest(falsifiable):
                self.assertEqual([], validate_tests(falsifiable), falsifiable)

    def test_an_approved_skip_owes_no_result(self) -> None:
        from agent_finish_gate_doc_test_validators import validate_tests

        self.assertEqual(
            [], validate_tests("tests not run because docs-only change has no useful test")
        )
        self.assertEqual([], validate_tests("not applicable: no behavior change"))


if __name__ == "__main__":
    unittest.main()
