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


class WorkflowRequestRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_scenario_testing_requests_infer_testing_concern(self) -> None:
        examples = (
            "Write scenario-driven tests for the checkout user flow",
            "Add QA scenarios for UI success and failure states",
            "사용자 흐름과 예외 처리를 시나리오 테스트로 정리해줘",
        )

        for request in examples:
            with self.subTest(request=request):
                self.assertIn("testing", infer_concerns_from_request(request))

    def test_spill_request_infers_metering_concern(self) -> None:
        concerns = infer_concerns_from_request("Preserve Spill workflow label bridge data")

        self.assertIn("metering", concerns)

    def test_explicit_graphify_exclusion_does_not_infer_graphify_concern(self) -> None:
        excluded_requests = (
            "P2 구현에서 Graphify 실행은 제외한다.",
            "그래프 설치는 제외해줘.",
            "그래피는 지금 돌리면 안됨",
            "Do not run Graphify for this task.",
            "Graphify must not be run for this task.",
            "Proceed without using Graphify.",
        )

        for request in excluded_requests:
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

        self.assertIn(
            "graphify",
            infer_concerns_from_request("Run Graphify readiness checks for this project."),
        )

    def test_graphify_preservation_language_keeps_graphify_concern(self) -> None:
        preserved_requests = (
            "Update hook setup without breaking Graphify integration.",
            "Refactor this without changing Graphify behavior.",
            "Do not break Graphify integration.",
            "Graphify behavior must not change.",
            "Graphify 연동을 깨뜨리지 않고 훅을 수정해줘.",
        )

        for request in preserved_requests:
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_natural_code_cleanup_request_routes_to_code_simplify(self) -> None:
        classification = classify_request("코드 정리해줘")

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("code-simplify", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])

    def test_natural_change_review_request_routes_to_review(self) -> None:
        for request in ("변경사항 검토하고 확인해줘", "이 작업 검토하고 확인해줘"):
            with self.subTest(request=request):
                classification = classify_request(request)

                self.assertEqual("clear-scoped", classification["clarity"])
                self.assertEqual("review", classification["recommended_route"])
                self.assertFalse(classification["grill_me"])

    def test_risk_domain_word_does_not_turn_diff_review_into_product_work(self) -> None:
        classification = classify_request(
            "Review only the current APP-1234 Kotlin and Gradle code diff for "
            "notification permission flow correctness. Do not review documents, "
            "edit files, run Gradle, or perform git mutations."
        )

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("review", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])
        self.assertEqual("work", classification["response_mode"])

    def test_natural_language_doc_routing_request_routes_to_workflow_setup(self) -> None:
        classification = classify_request("훅은 보완이고 자연어 검색 가능한 문서 라우팅을 강화해줘")

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("workflow-setup", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])

    def test_classification_includes_runtime_neutral_model_selection(self) -> None:
        quick = classify_request("`scripts/workflow_request.py:10` 확인해줘")
        standard = classify_request("기획변경 때 문서 정리가 누락되는 걸 막아줘")
        deep = classify_request("프로필 설정 기능을 구현해줘")

        self.assertEqual("quick", quick["effort"])
        self.assertEqual("fast", quick["model_tier"])
        self.assertEqual("gpt-5.6-luna", quick["model_selection"]["codex"])

        self.assertEqual("standard", standard["effort"])
        self.assertEqual("balanced", standard["model_tier"])
        self.assertEqual("gpt-5.6-terra", standard["model_selection"]["codex"])

        self.assertEqual("deep", deep["effort"])
        self.assertEqual("frontier", deep["model_tier"])
        self.assertEqual("gpt-5.6-sol", deep["model_selection"]["codex"])
        self.assertEqual(
            "codex-only-or-runtime-equivalent",
            deep["model_selection"]["runtime_mapping"],
        )
        self.assertEqual("task-or-agent-boundary", deep["model_selection"]["switching_boundary"])
        self.assertIn(
            "Use Codex model ids only on Codex",
            deep["model_selection"]["runtime_policy"],
        )

    def test_classification_keeps_code_authoring_above_luna(self) -> None:
        classification = classify_request("Add a regression test for `scripts/workflow_dispatch.py:10`.")

        self.assertEqual("quick", classification["effort"])
        self.assertEqual("balanced", classification["model_tier"])
        self.assertEqual("gpt-5.6-terra", classification["model_selection"]["codex"])

    def test_agent_skills_gap_requests_infer_new_concerns(self) -> None:
        examples = (
            ("Add a definition of done checklist", "testing"),
            ("Review web performance and Core Web Vitals", "webperf"),
            ("Review Jetpack Compose recomposition performance", "compose"),
            ("Review Jetpack Compose recomposition performance", "performance"),
            ("Use official docs for this SDK change", "source-driven"),
            ("Run a doubt-driven assumption review", "doubt-driven"),
            ("Split this into vertical slices", "incremental"),
            ("Fix CI/CD automation", "ci"),
            ("Apply OpenWiki-style living wiki docs", "wiki"),
            ("Generate source-grounded documentation from this codebase", "wiki"),
            ("코드베이스 위키와 자동 문서 갱신 방식을 정리해줘", "wiki"),
            ("Create commit rules for feature branches and PRs", "commit"),
            ("Create commit rules for feature branches and PRs", "branch"),
            ("Use git username/work-unit/description for branch names", "branch"),
            ("브랜치 전략을 git username 작업단위 내용으로 정리", "branch"),
            ("Automate git push only after safety checks", "push"),
            ("Open a draft PR from the work branch", "pull-request"),
            ("Release by pushing a verified tag", "tag"),
            ("태그 따고 푸쉬해줘", "tag"),
            ("태그 따고 푸쉬해줘", "push"),
        )

        for request, concern in examples:
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_commit_request_uses_lightweight_commit_route(self) -> None:
        classification = classify_request("웹 코드 커밋 안한거 분리해서 커밋해줘")

        self.assertEqual("commit", classification["recommended_route"])
        self.assertEqual("quick", classification["effort"])
        self.assertFalse(classification["grill_me"])

        self.assertIn("commit", COMMANDS)
        self.assertIn("git_commit", COMMANDS)

        route = resolve_docs("git_commit", None, [], request_classified=True)

        self.assertEqual(
            ["source docs", "review hook", RETROSPECTIVE_CHECK_GATE, "commit readiness"],
            [gate for gate in route["gates"] if gate != "request intake"],
        )
        self.assertNotIn(AMBIGUITY_GATE, route["gates"])
        self.assertNotIn(ALIGNMENT_BRIEF_GATE, route["gates"])
        self.assertNotIn(CYCLE_CONTRACT_GATE, route["gates"])
        self.assertNotIn(BOUNDARY_PLAN_GATE, route["gates"])
        self.assertNotIn(MULTI_AGENT_GATE, route["gates"])
        self.assertIn(required_doc("workflows/skills/review-and-commit/SKILL.md"), route["required_docs"])
        self.assertIn(required_doc("common/skills/commit-workflow/SKILL.md"), route["required_docs"])
        # The review hook's evidence contract lives in the guaranteed
        # review-and-commit entrypoint (asserted above), which now carries the
        # labelled-evidence steps itself. The generic code-review card no longer
        # fits the bounded required selection and stays reachable as reference.
        self.assertIn(route_doc("common/skills/code-review/SKILL.md"), route["reference_docs"])
        self.assertIn(route_doc("common/skills/worktree-hygiene/SKILL.md"), route["reference_docs"])

    def test_commit_explicit_concern_still_escalates_required_docs(self) -> None:
        route = resolve_docs(
            "git_commit",
            None,
            ["testing"],
            request_classified=True,
            request_text="검증 위험까지 확인하고 커밋해줘",
            surface_paths=["scripts/agent_preflight_runtime.py"],
            project_root=ROOT,
        )

        self.assertIn(
            required_doc("common/skills/testing/SKILL.md"),
            route["required_docs"],
        )

    def test_branch_strategy_routes_for_branch_naming(self) -> None:
        concerns = infer_concerns_from_request(
            "Use git username/work-unit/description for branch names"
        )

        self.assertIn("branch", concerns)

        route = resolve_docs("docs", None, ["branch"], request_classified=True)

        self.assertIn(required_doc("common/skills/branch-strategy/SKILL.md"), route["required_docs"])
        self.assertIn(required_doc("common/skills/worktree-hygiene/SKILL.md"), route["required_docs"])

    def test_preflight_rejects_invalid_concern_like_workflow_route_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "bugfix",
                    "--concern",
                    "not-a-real-concern",
                    "--request-classified",
                    "--classification-evidence",
                    "clear-scoped actionable request: verify preflight parser validation",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)

    def test_git_commit_route_accepts_commit_classification_evidence(self) -> None:
        evidence = (
            "User asked to split all uncommitted web code into commits. "
            "Target repo is known and current task is local commit creation."
        )

        self.assertIsNone(classified_route_block_reason("git_commit", evidence))

    def test_git_commit_route_rejects_english_negated_or_reference_evidence(self) -> None:
        # Regression (Codex finding): only the Korean negation branch was
        # guarded; English negation/reference phrases still matched the bare
        # \bcommit\b pattern and were treated as commit approval.
        for evidence in (
            "User said do not commit yet, more review is needed.",
            "Team lead said never commit this directly to main.",
            "The user explained that commit is only a term here, no action requested.",
            "Plan is to review before committing anything.",
        ):
            with self.subTest(evidence=evidence):
                self.assertIsNotNone(classified_route_block_reason("git_commit", evidence))

    def test_finish_request_intake_uses_commit_evidence_policy(self) -> None:
        evidence = (
            "User asked to split all uncommitted web code into commits. "
            "Target repo is known and current task is local commit creation."
        )
        route = {
            "command": "git_commit",
            "request_classified": True,
        }
        failures: list[str] = []
        gate_signals: list[dict[str, str]] = []
        missed_gates: list[str] = []

        check_request_intake(
            route,
            {"request_classified": True, "classification_evidence": evidence},
            {},
            {},
            gate_signals,
            missed_gates,
            failures,
        )

        self.assertEqual([], failures)
        self.assertEqual([], missed_gates)

    def test_writing_requests_infer_human_authored_writing_concern(self) -> None:
        examples = (
            "Tao Agent OS 소개하는 글을 써줘. 바이브가드도 같이 소개해줘.",
            "블로그 글 써달라고 하면 공유 writing workspace에 초안을 저장하게 해줘.",
            "AI 티 덜 나게 문체를 다듬어줘.",
            "Write an article introducing Tao Agent OS and VibeGuard.",
            "Draft release notes with a less AI-sounding tone.",
        )

        for request in examples:
            with self.subTest(request=request):
                concerns = infer_concerns_from_request(request)
                self.assertIn("writing", concerns)

        route = resolve_docs("docs", None, ["writing"], request_classified=True)
        self.assertIn(route_doc("common/skills/human-authored-writing/SKILL.md"), route["docs"])
        self.assertIn(route_doc("common/skills/writing-workspace/SKILL.md"), route["docs"])

    def test_ambiguous_writing_style_rewrite_requires_triage(self) -> None:
        request = (
            "# Tao Agent OS: AI 에이전트의 작업 습관을 프로젝트 밖에 저장하기 "
            "이거 작성 다시하자. 나는 ~했다. 뭐뭐다. 이다. "
            "이런 투로 쓰는데 존대라서 이런건 어떻게 내 스타일로 쓰도록 가이드하지?"
        )

        classification = classify_request(request)

        self.assertIn("writing", infer_concerns_from_request(request))
        self.assertEqual("vague-action", classification["clarity"])
        self.assertTrue(classification["grill_me"])
        self.assertEqual("triage", classification["recommended_route"])
        self.assertEqual("clarify_first", classification["response_mode"])

    def test_scoped_korean_request_does_not_trip_distant_broad_keywords(self) -> None:
        classification = classify_request(
            "공식 AI 서버 상태를 메인 앱 단일 조회와 로컬 캐시 IPC로 동기화하고 "
            "클릭 팝오버에 상태별 다음 행동 안내를 추가해줘"
        )

        self.assertNotEqual("broad-product", classification["clarity"])
        self.assertFalse(classification["grill_me"])

    def test_underspecified_action_requires_self_judged_triage(self) -> None:
        classification = classify_request("프로필 저장하고 아바타 프리셋도 추가해줘")

        self.assertEqual("vague-action", classification["clarity"])
        self.assertEqual("triage", classification["recommended_route"])
        self.assertTrue(classification["grill_me"])
        self.assertEqual("clarify_first", classification["response_mode"])
        self.assertIn("lacks a precise target", classification["reason"])

    def test_inspection_request_is_not_blocked_like_product_work(self) -> None:
        classification = classify_request("문서 전체 상태 체크해줘")

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("task", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])
        self.assertEqual("work", classification["response_mode"])

    def test_follow_up_approval_inherits_confirmed_scope(self) -> None:
        for request in (
            "아하 그럼 그건 수정해줘야겠네",
            "Then apply the agreed change",
        ):
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("clear-scoped", classification["clarity"])
                self.assertEqual("task", classification["recommended_route"])
                self.assertFalse(classification["grill_me"])
                self.assertIsNone(route_block_reason("bugfix", classification))

    def test_bare_follow_up_without_scope_still_requires_triage(self) -> None:
        classification = classify_request("수정해줘")

        self.assertEqual("vague-action", classification["clarity"])
        self.assertEqual("triage", classification["recommended_route"])
        self.assertIsNotNone(route_block_reason("bugfix", classification))

    def test_planning_change_doc_omission_request_routes_to_workflow_setup(self) -> None:
        classification = classify_request("기획변경 때 문서 정리가 누락되는 걸 막아줘")

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("workflow-setup", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])
        self.assertEqual("work", classification["response_mode"])

    def test_commit_first_release_substep_uses_commit_route(self) -> None:
        classification = classify_request(
            "Commit the current Swift warning cleanup first before continuing the "
            "Spill macOS release sequence."
        )

        self.assertEqual("clear-scoped", classification["clarity"])
        self.assertEqual("commit", classification["recommended_route"])
        self.assertFalse(classification["grill_me"])
        self.assertEqual("work", classification["response_mode"])

    def test_targetless_inspection_request_requires_triage(self) -> None:
        for request in ("확인", "check", "review", "이거 확인해줘"):
            with self.subTest(request=request):
                classification = classify_request(request)

                self.assertEqual("vague-action", classification["clarity"])
                self.assertEqual("triage", classification["recommended_route"])
                self.assertTrue(classification["grill_me"])
                self.assertEqual("clarify_first", classification["response_mode"])

                blocked = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "workflow.py"),
                        "route",
                        "task",
                        "--request",
                        request,
                    ],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

                self.assertEqual(2, blocked.returncode)
                self.assertIn("needs clarification", blocked.stderr)


