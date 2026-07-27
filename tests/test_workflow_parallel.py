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
from agent_delegation_plan import (
    SEQUENTIAL_MULTI_AGENT_MARKER,
    evidence_requires_delegation_plan,
    validate_delegation_plan_evidence,
)
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


class WorkflowParallelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_routes_expose_parallel_execution_plan(self) -> None:
        route = resolve_docs("feature", None, ["testing"], request_classified=True)
        plan = route["parallel_execution"]
        phases = {phase["id"]: phase for phase in plan["phases"]}

        self.assertEqual(1, plan["schema_version"])
        self.assertEqual([], validate_parallel_execution_plan(plan, route["gates"]))
        self.assertEqual(3, plan["delegation_policy"]["maximum_workers"])
        self.assertTrue(plan["delegation_policy"]["small_task_serial_fallback"])
        self.assertIn(
            "small bounded task that one parent can complete without a worker",
            plan["delegation_policy"]["serial_fallbacks"],
        )
        self.assertEqual("parallel", phases["orientation"]["mode"])
        self.assertIn(SOURCE_DOCS_GATE, phases["orientation"]["gates"])
        self.assertEqual("conditional_parallel", phases["implementation"]["mode"])
        self.assertIn(MULTI_AGENT_GATE, phases["implementation"]["gates"])
        self.assertEqual("serial", phases["integration_review"]["mode"])
        self.assertIn("review hook", phases["integration_review"]["gates"])
        self.assertEqual("parallel", phases["verification"]["mode"])
        self.assertIn(TEST_GATE, phases["verification"]["gates"])

    def test_multi_agent_route_exposes_worker_parallel_phase(self) -> None:
        route = resolve_docs("multi-agent", None, [], request_classified=True)
        phases = {phase["id"]: phase for phase in route["parallel_execution"]["phases"]}

        self.assertEqual([], validate_parallel_execution_plan(route["parallel_execution"], route["gates"]))
        self.assertEqual("serial", phases["scoping"]["mode"])
        self.assertIn(AGENTIC_RUN_STATE_GATE, phases["scoping"]["gates"])
        self.assertEqual("parallel", phases["worker_execution"]["mode"])
        self.assertIn("roles", phases["worker_execution"]["gates"])
        self.assertIn("write scopes", phases["worker_execution"]["gates"])
        self.assertEqual("serial", phases["integration_review"]["mode"])
        self.assertIn("integration review", phases["integration_review"]["gates"])

    def test_work_producing_routes_get_cycle_contract_but_review_stays_separate(self) -> None:
        for command in sorted(WORK_PRODUCING_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(CYCLE_CONTRACT_GATE, route["gates"])
                self.assertIn(route_doc("workflows/skills/cycle-contract/SKILL.md"), route["docs"])

        for command in ("review", "docs-review", "test", "multi-agent", "triage"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertNotIn(CYCLE_CONTRACT_GATE, route["gates"])

    def test_multi_agent_route_requires_agentic_run_state(self) -> None:
        route = resolve_docs("multi-agent", None, [], request_classified=True)

        self.assertIn(AGENTIC_RUN_STATE_GATE, route["gates"])
        self.assertIn(route_doc("workflows/skills/scripted-agent-workflow/SKILL.md"), route["docs"])
        self.assertLess(route["gates"].index(AGENTIC_RUN_STATE_GATE), route["gates"].index("roles"))
        for gate in ("roles", "write scopes", "agent briefs", "integration review"):
            self.assertIn(gate, VALIDATED_GATES)

    def test_korean_parallel_evidence_is_recognized(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "병렬 워커 2개가 소유 범위와 금지 범위를 나눠 작업했고, 계약과 브리프를 공유했다. "
                    "인수 조건과 통합 담당을 정했으며 검증 패스를 완료했다."
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_korean_serial_evidence_is_recognized(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "직렬 단일 에이전트로 진행했다. 작은 작업이고 같은 파일과 계약이 겹쳐 병렬화가 안전하지 않았다. "
                    "검증: focused test"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_korean_state_order_dependency_is_a_concrete_serial_reason(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "serial/single-agent: JIRA 생성과 단일 git branch/worktree 생성은 "
                    "동일 외부 상태에 순서 의존하는 setup 작업이라 독립된 두 구현 slice가 없다. "
                    "검증: 생성 결과와 git 상태 확인"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_negative_worker_language_does_not_require_parallel_plan(self) -> None:
        from agent_delegation_plan import validate_delegation_plan_evidence

        evidence = {
            MULTI_AGENT_GATE: (
                "직렬 단일 에이전트로 처리했고 워커 불필요. 작은 작업이라 병렬 안 함. "
                "검증은 focused test로 완료했다."
            )
        }

        self.assertEqual([], validate_delegation_plan_evidence([MULTI_AGENT_GATE], evidence, {}))

    def test_parallel_subagent_evidence_requires_contract_forbidden_scope_and_verification(self) -> None:
        failures = validate_gate_evidence(
            {MULTI_AGENT_GATE: "parallel subagent split with owned scope"},
            [MULTI_AGENT_GATE],
        )

        self.assertTrue(any("acceptance checks, integration owner, and verification" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "parallel subagent split: worker docs owns workflows/*.md; "
                    "forbidden scope: scripts/*.py; contract brief: report only doc gaps; "
                    "acceptance checks: findings include file and rule; "
                    "integration owner: lead agent; verification: workflow validate"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def test_parallel_subagent_evidence_requires_acceptance_and_integration_owner(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "parallel subagent split: worker docs owns workflows/*.md; "
                    "forbidden scope: scripts/*.py; contract brief: report only doc gaps; "
                    "verification: workflow validate"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertTrue(any("acceptance checks, integration owner" in failure for failure in failures))

    def test_parallel_subagent_finish_requires_structured_delegation_plan(self) -> None:
        evidence = {
            MULTI_AGENT_GATE: (
                "parallel subagent split: worker docs owns workflows/*.md; "
                "forbidden scope: scripts/*.py; contract brief: report doc gaps; "
                "acceptance checks: findings include file and rule; "
                "integration owner: lead agent; verification: workflow validate"
            )
        }

        failures = validate_delegation_plan_evidence([MULTI_AGENT_GATE], evidence, {})

        self.assertTrue(any("agent-delegation-plan.json" in failure for failure in failures))

        plan = {
            "schema_version": 1,
            "mode": "parallel",
            "workers": [
                {
                    "id": "docs-a",
                    "role": "docs reviewer",
                    "owned_scope": ["workflows/*.md"],
                    "forbidden_scope": ["scripts/*.py"],
                    "contract": "report documentation gaps only",
                    "acceptance": ["findings include file and rule"],
                    "verification": ["python3 scripts/workflow.py validate"],
                }
            ],
            "integration_review": {
                "owner": "lead agent",
                "contract_drift_check": "compare worker findings with route gate policy",
                "final_verification": ["python3 -m unittest discover tests"],
            },
        }

        self.assertEqual([], validate_delegation_plan_evidence([MULTI_AGENT_GATE], evidence, plan))

    def test_parallel_delegation_plan_requires_integration_owner(self) -> None:
        evidence = {
            MULTI_AGENT_GATE: (
                "parallel subagent split: worker docs owns workflows/*.md; "
                "forbidden scope: scripts/*.py; contract brief: report doc gaps; "
                "acceptance checks: findings include file and rule; "
                "integration owner: lead agent; verification: workflow validate"
            )
        }
        plan = {
            "schema_version": 1,
            "mode": "parallel",
            "workers": [
                {
                    "id": "docs-a",
                    "role": "docs reviewer",
                    "owned_scope": ["workflows/*.md"],
                    "forbidden_scope": ["scripts/*.py"],
                    "contract": "report documentation gaps only",
                    "acceptance": ["findings include file and rule"],
                    "verification": ["python3 scripts/workflow.py validate"],
                }
            ],
            "integration_review": {
                "contract_drift_check": "compare worker findings with route gate policy",
                "final_verification": ["python3 -m unittest discover tests"],
            },
        }

        failures = validate_delegation_plan_evidence([MULTI_AGENT_GATE], evidence, plan)

        self.assertTrue(any("owner/integration_owner" in failure for failure in failures))

    def test_serial_multi_agent_decision_does_not_require_delegation_plan(self) -> None:
        failures = validate_delegation_plan_evidence(
            [MULTI_AGENT_GATE],
            {
                MULTI_AGENT_GATE: (
                    "serial single-agent because same-file contract-bound change with overlapping verification"
                )
            },
            {},
        )

        self.assertEqual([], failures)

    def test_serial_multi_agent_decision_accepts_dirty_working_tree_wording(self) -> None:
        failures = validate_gate_evidence(
            {
                MULTI_AGENT_GATE: (
                    "serial single-agent because the dirty working tree has overlapping "
                    "workflow ownership; verification: full unittest"
                )
            },
            [MULTI_AGENT_GATE],
        )

        self.assertEqual([], failures)

    def _multi_worker_fields(self, mode: str, **overrides: str) -> dict[str, str]:
        """Structured split-decision fields for a genuine two-worker run."""

        fields = {
            "mode": mode,
            "reason": "two independent surfaces; worker-b started only after worker-a returned",
            "owned_scope": "worker-a: scripts/; worker-b: tests/",
            "forbidden_scope": "worker-a: tests/; worker-b: scripts/",
            "contract": "shared gate-evidence field names stay fixed",
            "acceptance": "each worker slice passes its focused check",
            "integration_owner": "lead agent",
            "verification": "python3 -m pytest tests/ -q",
        }
        fields.update(overrides)
        return fields

    def test_sequential_multi_worker_split_does_not_require_delegation_plan(self) -> None:
        """Several workers run one at a time: no concurrent writers to coordinate."""

        evidence, missing = synthesize_gate_evidence(
            MULTI_AGENT_GATE, "", self._multi_worker_fields("sequential")
        )

        self.assertEqual([], missing)
        self.assertFalse(evidence_requires_delegation_plan([], {MULTI_AGENT_GATE: evidence}))
        self.assertEqual(
            [], validate_delegation_plan_evidence([MULTI_AGENT_GATE], {MULTI_AGENT_GATE: evidence}, {})
        )

    def test_concurrent_multi_worker_split_still_requires_delegation_plan(self) -> None:
        """Workers active at the same time must still produce and pass a plan."""

        evidence, missing = synthesize_gate_evidence(
            MULTI_AGENT_GATE, "", self._multi_worker_fields("parallel")
        )

        self.assertEqual([], missing)
        self.assertTrue(evidence_requires_delegation_plan([], {MULTI_AGENT_GATE: evidence}))

        failures = validate_delegation_plan_evidence([MULTI_AGENT_GATE], {MULTI_AGENT_GATE: evidence}, {})

        self.assertTrue(any("agent-delegation-plan.json" in failure for failure in failures))

    def test_sequential_wording_is_recognized_as_non_concurrent(self) -> None:
        """`sequential` is a synonym of `serial` and must be recognized as one."""

        self.assertFalse(
            evidence_requires_delegation_plan(
                [],
                {MULTI_AGENT_GATE: "two sequential workers with disjoint write scopes"},
            )
        )

    def test_sequential_multi_worker_evidence_never_claims_single_agent(self) -> None:
        """The stored sentence must stay truthful about how many agents ran."""

        evidence, _ = synthesize_gate_evidence(
            MULTI_AGENT_GATE, "", self._multi_worker_fields("sequential")
        )

        self.assertNotIn("single-agent", evidence)
        self.assertNotIn("single agent", evidence)
        self.assertIn("multi-agent", evidence)
        self.assertIn(SEQUENTIAL_MULTI_AGENT_MARKER, evidence)

    def test_sequential_marker_alone_suppresses_delegation_plan(self) -> None:
        """The canonical marker is the structured signal, independent of prose wording.

        The marker carries a parallel signal (`workers`) and no serial word, so
        only the explicit marker check can suppress the plan here.
        """

        evidence = f"delegated to worker-a then worker-b; {SEQUENTIAL_MULTI_AGENT_MARKER}"

        self.assertFalse(evidence_requires_delegation_plan([], {MULTI_AGENT_GATE: evidence}))

    def test_sequential_multi_worker_still_requires_full_worker_brief(self) -> None:
        """Sequential excuses only the plan, never the per-worker brief fields."""

        evidence, missing = synthesize_gate_evidence(
            MULTI_AGENT_GATE,
            "",
            {
                "mode": "sequential",
                "reason": "workers ran one after another",
                "verification": "python3 -m pytest tests/ -q",
            },
        )

        self.assertEqual("", evidence)
        self.assertEqual(
            ["owned_scope", "forbidden_scope", "contract", "acceptance", "integration_owner"],
            missing,
        )

    def test_multi_agent_route_gates_require_plan_even_for_sequential_split(self) -> None:
        """Route gates outrank the sequential marker."""

        evidence, _ = synthesize_gate_evidence(
            MULTI_AGENT_GATE, "", self._multi_worker_fields("sequential")
        )

        self.assertTrue(
            evidence_requires_delegation_plan(
                ["roles", "write scopes"], {MULTI_AGENT_GATE: evidence}
            )
        )

    def test_multi_agent_route_specific_gates_require_structured_delegation_plan(self) -> None:
        failures = validate_delegation_plan_evidence(
            ["roles", "write scopes", "agent briefs", "integration review"],
            {},
            {},
        )

        self.assertTrue(any("agent-delegation-plan.json" in failure for failure in failures))

    def test_multi_agent_route_gates_reject_done_only_evidence(self) -> None:
        failures = validate_gate_evidence(
            {
                "roles": "done",
                "write scopes": "done",
                "agent briefs": "done",
                "integration review": "done",
            },
            ["roles", "write scopes", "agent briefs", "integration review"],
        )

        self.assertEqual(4, len(failures))

    def test_multi_agent_route_gates_accept_specific_delegation_evidence(self) -> None:
        failures = validate_gate_evidence(
            {
                "roles": "lead owner: main agent; worker: docs verifier; verifier: main review",
                "write scopes": "owned write scope: workflows/*.md; forbidden/read-only scope: scripts/*.py",
                "agent briefs": (
                    "worker docs-a role verifier; owned scope workflows/*.md; forbidden scope scripts/*.py; "
                    "input contract route docs policy; expected output findings; acceptance checks listed; "
                    "verification: workflow validate"
                ),
                "integration review": (
                    "integration review after merge; contract drift check for route/schema/state model; "
                    "final verification: unittest and workflow validate"
                ),
            },
            ["roles", "write scopes", "agent briefs", "integration review"],
        )

        self.assertEqual([], failures)

    def test_agentic_run_state_evidence_requires_state_transition_and_evidence(self) -> None:
        failures = validate_gate_evidence(
            {AGENTIC_RUN_STATE_GATE: "state: scoped"},
            [AGENTIC_RUN_STATE_GATE],
        )

        self.assertTrue(any("agentic run state evidence" in failure for failure in failures))

        failures = validate_gate_evidence(
            {
                AGENTIC_RUN_STATE_GATE: (
                    "run state: reviewing; next transition: reviewing -> done; "
                    "evidence: review hook and validation check passed; "
                    "checkpoint: final handoff; blocker status: no blockers"
                )
            },
            [AGENTIC_RUN_STATE_GATE],
        )

        self.assertEqual([], failures)

    def test_agentic_run_state_evidence_requires_checkpoint_and_blocker_status(self) -> None:
        failures = validate_gate_evidence(
            {
                AGENTIC_RUN_STATE_GATE: (
                    "run state: reviewing; next transition: reviewing -> done; "
                    "evidence: review hook and validation check passed"
                )
            },
            [AGENTIC_RUN_STATE_GATE],
        )

        self.assertTrue(any("checkpoint or stop condition" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
