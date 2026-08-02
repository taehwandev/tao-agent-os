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
from agent_route_state import request_fingerprint
from workflow_dispatch import (
    build_dispatch_manifest as _build_dispatch_manifest,
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
from workflow import build_parser, print_dispatch as _print_dispatch, print_dispatch_finalize
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

_RUNTIME_SESSION_ID = "workflow-dispatch-test-session"


def _intent_cli_args(request: str, command: str) -> list[str]:
    requested_effect = "read" if command in {"analysis", "review", "plan", "planning"} else "local_write"
    envelope = {
        "schema_version": 1,
        "request_fingerprint": request_fingerprint({"request": request}),
        "runtime_session_id": _RUNTIME_SESSION_ID,
        "mode": "work",
        "intent": "dispatch",
        "target_summary": "the dispatch test target",
        "requested_effects": [requested_effect],
        "ambiguity": "resolved",
    }
    return [
        "--intent-envelope", json.dumps(envelope),
        "--runtime-session-id", _RUNTIME_SESSION_ID,
    ]


def _authorize_dispatch_args(args: argparse.Namespace) -> argparse.Namespace:
    request = str(args.request or "")
    intent_args = _intent_cli_args(request, args.command)
    args.intent_envelope = intent_args[1]
    args.runtime_session_id = _RUNTIME_SESSION_ID
    return args


def print_dispatch(args: argparse.Namespace) -> int:
    return _print_dispatch(_authorize_dispatch_args(args))


def build_dispatch_manifest(command, request, project, **kwargs):
    """Exercise dispatch internals after the envelope intake boundary.

    CLI tests below cover that boundary itself. These tests own profile,
    isolation, evidence and launch behavior, so they pass the already accepted
    classification that a real envelope supplies.
    """

    kwargs.setdefault(
        "request_classification",
        {
            "request": request,
            "clarity": "clear-scoped",
            "effort": "standard",
            "question_drill": False,
            "grill_me": False,
            "response_mode": "work",
            "recommended_route": "",
        },
    )
    return _build_dispatch_manifest(command, request, project, **kwargs)


def _init_git_repo(project: Path) -> None:
    """Create a real committed git repo so isolated dispatch can add a worktree."""

    project.mkdir(parents=True, exist_ok=True)
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    (project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("config", "user.email", "tests@example.invalid"),
        ("config", "user.name", "Tao Agent OS Tests"),
        ("add", "-A"),
        ("commit", "-qm", "initial"),
    ):
        subprocess.run(
            ["git", *args],
            cwd=project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


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


class WorkflowDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_dispatch_profiles_match_stage_policy(self) -> None:
        expected = {
            "prd_design": ("gpt-5.6-sol", "high"),
            "research": ("gpt-5.6-terra", "low"),
            "analysis": ("gpt-5.6-terra", "medium"),
            "implementation": ("gpt-5.6-terra", "medium"),
            "complex_implementation": ("gpt-5.6-sol", "high"),
            "repetitive": ("gpt-5.6-luna", "low"),
            "final_review": ("gpt-5.6-sol", "xhigh"),
        }

        for work_kind, (model, effort) in expected.items():
            with self.subTest(work_kind=work_kind):
                profile = profile_for_work_kind(work_kind)
                self.assertEqual(model, profile["codex_model"])
                self.assertEqual(effort, profile["reasoning_effort"])

    def test_dispatch_keeps_normal_implementation_on_terra_medium(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
        )

        profile = manifest["work_profile"]
        self.assertEqual("implementation", profile["work_kind"])
        self.assertEqual("gpt-5.6-terra", profile["codex_model"])
        self.assertEqual("medium", profile["reasoning_effort"])
        self.assertIn("--model", manifest["codex_exec_argv"])
        self.assertIn('model_reasoning_effort="medium"', manifest["codex_exec_argv"])
        self.assertEqual("workspace-write", manifest["sandbox_mode"])

    def test_dispatch_auto_selects_stage_profiles(self) -> None:
        cases = {
            "analysis": ("analysis", "medium"),
            "prd": ("prd_design", "high"),
            "plan": ("research", "low"),
            "task": ("analysis", "medium"),
            "feature": ("implementation", "medium"),
            "review": ("final_review", "xhigh"),
        }

        for command, (work_kind, effort) in cases.items():
            with self.subTest(command=command):
                manifest = build_dispatch_manifest(
                    command,
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    ROOT,
                )
                profile = manifest["work_profile"]
                self.assertEqual(work_kind, profile["work_kind"])
                self.assertEqual(effort, profile["reasoning_effort"])

    def test_dispatch_auto_promotes_deep_implementation_to_sol_high(self) -> None:
        work_kind, reason = select_work_kind("feature", {"effort": "deep"}, "auto")
        profile = profile_for_work_kind(work_kind)

        self.assertEqual("complex_implementation", profile["work_kind"])
        self.assertEqual("gpt-5.6-sol", profile["codex_model"])
        self.assertEqual("high", profile["reasoning_effort"])
        self.assertEqual("deep effort is explicit complexity evidence", reason)

    def test_dispatch_reserves_luna_for_quick_repetition(self) -> None:
        quick = {"effort": "quick"}

        self.assertEqual(
            ("repetitive", "quick non-authoring test route selects the read-only Luna profile"),
            select_work_kind("test", quick, "auto"),
        )
        self.assertEqual(
            ("implementation", "normal implementation defaults to Terra medium"),
            select_work_kind("feature", quick, "auto"),
        )

    def test_dispatch_keeps_code_authoring_tests_on_terra(self) -> None:
        manifest = build_dispatch_manifest(
            "test",
            "Add a regression test for `scripts/workflow_dispatch.py:10`.",
            ROOT,
        )

        self.assertEqual("implementation", manifest["work_profile"]["work_kind"])
        self.assertEqual("gpt-5.6-terra", manifest["work_profile"]["codex_model"])
        self.assertEqual("workspace-write", manifest["sandbox_mode"])

    def test_dispatch_makes_luna_repetition_read_only_and_non_authoring(self) -> None:
        manifest = build_dispatch_manifest(
            "test",
            "Run the focused tests for `scripts/workflow_dispatch.py:10`.",
            ROOT,
            request_classification={
                "request": "Run the focused tests for `scripts/workflow_dispatch.py:10`.",
                "clarity": "clear-scoped",
                "effort": "quick",
                "question_drill": False,
                "grill_me": False,
                "response_mode": "work",
                "recommended_route": "",
            },
        )

        self.assertEqual("repetitive", manifest["work_profile"]["work_kind"])
        self.assertEqual("gpt-5.6-luna", manifest["work_profile"]["codex_model"])
        self.assertEqual("read-only", manifest["sandbox_mode"])
        self.assertEqual("read-only non-authoring", manifest["authoring_policy"])
        self.assertIn("Do not modify files, write code, generate patches, or create tests.", manifest["codex_exec_argv"][-1])

    def test_dispatch_rejects_luna_for_explicit_code_authoring(self) -> None:
        with self.assertRaisesRegex(ValueError, "Luna cannot write or modify code"):
            select_work_kind(
                "feature",
                {"effort": "quick", "request": "Implement the requested code change."},
                "repetitive",
            )

    def test_dispatch_promotes_deep_work_to_sol_high(self) -> None:
        manifest = build_dispatch_manifest(
            "task",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
            work_kind="complex_implementation",
            complexity_evidence="local inspection confirmed cross-module migration and repeated verification failures",
        )

        profile = manifest["work_profile"]
        self.assertEqual("complex_implementation", profile["work_kind"])
        self.assertEqual("gpt-5.6-sol", profile["codex_model"])
        self.assertEqual("high", profile["reasoning_effort"])

    def test_dispatch_rejects_unexplained_complex_implementation(self) -> None:
        with self.assertRaisesRegex(ValueError, "Complex implementation requires"):
            build_dispatch_manifest(
                "task",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                ROOT,
                work_kind="complex_implementation",
            )

    def test_dispatch_cli_without_explicit_isolation_stays_inline(self) -> None:
        # Dispatch against a plan-free project: an active delegation plan now
        # fails closed without --worker-id, and this test only exercises the
        # unrelated inline-execution default.
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "workflow.py"),
                    "dispatch",
                    "task",
                    "--request",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    "--project",
                    temp_dir,
                    "--format",
                    "json",
                    *_intent_cli_args(
                        "기획변경 때 문서 정리가 누락되는 걸 막아줘", "task"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=ROOT,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual("gpt-5.6-terra", manifest["work_profile"]["codex_model"])
        self.assertEqual("medium", manifest["work_profile"]["reasoning_effort"])
        self.assertIn("Continue inline in the parent", manifest["execution_policy"])
        self.assertEqual("inline", manifest["execution_mode"])
        self.assertEqual([], manifest["codex_exec_argv"])

    def test_injected_runner_is_rejected_for_isolated_manifest(self) -> None:
        """An injected runner cannot honor worktree isolation, so it must fail
        closed rather than silently run in the shared checkout (Fix B). The guard
        also fires before any scheduler task is claimed."""

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                Path(temp_dir),
                isolation_required=True,
            )
            received: list[list[str]] = []

            def runner(argv: list[str]) -> int:
                received.append(argv)
                return 17

            with self.assertRaisesRegex(ValueError, "cannot honor worktree isolation"):
                execute_dispatch_manifest(manifest, runner=runner)
            self.assertEqual([], received)
            self.assertFalse((Path(temp_dir) / ".tao" / "scheduler.json").exists())

    def test_injected_runner_on_inline_manifest_keeps_inline_guard(self) -> None:
        """A non-isolated manifest is inline, so the injected runner still hits the
        pre-existing inline decision guard -- unchanged behavior (Fix B)."""

        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
            parent_model="gpt-5.6-terra",
            parent_reasoning_effort="medium",
            parent_sandbox_mode="workspace-write",
        )
        received: list[list[str]] = []
        self.assertEqual("inline", manifest["execution_mode"])
        with self.assertRaisesRegex(ValueError, "cannot execute work in the parent process"):
            execute_dispatch_manifest(manifest, runner=received.append)
        self.assertEqual([], received)

    @staticmethod
    def _git_only_fake_run():
        """Keep real ``git`` (worktree creation) but stub the codex worker launch.

        Isolated manifests can no longer be executed through an injected runner
        (Fix B), so these launch-time behaviors are exercised on the real
        subprocess path with only the codex process mocked.
        """

        real_run = subprocess.run

        def fake_run(command, *args, **kwargs):
            if command and command[0] == "git":
                return real_run(command, *args, **kwargs)
            return SimpleNamespace(returncode=0)

        return fake_run

    def test_dispatch_revalidates_capsule_and_mints_worker_token_at_launch(self) -> None:
        reusable = {
            "path": "/tmp/execution-capsule.json",
            "reusable": True,
            "invalidation_reasons": [],
            "phase": "ready",
        }
        stale = {
            "path": "/tmp/execution-capsule.json",
            "reusable": False,
            "invalidation_reasons": ["project worktree status changed"],
            "phase": "ready",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch("workflow_dispatch._execution_capsule_state", side_effect=[reusable, stale]):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch.subprocess.run",
                    side_effect=self._git_only_fake_run(),
                ) as launch:
                    self.assertEqual(0, execute_dispatch_manifest(manifest))

        prompt = launch.call_args.args[0][-1]
        self.assertIn("No reusable execution capsule is available", prompt)
        self.assertRegex(prompt, r"worker-reservation-token [0-9a-f]{32}")

    def test_dispatch_execute_defers_duplicate_capsule_hashing_until_launch(self) -> None:
        stale = {
            "path": "/tmp/execution-capsule.json",
            "reusable": False,
            "invalidation_reasons": ["project worktree status changed"],
            "phase": "ready",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch("workflow_dispatch._execution_capsule_state", return_value=stale) as state:
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    reserve_worker_evidence=True,
                    defer_capsule_validation=True,
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch.subprocess.run",
                    side_effect=self._git_only_fake_run(),
                ):
                    self.assertEqual(0, execute_dispatch_manifest(manifest))

        # Deferred at build, hashed exactly once at launch.
        self.assertEqual(1, state.call_count)

    def test_dispatch_launch_preserves_request_mismatch_for_capsule_reuse(self) -> None:
        calls: list[bool] = []

        def capsule_state(*_args, parent_context_reusable: bool) -> dict[str, object]:
            calls.append(parent_context_reusable)
            return {
                "path": "/tmp/execution-capsule.json",
                "reusable": parent_context_reusable,
                "invalidation_reasons": [] if parent_context_reusable else ["request mismatch"],
                "phase": "ready",
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch("workflow_dispatch._execution_capsule_state", side_effect=capsule_state):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    parent_context_reusable=False,
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch.subprocess.run",
                    side_effect=self._git_only_fake_run(),
                ) as launch:
                    self.assertEqual(0, execute_dispatch_manifest(manifest))

        self.assertEqual([False, False], calls)
        self.assertFalse(manifest["handoff_state"]["parent_context_reusable"])
        self.assertIn("No reusable execution capsule is available", launch.call_args.args[0][-1])

    def test_dispatch_launch_exports_only_worker_evidence_boundary(self) -> None:
        stale = {
            "path": "/tmp/execution-capsule.json",
            "reusable": False,
            "invalidation_reasons": ["stale"],
            "phase": "ready",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch("workflow_dispatch._execution_capsule_state", side_effect=[stale, stale]):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    isolation_required=True,
                )
                real_run = subprocess.run

                def fake_run(command, *args, **kwargs):
                    # ``subprocess`` is a shared module, so patching it here also
                    # intercepts the real worktree git calls. Keep git real and
                    # mock only the codex worker launch.
                    if command and command[0] == "git":
                        return real_run(command, *args, **kwargs)
                    return SimpleNamespace(returncode=0)

                with patch(
                    "workflow_dispatch_launch.subprocess.run",
                    side_effect=fake_run,
                ) as launch:
                    self.assertEqual(0, execute_dispatch_manifest(manifest))

        environment = launch.call_args.kwargs["env"]
        self.assertTrue(environment["TAO_WORKER_EVIDENCE"].endswith("preflight.json"))
        self.assertRegex(environment["TAO_WORKER_RESERVATION_TOKEN"], r"^[0-9a-f]{32}$")
        self.assertEqual("worker-evidence-and-state", environment["TAO_CAPABILITY_ENFORCEMENT"])
        self.assertNotIn("TAO_PARENT_EVIDENCE_READONLY", environment)
        # Isolation binds the worker to a real git worktree, not the shared checkout.
        self.assertTrue(environment["TAO_WORKER_WORKTREE"].endswith(manifest["worktree_path"].rsplit("/", 1)[-1]))
        launched_argv = launch.call_args.args[0]
        self.assertEqual(manifest["worktree_path"], launched_argv[launched_argv.index("--cd") + 1])
        self.assertNotIn("--skip-git-repo-check", launched_argv)
        self.assertIn(
            "projects={ "
            f'{json.dumps(manifest["worktree_path"])} = '
            '{ trust_level = "trusted" } }',
            launched_argv,
        )

    def test_worker_environment_exports_partial_result_resume_token(self) -> None:
        from workflow_dispatch_launch import worker_environment

        environment = worker_environment(
            {
                "worker_preflight_evidence": "/tmp/preflight.json",
                "worker_reservation_token": "a" * 32,
            },
            {"partial_result_id": "result-1"},
        )
        self.assertEqual("result-1", environment["TAO_RESUME_RESULT_ID"])
        self.assertEqual("task-1", worker_environment({
            "worker_preflight_evidence": "/tmp/preflight.json",
            "worker_reservation_token": "a" * 32,
        }, {"task_id": "task-1"})["TAO_TASK_ID"])

    def test_dispatch_manifest_carries_explicit_partial_result_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_dispatch_manifest(
                "task",
                "Resume a bounded worker",
                Path(directory),
                work_kind="analysis",
                partial_result_id="partial-1",
                request_classified=True,
                classification_evidence="clear-scoped task blockers resolved",
                request_classification={
                    "clarity": "clear-scoped",
                    "question_drill": False,
                    "recommended_route": "task",
                },
                route={"required_docs": ["AGENTS.md"], "gates": []},
            )
            self.assertEqual("partial-1", manifest["partial_result_id"])

    def test_dispatch_stays_inline_when_parent_profile_and_sandbox_match(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
            parent_model="gpt-5.6-terra",
            parent_reasoning_effort="medium",
            parent_sandbox_mode="workspace-write",
        )
        received: list[list[str]] = []

        self.assertEqual("inline", manifest["execution_mode"])
        with self.assertRaisesRegex(ValueError, "cannot execute work in the parent process"):
            execute_dispatch_manifest(manifest, runner=received.append)
        self.assertEqual([], received)
        self.assertIn("must not start another Codex process", manifest["execution_policy"])

    def test_dispatch_stays_inline_without_parent_profile_or_for_a_mismatch(self) -> None:
        cases = {
            "missing parent profile": {},
            "known profile mismatch": {
                "parent_model": "gpt-5.6-sol",
                "parent_reasoning_effort": "xhigh",
                "parent_sandbox_mode": "workspace-write",
            },
        }

        for name, parent_context in cases.items():
            with self.subTest(name=name):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    ROOT,
                    **parent_context,
                )

                self.assertEqual("inline", manifest["execution_mode"])
                self.assertFalse(manifest["profile_matches_parent"])
                self.assertIn("continue inline", manifest["selection_reason"])

    def test_analysis_dispatch_never_starts_a_child_without_explicit_isolation(self) -> None:
        manifest = build_dispatch_manifest(
            "analysis",
            "Inspect the current workflow routing behavior and summarize the result.",
            ROOT,
        )
        received: list[list[str]] = []

        self.assertEqual("analysis", manifest["work_kind"])
        self.assertEqual("inline", manifest["execution_mode"])
        with self.assertRaisesRegex(ValueError, "cannot execute work in the parent process"):
            execute_dispatch_manifest(manifest, runner=received.append)
        self.assertEqual([], received)

    def test_analysis_dispatch_is_read_only_and_non_authoring_in_all_modes(self) -> None:
        for isolation_required, execution_mode in ((False, "inline"), (True, "child")):
            with self.subTest(isolation_required=isolation_required):
                manifest = build_dispatch_manifest(
                    "analysis",
                    "Inspect the current workflow routing behavior and summarize the result.",
                    ROOT,
                    isolation_required=isolation_required,
                )

                self.assertEqual("analysis", manifest["work_kind"])
                self.assertEqual(execution_mode, manifest["execution_mode"])
                self.assertEqual("read-only", manifest["sandbox_mode"])
                self.assertEqual("read-only non-authoring", manifest["authoring_policy"])
                self.assertIn(
                    "Do not modify files, write code, generate patches, or create tests.",
                    manifest["codex_exec_argv"][-1],
                )

    def test_dispatch_execute_cli_rejects_inline_false_success(self) -> None:
        # A plan-free project so the inline-execute guard, not the active-plan
        # fail-closed rule, is the rejection under test.
        with tempfile.TemporaryDirectory() as temp_dir:
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    "--project",
                    temp_dir,
                    "--parent-model",
                    "gpt-5.6-terra",
                    "--parent-reasoning-effort",
                    "medium",
                    "--parent-sandbox-mode",
                    "workspace-write",
                    "--execute",
                ]
            )
            error = io.StringIO()

            with redirect_stderr(error):
                result = print_dispatch(args)

        self.assertEqual(2, result)
        self.assertIn("Inline dispatch is a decision only", error.getvalue())

    def test_inline_dispatch_does_not_reserve_worker_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                project,
                parent_model="gpt-5.6-terra",
                parent_reasoning_effort="medium",
                parent_sandbox_mode="workspace-write",
                reserve_worker_evidence=True,
            )

            self.assertEqual("inline", manifest["execution_mode"])
            self.assertFalse(manifest["handoff_state"]["worker_evidence_reserved"])
            self.assertFalse((project / ".tao" / "workers").exists())

    def test_dispatch_requires_child_when_isolation_is_explicit(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
            parent_model="gpt-5.6-terra",
            parent_reasoning_effort="medium",
            parent_sandbox_mode="workspace-write",
            isolation_required=True,
        )

        self.assertEqual("child", manifest["execution_mode"])
        self.assertTrue(manifest["profile_matches_parent"])

    def test_isolated_manifest_binds_cd_to_a_worktree_path(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
            isolation_required=True,
        )

        worktree_path = manifest["worktree_path"]
        self.assertTrue(worktree_path)
        self.assertEqual("worktree", manifest["capability_profile"]["working_dir_kind"])
        self.assertTrue(worktree_path.startswith(str(ROOT.resolve())))
        argv = manifest["codex_exec_argv"]
        bound_cd = argv[argv.index("--cd") + 1]
        self.assertEqual(worktree_path, bound_cd)
        self.assertNotEqual(str(ROOT.resolve()), bound_cd)
        self.assertFalse(any("trust_level" in item for item in argv))
        self.assertNotIn("--skip-git-repo-check", argv)

    def test_shared_manifest_stays_on_the_project_checkout(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
        )

        self.assertIsNone(manifest["worktree_path"])
        self.assertEqual("workspace", manifest["capability_profile"]["working_dir_kind"])
        argv = manifest["codex_exec_argv"]
        self.assertEqual(str(ROOT.resolve()), argv[argv.index("--cd") + 1])

    def test_dispatch_reuses_validated_parent_capsule_in_handoff_prompt(self) -> None:
        capsule_state = {
            "path": "/tmp/execution-capsule.json",
            "reusable": True,
            "invalidation_reasons": [],
            "phase": "ready",
        }
        with patch("workflow_dispatch._execution_capsule_state", return_value=capsule_state):
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                ROOT,
                isolation_required=True,
            )

        prompt = manifest["codex_exec_argv"][-1]
        self.assertIn("Validated parent execution capsule", prompt)
        self.assertIn("parent already completed route, preflight, required-doc reading", prompt)
        self.assertIn("Do not reread required docs", prompt)
        self.assertIn("Do not reread required docs or rerun route, startup, preflight, VibeGuard, review, finish", prompt)
        self.assertNotIn("Open and read every required doc", prompt)
        self.assertIn("parent remains the only owner of the gate ledger", prompt)

    def test_dispatch_fallback_worker_keeps_normal_lifecycle_and_document_reading(self) -> None:
        capsule_state = {
            "path": "/tmp/execution-capsule.json",
            "reusable": False,
            "invalidation_reasons": ["stale"],
            "phase": "ready",
        }
        with patch("workflow_dispatch._execution_capsule_state", return_value=capsule_state):
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                ROOT,
                isolation_required=True,
            )

        prompt = manifest["codex_exec_argv"][-1]
        self.assertIn("Follow the normal project lifecycle before work", prompt)
        self.assertIn("Open and read every required doc from the parent route manifest", prompt)

    def test_dispatch_execute_cli_uses_executor(self) -> None:
        # A plan-free project so --require-isolation drives execution rather than
        # the active-plan fail-closed rule short-circuiting before the executor.
        with tempfile.TemporaryDirectory() as temp_dir:
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    "--project",
                    temp_dir,
                    "--require-isolation",
                    "--execute",
                ]
            )

            with patch("workflow.execute_dispatch_manifest", return_value=23) as execute:
                self.assertEqual(23, print_dispatch(args))

        execute.assert_called_once()

    def test_dispatch_finalize_wires_explicit_ignored_discard_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir).resolve()
            worktree = project / ".tao" / "worktrees" / ("a" * 16)
            args = build_parser().parse_args(
                [
                    "dispatch-finalize",
                    "--project",
                    str(project),
                    "--worktree",
                    str(worktree),
                    "--discard-ignored",
                    "--format",
                    "json",
                ]
            )
            finalization = SimpleNamespace(
                integrated_path_count=3,
                discarded_ignored_path_count=2,
            )
            stdout = io.StringIO()
            with (
                patch(
                    "workflow.finalize_worker_worktree",
                    return_value=finalization,
                ) as finalize,
                redirect_stdout(stdout),
            ):
                self.assertEqual(0, print_dispatch_finalize(args))

        finalize.assert_called_once_with(
            project,
            worktree,
            discard_ignored=True,
        )
        self.assertEqual("finalized", json.loads(stdout.getvalue())["status"])

    def test_dispatch_self_asserted_classification_cannot_open_a_question_request(self) -> None:
        # --request-classified used to replace the classifier's verdict with a
        # regex over free text the caller wrote about itself, so a direct
        # question could open a work route just by claiming it was answered.
        # Without a valid parent capsule the classifier's verdict now stands;
        # a caller with a genuinely separate actionable request must dispatch
        # that request's text, not the question it already answered.
        args = build_parser().parse_args(
            [
                "dispatch",
                "workflow-setup",
                "--request",
                "이 워크플로우가 코덱스와 안 맞나?",
                "--request-classified",
                "--classification-evidence",
                "answered direct question; separate actionable clear-scoped workflow setup",
                "--project",
                str(ROOT),
            ]
        )

        with patch("workflow.execute_dispatch_manifest") as execute:
            self.assertEqual(2, _print_dispatch(args))

        execute.assert_not_called()

    def test_inspect_only_invalid_dispatch_withholds_raw_worker_command(self) -> None:
        capsule_state = {
            "path": "/tmp/execution-capsule.json",
            "reusable": False,
            "invalidation_reasons": ["stale"],
            "phase": "ready",
        }
        with patch("workflow_dispatch._execution_capsule_state", return_value=capsule_state):
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                ROOT,
                isolation_required=True,
            )

        markdown = io.StringIO()
        with redirect_stdout(markdown):
            print_dispatch_manifest(manifest, "markdown")
        self.assertNotIn("codex exec --model", markdown.getvalue())
        self.assertIn("withholds the raw worker command", markdown.getvalue())
        self.assertIn("--execute", markdown.getvalue())

        encoded = io.StringIO()
        with redirect_stdout(encoded):
            print_dispatch_manifest(manifest, "json")
        payload = json.loads(encoded.getvalue())
        self.assertEqual([], payload["codex_exec_argv"])
        self.assertEqual("", payload["codex_exec_command"])

    def test_dispatch_reuses_only_matching_parent_start_route_without_mutating_capsule(self) -> None:
        request = "기획변경 때 문서 정리가 누락되는 걸 막아줘"
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            parent_route = {
                "command": "feature",
                "missing": [],
                "blocking": [],
                "required_docs": ["parent-only.md"],
                "gates": ["verify"],
            }
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(project.resolve()),
                        "rules": str(ROOT.resolve()),
                        "request_intake": {
                            "request": request,
                            "request_classified": False,
                            "classification_evidence": "",
                        },
                        "route": parent_route,
                    }
                ),
                encoding="utf-8",
            )
            capsule = evidence.parent / "execution-capsule.json"
            capsule.write_text('{"sentinel": true}\n', encoding="utf-8")
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    request,
                    "--project",
                    str(project),
                    "--evidence",
                    str(evidence),
                    "--execute",
                ]
            )

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                with patch("workflow.execute_dispatch_manifest", return_value=0):
                    self.assertEqual(0, print_dispatch(args))

            self.assertEqual(parent_route, build.call_args.kwargs["route"])
            self.assertTrue(build.call_args.kwargs["parent_context_reusable"])
            self.assertEqual('{"sentinel": true}\n', capsule.read_text(encoding="utf-8"))

    def test_dispatch_rejects_stale_same_command_parent_request_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(project.resolve()),
                        "rules": str(ROOT.resolve()),
                        "request_intake": {
                            "request": "old feature request",
                            "request_classified": False,
                            "classification_evidence": "",
                        },
                        "route": {
                            "command": "feature",
                            "missing": [],
                            "blocking": [],
                            "required_docs": ["stale-parent-only.md"],
                            "gates": ["verify"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            capsule = evidence.parent / "execution-capsule.json"
            capsule.write_text('{"sentinel": true}\n', encoding="utf-8")
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    "--project",
                    str(project),
                    "--evidence",
                    str(evidence),
                    "--execute",
                ]
            )

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                with patch("workflow.execute_dispatch_manifest", return_value=0):
                    self.assertEqual(0, print_dispatch(args))

            self.assertFalse(build.call_args.kwargs["parent_context_reusable"])
            self.assertNotIn("stale-parent-only.md", build.call_args.kwargs["route"]["required_docs"])
            self.assertEqual('{"sentinel": true}\n', capsule.read_text(encoding="utf-8"))

    def test_dispatch_rejects_parent_route_missing_current_explicit_facets(self) -> None:
        request = "기획변경 때 문서 정리가 누락되는 걸 막아줘"
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(project.resolve()),
                        "rules": str(ROOT.resolve()),
                        "request_intake": {
                            "request": request,
                            "request_classified": False,
                            "classification_evidence": "",
                        },
                        "route": {
                            "command": "feature",
                            "platform": None,
                            "concerns": [],
                            "missing": [],
                            "blocking": [],
                            "required_docs": ["stale-unfaceted-parent.md"],
                            "gates": ["verify"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    request,
                    "--platform",
                    "ios",
                    "--concern",
                    "ui",
                    "--project",
                    str(project),
                    "--evidence",
                    str(evidence),
                    "--format",
                    "json",
                ]
            )

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                self.assertEqual(0, print_dispatch(args))

            self.assertFalse(build.call_args.kwargs["parent_context_reusable"])
            fresh_route = build.call_args.kwargs["route"]
            self.assertEqual("ios", fresh_route["platform"])
            self.assertIn("ui", fresh_route["concerns"])
            self.assertNotIn("stale-unfaceted-parent.md", fresh_route["required_docs"])

    def test_dispatch_rejects_foreign_project_parent_evidence(self) -> None:
        request = "기획변경 때 문서 정리가 누락되는 걸 막아줘"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "current"
            foreign = root / "foreign"
            project.mkdir()
            evidence = foreign / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(foreign.resolve()),
                        "rules": str(ROOT.resolve()),
                        "request_intake": {
                            "request": request,
                            "request_classified": False,
                            "classification_evidence": "",
                        },
                        "route": {
                            "command": "feature",
                            "missing": [],
                            "blocking": [],
                            "required_docs": ["foreign-parent-only.md"],
                            "gates": ["verify"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                [
                    "dispatch",
                    "feature",
                    "--request",
                    request,
                    "--project",
                    str(project),
                    "--evidence",
                    str(evidence),
                    "--format",
                    "json",
                ]
            )

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                self.assertEqual(0, print_dispatch(args))

            self.assertFalse(build.call_args.kwargs["parent_context_reusable"])
            self.assertNotIn(
                "foreign-parent-only.md", build.call_args.kwargs["route"]["required_docs"]
            )
            self.assertEqual(
                project.resolve() / ".tao" / "preflight.json",
                build.call_args.kwargs["evidence_path"],
            )

    def test_dispatch_reuses_classified_parent_only_for_exact_request_and_evidence(self) -> None:
        # Both requests must classify cleanly on their own: --request-classified
        # no longer suppresses classification without a valid parent capsule.
        request = "apply the resolved runtime workflow change in scripts/workflow_route.py"
        classification = "answered direct question; separate actionable clear-scoped workflow setup"
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            parent_route = {
                "command": "workflow-setup",
                "missing": [],
                "blocking": [],
                "required_docs": ["classified-parent-only.md"],
                "gates": ["verify"],
            }
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(project.resolve()),
                        "rules": str(ROOT.resolve()),
                        "request_intake": {
                            "request": request,
                            "request_classified": True,
                            "classification_evidence": classification,
                        },
                        "route": parent_route,
                    }
                ),
                encoding="utf-8",
            )

            def dispatch_args(current_request: str, current_evidence: str) -> argparse.Namespace:
                return build_parser().parse_args(
                    [
                        "dispatch",
                        "workflow-setup",
                        "--request",
                        current_request,
                        "--request-classified",
                        "--classification-evidence",
                        current_evidence,
                        "--project",
                        str(project),
                        "--evidence",
                        str(evidence),
                        "--format",
                        "json",
                    ]
                )

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                self.assertEqual(0, print_dispatch(dispatch_args(request, classification)))
            self.assertTrue(build.call_args.kwargs["parent_context_reusable"])
            self.assertEqual(parent_route, build.call_args.kwargs["route"])

            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                self.assertEqual(
                    0,
                    print_dispatch(
                        dispatch_args(
                            "a different resolved workflow change in scripts/workflow_catalog.py",
                            classification,
                        )
                    ),
                )
            self.assertFalse(build.call_args.kwargs["parent_context_reusable"])
            self.assertNotIn(
                "classified-parent-only.md", build.call_args.kwargs["route"]["required_docs"]
            )

            different_evidence = "answered direct question; separate actionable clear-exact setup"
            with patch("workflow.build_dispatch_manifest", return_value={"execution_mode": "child"}) as build:
                self.assertEqual(0, print_dispatch(dispatch_args(request, different_evidence)))
            self.assertFalse(build.call_args.kwargs["parent_context_reusable"])

    def test_dispatch_handoff_state_preserves_parent_evidence_paths(self) -> None:
        manifest = build_dispatch_manifest(
            "feature",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
            ROOT,
        )
        handoff_state = manifest["handoff_state"]
        prompt = manifest["codex_exec_argv"][-1]

        self.assertTrue(str(handoff_state["preflight_evidence"]).endswith("preflight.json"))
        self.assertTrue(str(handoff_state["gate_ledger"]).endswith("gate-evidence.json"))
        self.assertNotIn("receipt", prompt.lower())
        self.assertIn("Do not overwrite parent gate-ledger entries", prompt)

    def test_dispatch_invalid_capsule_uses_isolated_worker_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            worker_evidence = project / ".tao" / "workers" / "test-worker" / "preflight.json"
            capsule_state = {
                "path": "/tmp/execution-capsule.json",
                "reusable": False,
                "invalidation_reasons": ["stale"],
                "phase": "ready",
            }
            with patch("workflow_dispatch._execution_capsule_state", return_value=capsule_state):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    worker_evidence_path=worker_evidence,
                    reserve_worker_evidence=True,
                    isolation_required=True,
                )

            handoff = manifest["handoff_state"]
            prompt = manifest["codex_exec_argv"][-1]
            self.assertEqual(
                str(worker_evidence.resolve()), handoff["worker_preflight_evidence"]
            )
            self.assertTrue(worker_evidence.resolve().parent.is_dir())
            self.assertNotEqual(handoff["preflight_evidence"], handoff["worker_preflight_evidence"])
            self.assertNotEqual(handoff["gate_ledger"], handoff["worker_gate_ledger"])
            self.assertIn("Pass the worker preflight path with --evidence", prompt)
            self.assertIn("Never write the parent evidence files", prompt)
            token = handoff["worker_reservation_token"]
            self.assertRegex(token, r"^[0-9a-f]{32}$")
            self.assertTrue(worker_reservation_matches(worker_evidence.parent, token))

    def test_dispatch_rejects_worker_evidence_outside_isolated_root_or_parent_collision(self) -> None:
        parent = ROOT / ".tao" / "preflight.json"
        outside = ROOT / ".tao" / "not-isolated.json"
        parent_in_worker_root = ROOT / ".tao" / "workers" / "parent" / "preflight.json"
        for parent_path, worker_path, expected in (
            (parent, parent, "under <project>/.tao/workers"),
            (parent, outside, "under <project>/.tao/workers"),
            (parent_in_worker_root, parent_in_worker_root, "must not overlap parent evidence"),
        ):
            with self.subTest(worker_path=worker_path):
                with self.assertRaisesRegex(ValueError, expected):
                    build_dispatch_manifest(
                        "feature",
                        "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                        ROOT,
                        evidence_path=parent_path,
                        worker_evidence_path=worker_path,
                    )

    def test_dispatch_rejects_symlinked_worker_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            outside = root / "outside"
            (project / ".tao").mkdir(parents=True)
            outside.mkdir()
            (project / ".tao" / "workers").symlink_to(
                outside,
                target_is_directory=True,
            )

            with self.assertRaisesRegex(ValueError, "must not resolve through a symlink"):
                build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                )

    def test_dispatch_accepts_custom_rules_and_parent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            project = root / "project"
            rules = root / "rules"
            project.mkdir()
            rules.mkdir()
            evidence = project / ".tao" / "parent-a.json"
            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                project,
                rules=rules,
                evidence_path=evidence,
            )

        handoff = manifest["handoff_state"]
        prompt = manifest["codex_exec_argv"][-1]
        self.assertEqual(str(rules), handoff["rules"])
        self.assertEqual(str(evidence), handoff["preflight_evidence"])
        self.assertTrue(str(handoff["gate_ledger"]).endswith("parent-a-gate-evidence.json"))
        self.assertIn(f"Tao Agent OS rules root: {rules}", prompt)

    def test_dispatch_spill_label_contract_is_preserved(self) -> None:
        self.assertEqual(("workflow_setup", "plan"), SPILL_ACTION_LABELS["dispatch"])
        self.assertEqual(
            ("workflow_setup", "implement"),
            SPILL_ACTION_LABELS["dispatch-finalize"],
        )
        self.assertEqual([], validate_spill_label_contracts(set(COMMANDS)))

    def test_runtime_dispatch_paths_promote_runtime_guidance(self) -> None:
        route = resolve_docs(
            "workflow-setup",
            None,
            [],
            request_classified=True,
            surface_paths=["scripts/workflow_spill.py"],
        )

        for doc in (
            "docs/skills/agent-runtime-integration/SKILL.md",
            "workflows/skills/agent-handoff-continuation/SKILL.md",
            "common/skills/local-tools/SKILL.md",
        ):
            self.assertIn(guidance_area(doc), routed_areas(route))

    def test_codex_runtime_bridge_requires_stage_profile_dispatch(self) -> None:
        codex_required = runtime_bridge_required_phrases("Codex", "AGENTS.md")
        codex_block = runtime_bridge_block(ROOT, "Codex", "AGENTS.md")
        claude_block = runtime_bridge_block(ROOT, "Claude", "CLAUDE.md")

        self.assertIn(CODEX_DISPATCH_BRIDGE_PHRASE, codex_required)
        self.assertIn(CODEX_DISPATCH_BRIDGE_PHRASE, codex_block)
        self.assertNotIn(CODEX_DISPATCH_BRIDGE_PHRASE, claude_block)