class GraphifyExclusionPhrasingTests(unittest.TestCase):
    """Opting out of Graphify must not depend on one exact verb.

    The exclusion patterns were anchored to run/use/invoke/call/install/enable,
    so "do not execute Graphify" still inferred the concern and pulled the whole
    Graphify surface into the route. Korean drops the verb entirely.
    """

    EXCLUSIONS = (
        "Do not execute Graphify for this task",
        "Do not run Graphify for this task",
        "Never execute graphify here",
        "Finish without executing graphify",
        "Don't include Graphify",
        "Don’t include Graphify",
        "Do not include graphify in this task",
        "Never include Graphify here",
        "Proceed without including Graphify",
        "Graphify should not be included",
        "Graphify 는 하지 마",
        "graphify 하지 않습니다",
        "그래프 는 제외",
    )

    def test_exclusion_phrasings_drop_the_graphify_concern(self) -> None:
        for request in self.EXCLUSIONS:
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_negated_include_regresses_the_old_action_verb_gap(self) -> None:
        """`include` was absent from the action verbs, so this kept Graphify."""

        self.assertNotIn(
            "graphify",
            infer_concerns_from_request("Don't include Graphify"),
        )

    def test_negative_control_ordinary_graphify_requests_still_infer_it(self) -> None:
        """The control: broadening the exclusion must not disable inference.

        If it did, a genuine Graphify request would silently lose its concern
        and the route would never load the Graphify surface at all.
        """

        for request in (
            "Run graphify and report the project graph",
            "Include Graphify in the routing review",
            "graphify 그래프를 갱신해줘",
            "Rebuild the knowledge graph with graphify update",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_double_negation_include_fix_does_not_invert_removal_verbs(self) -> None:
        for request in (
            "Do not exclude Graphify",
            "Don’t exclude Graphify",
            "Graphify 는 제외하지 마",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))


