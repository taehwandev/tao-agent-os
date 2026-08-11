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


class LessonStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_retrospective_candidate_writes_safe_global_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["TAO_STATE_HOME"] = temp_dir

            result = write_retrospective_candidate(
                {
                    "retrospective_required": True,
                    "missed_gates": ["side-effect audit"],
                    "gate_signals": [{"gate": "gate evidence policy", "signal": "FAIL"}],
                }
            )

            self.assertTrue(result["created"])
            lesson_path = Path(temp_dir) / result["relative_path"]
            lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
            self.assertEqual("repair_required", lesson["promotion_status"])
            self.assertEqual(["side_effect_audit"], lesson["missed_gates"])
            self.assertEqual("safe_slugs_only", lesson["privacy"])
            self.assertEqual(
                "repair_verify_then_resume_failed_checkpoint",
                lesson["next_action"],
            )
            self.assertEqual(
                "immediate_correction_plan",
                lesson["required_retrospective_output"],
            )
            self.assertEqual(
                "improve_tao_doc_hook_validator_or_test_before_resume",
                lesson["repair_rule"],
            )
            self.assertEqual(
                "resume_first_failed_checkpoint_after_verified_improvement",
                lesson["resume_rule"],
            )
            self.assertEqual(1, lesson["repair_cycle_limit"])
            self.assertEqual("repair_required", lesson["promotion_status"])
            for private_key in ("project", "path", "prompt", "command", "diff", "repo", "branch"):
                self.assertNotIn(private_key, lesson)

            summary = lesson_summary()
            self.assertEqual(1, summary["candidate_count"])

    def test_occurrence_keys_evict_by_recency_not_hash_order(self) -> None:
        # Regression: occurrence_keys were capped with sorted(...)[-20:],
        # which evicts by hash value rather than recency. A legitimately
        # repeated occurrence_id could be evicted while a truly stale one
        # stayed, letting old occurrences be miscounted as new.
        lesson = retrospective_candidate({"missed_gates": ["tests"], "gate_signals": []})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(25):
                upsert_retrospective_candidate(
                    root, dict(lesson), occurrence_id=f"bulk-{index}"
                )

            evicted_replay = upsert_retrospective_candidate(
                root, dict(lesson), occurrence_id="bulk-0"
            )
            recent_replay = upsert_retrospective_candidate(
                root, dict(lesson), occurrence_id="bulk-24"
            )

            self.assertFalse(evicted_replay["idempotent"])
            self.assertTrue(recent_replay["idempotent"])

    def test_lesson_candidate_empty_occurrence_id_does_not_inflate_count(self) -> None:
        # Regression: a missing agent_run_id (occurrence_id="") used to be
        # treated as a brand-new occurrence on every call, so a broken run
        # registry alone could spuriously reach the review threshold.
        lesson = retrospective_candidate({"missed_gates": ["tests"], "gate_signals": []})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            results = [
                upsert_retrospective_candidate(root, dict(lesson), occurrence_id="")
                for _ in range(5)
            ]

            self.assertEqual(
                [1, 1, 1, 1, 1],
                [result["occurrence_count"] for result in results],
            )

    def test_lesson_store_survives_concurrent_writers(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        lesson = retrospective_candidate({"missed_gates": ["tests"], "gate_signals": []})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def call(index: int) -> dict:
                return upsert_retrospective_candidate(
                    root, dict(lesson), occurrence_id=f"run-{index}"
                )

            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(call, range(30)))

            self.assertTrue(all(result["created"] for result in results))
            inbox = Path(temp_dir) / "lessons" / "inbox"
            files = list(inbox.glob("*.json"))
            self.assertEqual(1, len(files))
            final = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(30, final["occurrence_count"])

    def test_skill_feedback_hook_storage_failure_is_nonblocking(self) -> None:
        with patch.object(
            agent_skill_hooks,
            "record_skill_feedback",
            return_value=(
                {"created": False, "reason": "write_failed"},
                ["skill observation skipped: write_failed; task completion is unchanged"],
            ),
        ):
            result = agent_hook.skill_feedback_hook(
                SimpleNamespace(
                    evidence=None,
                    project=ROOT,
                    skill_feedback_outcome="observed",
                    skill_id="retrospective_learning",
                    feedback_signal="missing_skill_guidance",
                    feedback_gap="workflow_gap",
                    promotion_target="workflow_skill",
                    output=None,
                )
            )

        self.assertEqual(0, result)

    def test_finish_check_does_not_create_successful_task_skill_feedback(self) -> None:
        self.assertFalse(hasattr(agent_finish_check, "process_finish_learning"))
        self.assertTrue(hasattr(agent_finish_check, "process_skill_followup"))

    def test_every_route_requires_reflection_but_skill_feedback_hook_stays_optional(self) -> None:
        self.assertEqual(set(COMMANDS), RETROSPECTIVE_CHECK_COMMANDS)
        for command in sorted(RETROSPECTIVE_CHECK_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertIn(RETROSPECTIVE_CHECK_GATE, route["gates"])
                self.assertTrue(
                    any(item["gate"] == RETROSPECTIVE_CHECK_GATE for item in route["gate_ledger"])
                )
                self.assertTrue(route["skill_feedback"]["enabled"])
                self.assertTrue(route["skill_feedback"]["evaluation_required"])
                self.assertTrue(route["skill_feedback"]["blocking"])
                self.assertTrue(
                    route["skill_feedback"]["threshold_followup_required"]
                )
                hooks = [hook for hook in route["hooks"] if hook["hook"] == SKILL_FEEDBACK_HOOK]
                self.assertEqual(1, len(hooks))
                self.assertFalse(hooks[0]["required"])


if __name__ == "__main__":
    unittest.main()
