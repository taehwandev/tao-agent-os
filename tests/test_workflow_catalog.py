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
from workflow_doc_resolution import resolve_guidance_docs
from workflow_route import CORE_REQUIRED_DOCS
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
    RETROSPECTIVE_CHECK_COMMANDS,
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
    _threshold_followup_contradictions,
    markdown_files_to_validate,
    removed_cli_option_failures,
    validate_route_contracts,
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
def required_doc(path: str) -> str:
    """The document a route actually requires for a guidance area.

    Thin `SKILL.md` entrypoints resolve to `references/current-guidance.md`,
    which is where the rules live; entrypoints with content of their own, and
    skills with no reference, stay as they are. Core docs are exempt from
    resolution in the router, so they are exempt here too.
    """
    canonical = canonical_doc_path(path)
    if canonical in {canonical_doc_path(doc) for doc in CORE_REQUIRED_DOCS}:
        return canonical
    return resolve_guidance_docs(ROOT, [canonical])[-1]


def guidance_area(path: str) -> str:
    """The skill bundle a document belongs to, entrypoint or reference alike."""
    canonical = canonical_doc_path(path)
    for suffix in ("/references/current-guidance.md", "/SKILL.md"):
        if canonical.endswith(suffix):
            return canonical[: -len(suffix)]
    return canonical


def routed_areas(route: dict) -> set[str]:
    """Guidance areas the route puts in front of the agent, required or not.

    Required-doc membership is budget-bounded, so a surface match that fires
    may leave its lower-ranked areas in `reference_docs` rather than
    `required_docs`. Both are routed; only the first is mandatory reading.
    """
    return {
        guidance_area(doc)
        for doc in [*route["required_docs"], *route["reference_docs"]]
    }


class WorkflowCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_required_hook_commands_use_stable_launcher(self) -> None:
        hooks = route_hooks("task")
        commands = {hook["hook"]: hook["command"] for hook in hooks}
        for name in ("start", "review", "finish"):
            self.assertIn(str(stable_launcher_path()), commands[name])
            self.assertNotIn("scripts/agent-hook.py", commands[name])
            self.assertIn("--rules <TAO_ROOT>", commands[name])
            self.assertIn("--evidence <RUN_EVIDENCE>", commands[name])

    def test_read_only_routes_skip_mutation_only_preflight_gates(self) -> None:
        analysis_start = next(
            hook["command"] for hook in route_hooks("analysis") if hook["hook"] == "start"
        )
        task_start = next(
            hook["command"] for hook in route_hooks("task") if hook["hook"] == "start"
        )

        self.assertIn("--read-only", analysis_start)
        self.assertNotIn("--read-only", task_start)

    def test_testing_concern_is_registered(self) -> None:
        self.assertIn("testing", CONCERNS)
        self.assertIn("common/skills/testing/SKILL.md", CONCERNS["testing"])
        self.assertIn("common/skills/scenario-driven-testing/SKILL.md", CONCERNS["testing"])
        self.assertIn("common/skills/verification-policy/SKILL.md", CONCERNS["testing"])
        self.assertIn("definition-of-done", CONCERNS)
        self.assertIn("common/skills/definition-of-done/SKILL.md", CONCERNS["definition-of-done"])

    def test_workflow_validate_ignores_generated_markdown_caches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            agent_cache_dir = root / ".tao" / "skills" / "graphify"
            cache_dir = root / ".pytest_cache"
            graphify_dir = root / "graphify-out"
            docs_dir.mkdir()
            agent_cache_dir.mkdir(parents=True)
            cache_dir.mkdir()
            graphify_dir.mkdir()
            valid_doc = docs_dir / "guide.md"
            valid_doc.write_text(
                "---\nkeyflow_id: test\nstatus: stable\ntype: human-reviewed\n---\n# Guide\n",
                encoding="utf-8",
            )
            (agent_cache_dir / "SKILL.md").write_text("# Local skill cache\n", encoding="utf-8")
            (cache_dir / "README.md").write_text("# Cache\n", encoding="utf-8")
            (graphify_dir / "GRAPH_REPORT.md").write_text("# Generated graph report\n", encoding="utf-8")

            self.assertEqual([valid_doc], markdown_files_to_validate(root))

    def test_workflow_validate_accepts_skill_draft_route_hook(self) -> None:
        self.assertEqual([], validate_route_contracts())

    def test_lifecycle_alias_commands_are_registered(self) -> None:
        for command in ("analysis", "spec", "plan", "build", "test", "webperf", "code-simplify", "ship"):
            with self.subTest(command=command):
                self.assertIn(command, COMMANDS)
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn("request intake", route["gates"])
                if command == "analysis":
                    self.assertEqual(["AGENTS.md"], route["required_docs"])
                else:
                    self.assertTrue(route["required_docs"])

        self.assertIn(route_doc("common/skills/incremental-implementation/SKILL.md"), resolve_docs("build", None, [], request_classified=True)["docs"])
        self.assertIn(route_doc("common/skills/performance-verification/SKILL.md"), resolve_docs("webperf", None, [], request_classified=True)["docs"])
        self.assertIn(route_doc("common/skills/web-performance-verification/SKILL.md"), resolve_docs("webperf", None, [], request_classified=True)["docs"])
        self.assertIn(route_doc("common/skills/ci-cd-automation/SKILL.md"), resolve_docs("ship", None, [], request_classified=True)["docs"])

        test_route = resolve_docs("test", None, [], request_classified=True)
        self.assertIn(route_doc("common/skills/scenario-driven-testing/SKILL.md"), test_route["docs"])

        webperf_route = resolve_docs("webperf", None, [], request_classified=True)
        self.assertLess(webperf_route["gates"].index(ALIGNMENT_BRIEF_GATE), webperf_route["gates"].index("baseline"))

        spec_route = resolve_docs("spec", None, [], request_classified=True)
        self.assertTrue(spec_route["required_docs"])

    def test_analysis_route_stays_lightweight(self) -> None:
        route = resolve_docs("analysis", None, [], request_classified=True)

        self.assertEqual(
            ["request intake", "investigate", RETROSPECTIVE_CHECK_GATE, "report"],
            route["gates"],
        )
        self.assertEqual(["AGENTS.md"], route["required_docs"])
        parallel = route["parallel_execution"]
        self.assertEqual("serial_lightweight_analysis", parallel["strategy"])
        self.assertEqual(0, parallel["delegation_policy"]["maximum_workers"])
        self.assertTrue(all(phase["mode"] == "serial" for phase in parallel["phases"]))
        self.assertEqual([], validate_parallel_execution_plan(parallel, route["gates"]))
        self.assertFalse(next(hook for hook in route["hooks"] if hook["hook"] == "review")["required"])
        for excluded_gate in (
            SOURCE_DOCS_GATE,
            DOCUMENTATION_IMPACT_GATE,
            DOCUMENTATION_GATE,
            TEST_GATE,
            CYCLE_CONTRACT_GATE,
            BOUNDARY_PLAN_GATE,
            MULTI_AGENT_GATE,
            SIDE_EFFECT_AUDIT_GATE,
            "review hook",
        ):
            with self.subTest(excluded_gate=excluded_gate):
                self.assertNotIn(excluded_gate, route["gates"])

    def test_agent_skills_gap_concerns_are_registered(self) -> None:
        expected = {
            "skill-card": "common/skills/agent-skill-card-anatomy/SKILL.md",
            "source-driven": "common/skills/source-driven-development/SKILL.md",
            "doubt-driven": "common/skills/doubt-driven-development/SKILL.md",
            "incremental": "common/skills/incremental-implementation/SKILL.md",
            "deprecation": "common/skills/deprecation-migration/SKILL.md",
            "ci": "common/skills/ci-cd-automation/SKILL.md",
            "webperf": "common/skills/performance-verification/SKILL.md",
            "browser-testing": "common/skills/browser-runtime-testing/SKILL.md",
            "wiki": "common/skills/llm-wiki-documentation/SKILL.md",
            "commit": "common/skills/commit-workflow/SKILL.md",
            "branch": "common/skills/branch-strategy/SKILL.md",
            "push": "common/skills/commit-workflow/SKILL.md",
            "pull-request": "common/skills/branch-strategy/SKILL.md",
            "tag": "common/skills/release-deployment/SKILL.md",
        }

        for concern, doc in expected.items():
            with self.subTest(concern=concern):
                self.assertIn(concern, CONCERNS)
                self.assertIn(doc, CONCERNS[concern])

    def test_web_service_rn_python_concerns_and_platforms_route(self) -> None:
        expected = {
            "web-service-stack": "common/skills/web-service-rn-python/SKILL.md",
            "react-native": "platforms/react-native/skills/react-native-app/SKILL.md",
            "python-web-service": "platforms/python/skills/python-web-service/SKILL.md",
        }

        for concern, doc in expected.items():
            with self.subTest(concern=concern):
                self.assertIn(concern, CONCERNS)
                self.assertIn(doc, CONCERNS[concern])

        inferred = infer_concerns_from_request("크리스밴 스킬처럼 활용해서 rn react python 스킬 추가해줘")
        self.assertIn("web-service-stack", inferred)
        self.assertIn("react-native", inferred)
        self.assertIn("python-web-service", inferred)

        route_cases = (
            ("react-native", "platforms/react-native/skills/react-native-app/SKILL.md"),
            ("python", "platforms/python/skills/python-web-service/SKILL.md"),
            ("web-service", "common/skills/web-service-rn-python/SKILL.md"),
        )
        for platform, doc in route_cases:
            with self.subTest(platform=platform):
                route = resolve_docs("feature", platform, [], request_classified=True)
                self.assertIn(route_doc(doc), route["docs"])
                self.assertEqual([], route["missing"])

    def test_strict_card_required_headings_cover_anti_rationalization(self) -> None:
        self.assertIn("## Common Rationalizations", STRICT_CARD_REQUIRED_HEADINGS)
        self.assertIn("## Red Flags", STRICT_CARD_REQUIRED_HEADINGS)
        self.assertIn("## Verification", STRICT_CARD_REQUIRED_HEADINGS)

    def test_metering_concern_is_registered_separately_from_design_tokens(self) -> None:
        self.assertIn("metering", CONCERNS)
        self.assertIn("usage", CONCERNS)
        self.assertIn("common/skills/local-tools/SKILL.md", CONCERNS["metering"])
        self.assertIn("docs/skills/agent-runtime-integration/SKILL.md", CONCERNS["local-tools"])
        self.assertIn("common/skills/local-tools/SKILL.md", CONCERNS["usage"])
        self.assertIn("common/skills/design-system/SKILL.md", CONCERNS["tokens"])
        self.assertNotIn("common/skills/local-tools/SKILL.md", CONCERNS["tokens"])

    def test_web_deployment_versioning_routes_with_release_and_shipping(self) -> None:
        doc = "common/skills/web-deployment-versioning/SKILL.md"

        self.assertIn(doc, CONCERNS["release"])
        self.assertIn(doc, CONCERNS["shipping"])
        self.assertIn("workflows/skills/release-readiness/SKILL.md", CONCERNS["release"])
        self.assertIn(route_doc(doc), resolve_docs("docs", "web", ["release"], request_classified=True)["docs"])
        self.assertIn(route_doc(doc), resolve_docs("ship", "web", ["shipping"], request_classified=True)["docs"])

        examples = (
            "Define web deployment versioning for every main merge",
            "Should web deploys bump SemVer or use deployment ids?",
            "웹 배포 버전 체계를 정리해줘",
        )
        for request in examples:
            with self.subTest(request=request):
                self.assertIn("release", infer_concerns_from_request(request))

    def test_release_route_requires_versioning_skill_doc(self) -> None:
        route = resolve_docs("release", None, [], request_classified=True)

        self.assertIn(required_doc("workflows/skills/release-readiness/SKILL.md"), route["required_docs"])
        self.assertIn(required_doc("common/skills/release-deployment/SKILL.md"), route["required_docs"])
        self.assertIn(required_doc("common/skills/release-versioning/SKILL.md"), route["required_docs"])
        self.assertNotIn(required_doc("common/skills/release-versioning/SKILL.md"), route["reference_docs"])

    def test_tag_concern_requires_release_and_git_safety_skill_docs(self) -> None:
        expected_docs = (
            "common/skills/commit-workflow/SKILL.md",
            "common/skills/worktree-hygiene/SKILL.md",
            "workflows/skills/release-readiness/SKILL.md",
            "common/skills/release-deployment/SKILL.md",
            "common/skills/release-versioning/SKILL.md",
        )

        for doc in expected_docs:
            with self.subTest(doc=doc):
                self.assertIn(doc, CONCERNS["tag"])

        route = resolve_docs("release", None, ["tag"], request_classified=True)
        for doc in expected_docs:
            with self.subTest(required_doc=doc):
                self.assertIn(required_doc(doc), route["required_docs"])

    def test_release_versioning_forbids_four_digit_year_calver_tags(self) -> None:
        guidance = (ROOT / "common/skills/release-versioning/references/current-guidance.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("weekly CalVer `YY.WW.N`", guidance)
        self.assertIn("four-digit years", guidance)
        self.assertIn("2026.27.1", guidance)
        self.assertIn("starts at `1`", guidance)

    def test_credential_broker_concern_routes_to_product_pattern(self) -> None:
        doc = "product-patterns/skills/agent-credential-broker-ideation/SKILL.md"
        for concern in (
            "credential-broker",
            "agent-credentials",
            "brokered-credentials",
            "capability-token",
            "egress-control",
        ):
            with self.subTest(concern=concern):
                self.assertIn(concern, CONCERNS)
                self.assertIn(doc, CONCERNS[concern])

        examples = (
            "Compare credential broker patterns for an AI coding agent",
            "Design brokered credentials and capability token access for agents",
            "에이전트 자격 증명 브로커 아이디에이션을 정리해줘",
        )
        for request in examples:
            with self.subTest(request=request):
                self.assertIn("credential-broker", infer_concerns_from_request(request))

        route = resolve_docs("planning", None, ["credential-broker"], request_classified=True)
        self.assertIn(route_doc(doc), route["docs"])

    def test_number_unit_display_concerns_route_to_accessibility_i18n(self) -> None:
        for concern in (
            "i18n",
            "localization",
            "number-format",
            "number",
            "numbers",
            "numeric",
            "unit",
            "units",
            "measurement",
            "measurements",
            "currency",
            "display-value",
            "display-values",
        ):
            with self.subTest(concern=concern):
                self.assertIn(concern, CONCERNS)
                self.assertIn("common/skills/accessibility-i18n/SKILL.md", CONCERNS[concern])

        examples = (
            "Fix visible number and unit display in metric cards",
            "Format storage size units and duration labels",
            "숫자 표기와 단위를 화면 표시 기준으로 처리해줘",
        )

        for request in examples:
            with self.subTest(request=request):
                concerns = infer_concerns_from_request(request)
                self.assertIn("accessibility", concerns)

        route = resolve_docs("docs", None, ["units"], request_classified=True)
        self.assertIn(route_doc("common/skills/accessibility-i18n/SKILL.md"), route["docs"])

    def test_workflow_validate_rejects_removed_gate_option_in_markdown(self) -> None:
        self.assertEqual(
            ["guide.md:2: removed CLI option --gate; use gate or gate-batch"],
            removed_cli_option_failures(
                Path("guide.md"),
                "finish is read-only\nfinish --gate report=done\n",
            ),
        )
        self.assertEqual(
            [],
            removed_cli_option_failures(
                Path("guide.md"),
                "gate-batch --gate-record '{...}'\ngate --gate-name report\n",
            ),
        )

    def test_code_route_gets_automatic_gates_and_docs(self) -> None:
        route = resolve_docs("feature", None, ["testing"], request_classified=True)

        for gate in (
            SOURCE_DOCS_GATE,
            AMBIGUITY_GATE,
            DOCUMENTATION_IMPACT_GATE,
            DOCUMENTATION_GATE,
            TEST_GATE,
            CYCLE_CONTRACT_GATE,
            BOUNDARY_PLAN_GATE,
            MULTI_AGENT_GATE,
            AGENTIC_RUN_STATE_GATE,
            SIDE_EFFECT_AUDIT_GATE,
            RETROSPECTIVE_CHECK_GATE,
        ):
            self.assertIn(gate, route["gates"])

        self.assertIn(route_doc("workflows/skills/ambiguity-gate/SKILL.md"), route["docs"])
        self.assertIn(route_doc("workflows/skills/documentation-update/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/product-spec-to-implementation/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/source-driven-development/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/testing/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/scenario-driven-testing/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/verification-policy/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/code-structure-ownership/SKILL.md"), route["docs"])
        self.assertIn(route_doc("workflows/skills/cycle-contract/SKILL.md"), route["docs"])
        self.assertIn(route_doc("workflows/skills/multi-agent-collaboration/SKILL.md"), route["docs"])
        self.assertIn(route_doc("workflows/skills/development-cycle/SKILL.md"), route["docs"])
        self.assertIn(route_doc("workflows/skills/retrospective-learning/SKILL.md"), route["docs"])
        self.assertEqual(1, route["repair_cycle_limit"])
        self.assertEqual("retrospective_repair_verify_resume", route["repair_policy"])
        self.assertEqual("first_failed_checkpoint", route["resume_scope"])
        self.assertEqual("same_failure_after_repair_or_unsafe_repair", route["stop_condition"])
        for legacy_field in ("attempt_limit", "retry_limit", "retry_scope"):
            self.assertNotIn(legacy_field, route)
        self.assertIn(guidance_area("common/skills/code-conventions/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/llm-coding-discipline/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/agent-editing-safety/SKILL.md"), routed_areas(route))
        self.assertIn(required_doc("common/skills/testing/SKILL.md"), route["required_docs"])
        self.assertIn(route_doc("workflows/skills/ambiguity-gate/SKILL.md"), route["reference_docs"])
        self.assertIn(route_doc("workflows/skills/cycle-contract/SKILL.md"), route["reference_docs"])
        self.assertIn(route_doc("workflows/skills/product-architecture-delivery/SKILL.md"), route["reference_docs"])
        self.assertNotIn(required_doc("workflows/skills/product-architecture-delivery/SKILL.md"), route["required_docs"])
        self.assertLess(route["gates"].index(SOURCE_DOCS_GATE), route["gates"].index(AMBIGUITY_GATE))
        self.assertLess(route["gates"].index(SOURCE_DOCS_GATE), route["gates"].index(DOCUMENTATION_IMPACT_GATE))
        self.assertLess(route["gates"].index(DOCUMENTATION_IMPACT_GATE), route["gates"].index("implementation"))
        self.assertLess(route["gates"].index(SOURCE_DOCS_GATE), route["gates"].index("implementation"))
        self.assertLess(route["gates"].index(AGENTIC_RUN_STATE_GATE), route["gates"].index("implementation"))
        self.assertLess(route["gates"].index(CYCLE_CONTRACT_GATE), route["gates"].index("implementation"))
        self.assertLess(route["gates"].index(AGENTIC_RUN_STATE_GATE), route["gates"].index(CYCLE_CONTRACT_GATE))
        self.assertEqual(set(COMMANDS), RETROSPECTIVE_CHECK_COMMANDS)
        self.assertIn(RETROSPECTIVE_CHECK_GATE, route["gates"])
        self.assertLess(route["gates"].index("review hook"), route["gates"].index(RETROSPECTIVE_CHECK_GATE))
        self.assertLess(route["gates"].index(RETROSPECTIVE_CHECK_GATE), route["gates"].index("handoff"))
        self.assertTrue(route["skill_feedback"]["enabled"])
        self.assertTrue(route["skill_feedback"]["evaluation_required"])
        self.assertEqual(RETROSPECTIVE_CHECK_GATE, route["skill_feedback"]["evaluation_gate"])
        self.assertTrue(route["skill_feedback"]["blocking"])
        self.assertTrue(route["skill_feedback"]["threshold_followup_required"])
        feedback_hooks = [hook for hook in route["hooks"] if hook["hook"] == SKILL_FEEDBACK_HOOK]
        self.assertEqual(1, len(feedback_hooks))
        self.assertFalse(feedback_hooks[0]["required"])
        hook_names = [hook["hook"] for hook in route["hooks"]]
        self.assertLess(hook_names.index(SKILL_FEEDBACK_HOOK), hook_names.index("finish"))

    def _contradictions(
        self, constraint: str, *, required: bool = True, field: str = "constraints"
    ) -> list[str]:
        return _threshold_followup_contradictions(
            "task",
            {"parallel_execution": {"phases": [{"id": "closeout", field: [constraint]}]}},
            {"threshold_followup_required": required},
        )

    def test_a_blanket_non_blocking_claim_contradicts_the_threshold_contract(self) -> None:
        """The boolean alone let the route keep printing the opposite instruction."""

        failures = self._contradictions("skill review must not change finish status")

        self.assertEqual(1, len(failures))
        self.assertIn("closeout", failures[0])

    def test_a_claim_scoped_to_a_first_observation_is_allowed(self) -> None:
        """Below the recurrence threshold the non-blocking claim is true."""

        self.assertEqual(
            [],
            self._contradictions("storing a first observation must not change finish status"),
        )

    def test_naming_the_threshold_does_not_excuse_an_at_threshold_claim(self) -> None:
        """Exempting any sentence containing "threshold" passed the exact opposite."""

        for constraint in (
            "at the threshold, skill review must not change finish status",
            "even once the recurrence threshold is reached, review must not change finish status",
            "skill maintenance never changes a successful finish, threshold or not",
        ):
            with self.subTest(constraint=constraint):
                self.assertNotEqual([], self._contradictions(constraint))

    def test_the_claim_is_caught_in_phase_tasks_and_in_notes(self) -> None:
        """Both render into the route as literally as a constraint does."""

        claim = "skill review must not change finish status"
        self.assertNotEqual([], self._contradictions(claim, field="tasks"))
        self.assertNotEqual(
            [],
            _threshold_followup_contradictions(
                "task",
                {"parallel_execution": {"phases": [], "notes": [claim]}},
                {"threshold_followup_required": True},
            ),
        )

    def test_routes_without_the_follow_up_contract_are_not_checked(self) -> None:
        self.assertEqual(
            [],
            self._contradictions("skill review must not change finish status", required=False),
        )

    def test_every_shipped_route_states_the_contract_consistently(self) -> None:
        for command in COMMANDS:
            route = resolve_docs(command, None, [], request_classified=True)
            with self.subTest(command=command):
                self.assertEqual(
                    [],
                    _threshold_followup_contradictions(
                        command, route, route.get("skill_feedback") or {}
                    ),
                )


class AutoRouteSentinelTests(unittest.TestCase):
    """The prompt hook cannot know the task, so it must be able to defer.

    A fixed command routed every request as triage, so the work-shaped routes
    never fired from a prompt: a deploy was asked for test and implementation
    evidence while nobody asked for smoke or rollback. `auto` classifies the
    prompt on stdin instead, and fails open to triage in every direction because
    a hook that runs on every prompt must never block a session from starting.
    """

    ROOT = Path(__file__).resolve().parents[1]

    def _route(self, stdin_text: str) -> str:
        completed = subprocess.run(
            [sys.executable, str(self.ROOT / "scripts" / "workflow.py"), "route", "auto", "--advisory"],
            input=stdin_text,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in completed.stdout.splitlines():
            if line.startswith("Command:"):
                return line.split(":", 1)[1].strip().strip("`")
        return ""

    def test_a_deploy_prompt_resolves_to_the_release_route(self) -> None:
        self.assertEqual("release", self._route('{"prompt": "테스터에게 앱 배포"}'))

    def test_every_unusable_payload_falls_back_to_triage(self) -> None:
        for payload in ("", "not json", "{}", '{"prompt": ""}', '[]'):
            with self.subTest(payload=payload):
                self.assertEqual("triage", self._route(payload))


if __name__ == "__main__":
    unittest.main()
