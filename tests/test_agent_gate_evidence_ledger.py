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


class GateEvidenceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_policy_invalid_gate_evidence_is_attributable_to_its_gate(self) -> None:
        # Regression (Codex finding): a gate with non-empty but
        # content-invalid evidence (e.g. tests="done") is not in
        # missed_gates (it has evidence), so its failure only landed in the
        # generic "finish" checkpoint bucket -- a --resume-checkpoint tests
        # repair claim was rejected as never-recorded, even though "tests"
        # is precisely what failed. This mirrors the attribution logic
        # agent-finish-check.py applies before recording failed checkpoints.
        gate_evidence = {"tests": "done"}
        required_gates, missed_gates, gate_policy_failures = check_required_gates(
            {"gates": ["tests", "handoff"]}, gate_evidence, [], [], {}
        )
        policy_failed_gates = [
            gate
            for gate in required_gates
            if gate_evidence.get(gate, "").strip()
            and any(gate.lower() in failure.lower() for failure in gate_policy_failures)
        ]

        self.assertNotIn("tests", missed_gates)
        self.assertIn("tests", policy_failed_gates)

    def test_gate_evidence_ledger_synthesizes_structured_finish_evidence(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [CYCLE_CONTRACT_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)

            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate=CYCLE_CONTRACT_GATE,
                fields={
                    "cycle_type": "workflow_setup",
                    "input_scope": "finish evidence workflow policy",
                    "allowed_changes": "hook ledger, finish-check merge, tests, docs",
                    "forbidden_changes": "unrelated dirty worktree and external state",
                    "acceptance_criteria": "finish can read current structured gate ledger",
                    "verification": "unit tests and workflow validate",
                    "stop_condition": "ledger evidence is merged and validated",
                    "checkpoint": "handoff",
                },
                source="manual",
            )
            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

            self.assertTrue(gate_evidence_path_for_preflight(evidence_path).exists())
            self.assertTrue(diagnostics["used"])
            self.assertIn(CYCLE_CONTRACT_GATE, gate_evidence)
            self.assertEqual([], validate_gate_evidence(gate_evidence, route["gates"]))

    def test_gate_evidence_ledger_requires_structured_fields_for_structured_gates(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [CYCLE_CONTRACT_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)

            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate=CYCLE_CONTRACT_GATE,
                evidence=(
                    "cycle_type=workflow_setup; input_scope=gate evidence ledger fallback; "
                    "allowed_changes=finish-check merge code and tests; "
                    "forbidden_changes=unrelated workflow behavior; "
                    "acceptance criteria=manual ledger evidence is still validated by finish; "
                    "verification=unit test; stop condition=manual evidence merges; "
                    "checkpoint=finish hook retry"
                ),
                source="manual",
            )

            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

        self.assertFalse(diagnostics["used"])
        self.assertIn(CYCLE_CONTRACT_GATE, diagnostics["missing_fields"])
        self.assertNotIn(CYCLE_CONTRACT_GATE, gate_evidence)

    def test_gate_evidence_ledger_rejects_same_route_preflight_hash_refresh(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [TEST_GATE, CYCLE_CONTRACT_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route, "git_status": {"stdout": "before"}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate=TEST_GATE,
                evidence="test/check run: first check; result: PASS",
                source="manual",
            )

            refreshed_preflight = {"route": route, "git_status": {"stdout": "after"}}
            evidence_path.write_text(json.dumps(refreshed_preflight), encoding="utf-8")
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=refreshed_preflight,
                gate=CYCLE_CONTRACT_GATE,
                fields={
                    "cycle_type": "workflow_setup",
                    "input_scope": "same route ledger refresh",
                    "allowed_changes": "gate evidence binding",
                    "forbidden_changes": "route changes",
                    "acceptance_criteria": "existing gate evidence remains after hash refresh",
                    "verification": "unit test",
                    "stop_condition": "ledger keeps both entries",
                    "checkpoint": "finish hook",
                },
                source="manual",
            )

            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

        self.assertTrue(diagnostics["used"])
        self.assertNotIn(TEST_GATE, gate_evidence)
        self.assertIn(CYCLE_CONTRACT_GATE, gate_evidence)
        self.assertEqual([], validate_gate_evidence(gate_evidence, route["gates"]))

    def test_gate_evidence_ledger_rejects_partial_structured_fields_even_with_text(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [CYCLE_CONTRACT_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)

            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate=CYCLE_CONTRACT_GATE,
                evidence=(
                    "cycle_type=workflow_setup; input_scope=partial fields; "
                    "allowed_changes=tests; forbidden_changes=none; "
                    "acceptance criteria=must not bypass fields; verification=unit test; "
                    "stop condition=done; checkpoint=finish"
                ),
                fields={
                    "cycle_type": "workflow_setup",
                    "input_scope": "partial fields",
                },
                source="manual",
            )

            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

        self.assertNotIn(CYCLE_CONTRACT_GATE, gate_evidence)
        self.assertIn(CYCLE_CONTRACT_GATE, diagnostics["missing_fields"])

    def test_record_many_gate_evidence_writes_batch_with_single_binding(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [BOUNDARY_PLAN_GATE, TEST_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            entries = record_many_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                records=[
                    {
                        "gate": BOUNDARY_PLAN_GATE,
                        "fields": {
                            "scope": "gate evidence batching",
                            "verification": "unit test",
                        },
                    },
                    {
                        "gate": TEST_GATE,
                        "fields": {
                            "check": "unit test",
                            "result": "PASS",
                        },
                    },
                ],
            )

            ledger_path = gate_evidence_path_for_preflight(evidence_path)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

        self.assertEqual(2, len(entries))
        self.assertEqual(2, len(ledger["entries"]))
        self.assertTrue(diagnostics["used"])
        self.assertIn(BOUNDARY_PLAN_GATE, gate_evidence)
        self.assertIn(TEST_GATE, gate_evidence)
        self.assertEqual([], validate_gate_evidence(gate_evidence, route["gates"]))

    def test_custom_preflight_evidence_uses_separate_gate_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            default_evidence = root / ".tao" / "preflight.json"
            custom_evidence = root / ".tao" / "preflight-smoke.json"
            default_evidence.parent.mkdir(parents=True)

            self.assertEqual(
                default_evidence.parent / "gate-evidence.json",
                gate_evidence_path_for_preflight(default_evidence),
            )
            self.assertEqual(
                custom_evidence.parent / "preflight-smoke-gate-evidence.json",
                gate_evidence_path_for_preflight(custom_evidence),
            )

    def test_agent_hook_gate_batch_cli_records_multiple_gates(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [BOUNDARY_PLAN_GATE, TEST_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "project": str(project),
                "rules": str(ROOT.resolve()),
                "route": route,
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            records = [
                {
                    "gate": BOUNDARY_PLAN_GATE,
                    "fields": {
                        "scope": "gate evidence batch cli",
                        "verification": "subprocess test",
                    },
                },
                {
                    "gate": TEST_GATE,
                    "fields": {
                        "check": "subprocess test",
                        "result": "PASS",
                    },
                },
            ]

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-hook.py"),
                    "gate-batch",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--evidence",
                    str(evidence_path),
                    "--gate-record",
                    json.dumps(records),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            ledger_path = gate_evidence_path_for_preflight(evidence_path)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("SUCCESS gate-batch", result.stdout)
        self.assertIn("2 gate evidence entries recorded", result.stdout)
        self.assertEqual([BOUNDARY_PLAN_GATE, TEST_GATE], [entry["gate"] for entry in ledger["entries"]])

    def test_gate_evidence_ledger_ignores_stale_preflight(self) -> None:
        route = {
            "command": "workflow-setup",
            "docs": ["AGENTS.md"],
            "gates": [CYCLE_CONTRACT_GATE],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                gate=CYCLE_CONTRACT_GATE,
                fields={
                    "cycle_type": "workflow_setup",
                    "input_scope": "old route",
                    "allowed_changes": "old changes",
                    "forbidden_changes": "old forbidden scope",
                    "acceptance_criteria": "old criteria",
                    "verification": "old verification",
                    "stop_condition": "old stop",
                    "checkpoint": "old checkpoint",
                },
                source="manual",
            )
            stale_preflight = {"route": {**route, "gates": [CYCLE_CONTRACT_GATE, "verify"]}}
            evidence_path.write_text(json.dumps(stale_preflight), encoding="utf-8")

            gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
                route=stale_preflight["route"],
                evidence_path=evidence_path,
            )

        self.assertEqual({}, gate_evidence)
        self.assertIn("stale", " ".join(diagnostics["warnings"]))

    def test_new_request_cannot_reuse_prior_review_success_on_same_route(self) -> None:
        route = {
            "command": "review",
            "docs": ["AGENTS.md"],
            "gates": ["review hook"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            old_preflight = {
                "route": route,
                "request_intake": {"request": "review the first change"},
            }
            evidence_path.write_text(json.dumps(old_preflight), encoding="utf-8")
            reset_gate_evidence_ledger(evidence_path, old_preflight)
            record_gate_evidence(
                evidence_path=evidence_path,
                preflight=old_preflight,
                gate="review hook",
                evidence="first request review completed",
                source="review",
            )

            new_preflight = {
                "route": route,
                "request_intake": {"request": "review a different change"},
            }
            evidence_path.write_text(json.dumps(new_preflight), encoding="utf-8")
            stale_evidence, stale_diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )
            reset_gate_evidence_ledger(evidence_path, new_preflight)
            fresh_evidence, fresh_diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

        self.assertNotIn("review hook", stale_evidence)
        self.assertIn("stale", " ".join(stale_diagnostics["warnings"]))
        self.assertNotIn("review hook", fresh_evidence)
        self.assertFalse(fresh_diagnostics["used"])


if __name__ == "__main__":
    unittest.main()