class _SchedulerFailureOnWorktreeBindTestCase(unittest.TestCase):
    """A worktree-creation failure must fail the claimed scheduler task (Fix 3)."""

    _STALE_CAPSULE = {
        "path": "/tmp/execution-capsule.json",
        "reusable": False,
        "invalidation_reasons": ["stale"],
        "phase": "ready",
    }

    def test_bind_failure_transitions_task_to_failed_and_propagates(self) -> None:
        from agent_worktree_session import WorktreeSessionError

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch(
                "workflow_dispatch._execution_capsule_state",
                side_effect=[self._STALE_CAPSULE, self._STALE_CAPSULE],
            ):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch._bind_worker_working_dir",
                    side_effect=WorktreeSessionError("cannot create isolated worker worktree"),
                ):
                    with self.assertRaises(WorktreeSessionError):
                        execute_dispatch_manifest(manifest)

            scheduler = json.loads((project / ".tao" / "scheduler.json").read_text())

        self.assertEqual("failed", scheduler["tasks"][-1]["state"])

    def test_create_worktree_failure_also_fails_the_task(self) -> None:
        from agent_worktree_session import WorktreeSessionError

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch(
                "workflow_dispatch._execution_capsule_state",
                side_effect=[self._STALE_CAPSULE, self._STALE_CAPSULE],
            ):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch.create_worker_worktree",
                    side_effect=WorktreeSessionError("git worktree add failed"),
                ):
                    with self.assertRaises(WorktreeSessionError):
                        execute_dispatch_manifest(manifest)

            scheduler = json.loads((project / ".tao" / "scheduler.json").read_text())

        self.assertEqual("failed", scheduler["tasks"][-1]["state"])

    def test_nonzero_worker_exit_transitions_task_to_failed(self) -> None:
        # Integration coverage for the launch branch where the real worker
        # process returns non-zero: transition_task(..., "failed") plus the
        # (default max_retries=0) retry logic. This regained the coverage lost
        # when test_dispatch_executor_runs_selected_argv was removed, since every
        # other converted launch test mocks subprocess.run to returncode=0.
        real_run = subprocess.run

        def fake_run(command, *args, **kwargs):
            # Keep real git so the isolated worktree is genuinely created, but
            # make the codex worker process report failure.
            if command and command[0] == "git":
                return real_run(command, *args, **kwargs)
            return SimpleNamespace(returncode=1)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            _init_git_repo(project)
            with patch(
                "workflow_dispatch._execution_capsule_state",
                side_effect=[self._STALE_CAPSULE, self._STALE_CAPSULE],
            ):
                manifest = build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    route={"required_docs": [], "gates": []},
                    isolation_required=True,
                )
                with patch(
                    "workflow_dispatch_launch.subprocess.run",
                    side_effect=fake_run,
                ):
                    self.assertEqual(1, execute_dispatch_manifest(manifest))

            scheduler = json.loads((project / ".tao" / "scheduler.json").read_text())
            self.assertTrue(Path(str(manifest["worktree_path"])).is_dir())

        self.assertEqual("failed", scheduler["tasks"][-1]["state"])


if __name__ == "__main__":
    unittest.main()