class GraphifyOptOutVerbTests(unittest.TestCase):
    """Opting out by removal verb, and the double negation that undoes it.

    "Skip Graphify" was not recognised at all, and "Graphify 는 제외하지 마"
    ("do NOT exclude Graphify") matched a bare-negation pattern and dropped the
    concern the user had just asked to keep.
    """

    OPT_OUTS = (
        "Skip Graphify for this task",
        "Omit graphify here",
        "Please exclude graphify",
        "Disable graphify for now",
        "Bypass graphify entirely",
        "Leave out graphify",
        "Leave graphify out of this",
        "Drop graphify from this run",
        "Graphify should be skipped",
        "그래피는 빼줘",
        "그래피 빼고 진행해줘",
        "그래피를 제외해줘",
        "지식 그래프는 생략해줘",
        "graphify 는 건너뛰어",
        "프로젝트 그래프는 무시해줘",
    )

    DOUBLE_NEGATIONS = (
        "Do not skip graphify",
        "Don't exclude graphify",
        "Never omit graphify",
        "do not disable graphify",
        "You should not bypass graphify",
        "Graphify 는 제외하지 마",
        "그래피는 빼지 마",
        "그래피 건너뛰지 마",
        "graphify 생략하지 말고 진행해",
        "지식 그래프는 무시하지 않는다",
    )

    def test_opt_out_verbs_drop_the_graphify_concern(self) -> None:
        for request in self.OPT_OUTS:
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_double_negation_keeps_the_graphify_concern(self) -> None:
        """Negating the opt-out verb asks for the opposite of the opt-out."""

        for request in self.DOUBLE_NEGATIONS:
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_negative_control_genuine_graphify_requests_still_infer_it(self) -> None:
        """The opposite direction: the broadened opt-out must not swallow work.

        Korean 그래프 is an ordinary word, so an over-broad opt-out pattern
        would strip the concern from requests that are asking for Graphify.
        """

        for request in (
            "Run graphify update on the repo",
            "graphify query 로 구조를 설명해줘",
            "graphify 그래프를 갱신해줘",
            "지식 그래프를 만들어줘",
            "Rebuild the knowledge graph with graphify update",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_unrelated_chart_sentence_is_unaffected(self) -> None:
        """A bare 그래프 mention is not a Graphify request either way."""

        self.assertEqual(
            infer_concerns_from_request("차트에서 그래프를 제외한 나머지를 보여줘"),
            [],
        )


class AttachedHangulParticleTests(unittest.TestCase):
    """Korean writes "Graphify는", not "Graphify 는".

    Python's \\b finds no boundary between a Latin letter and a Hangul particle
    because both are word characters, so the ordinary Korean spelling used to
    match no hint at all: "Graphify는 제외하지 마" inferred nothing, which looks
    to the user exactly like the inverted match — they asked to keep Graphify
    and lost it.
    """

    def test_attached_particle_opt_out_drops_the_concern(self) -> None:
        for request in (
            "Graphify는 빼줘",
            "Graphify는 제외해줘",
            "graphify는 생략",
            "Graphify는 하지 마",
            "graphify없이 진행해줘",
        ):
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_attached_particle_double_negation_keeps_the_concern(self) -> None:
        for request in (
            "Graphify는 제외하지 마",
            "Graphify는 빼지 말고 돌려줘",
            "graphify는 생략하지 마",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_attached_particle_request_infers_the_concern(self) -> None:
        """The control that fails if the junction fix is reverted.

        Without it the hint itself never fires, so the concern is absent no
        matter which direction the sentence argues.
        """

        self.assertIn("graphify", infer_concerns_from_request("Graphify는 어떻게 써?"))

    def test_other_latin_keyword_concerns_share_the_fix(self) -> None:
        """The blind spot was never graphify-specific: 228 hints are \\b-anchored."""

        for request, concern in (
            ("SwiftUI는 어떻게 쓰지", "swift"),
            ("CI는 어떻게 되어 있어", "ci"),
            ("PR을 만들어줘", "pull-request"),
            ("SEO를 개선하자", "seo"),
        ):
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_negative_control_latin_identifiers_do_not_match(self) -> None:
        """The junction split must not become a substring match.

        The space only lands between a complete Latin run and an attached
        Hangul syllable, so a longer identifier still has to fail the hint.
        """

        self.assertNotIn("graphify", infer_concerns_from_request("graphifyer를 고쳐줘"))
        self.assertNotIn(
            "graphify", infer_concerns_from_request("graphifyui는 무엇인가")
        )


if __name__ == "__main__":
    unittest.main()
