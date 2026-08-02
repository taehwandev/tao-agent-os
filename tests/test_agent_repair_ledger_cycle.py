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
from agent_route_state import request_fingerprint
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


class RepairLedgerCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_hook_rejects_invalid_concern_before_start_repair_policy(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent-hook.py"),
                "start",
                "--concern",
                "not-a-real-concern",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)
        self.assertNotIn("recovery request", result.stdout + result.stderr)

    def test_hook_failure_policy_requires_verified_repair_before_resume(self) -> None:
        policy, details = hook_failure_policy(success=False, repair_cycle=0)

        self.assertEqual("retrospective_then_repair_verify_resume", policy["next_action"])
        self.assertEqual("verified_tao_improvement", policy["recovery_required"])
        joined_details = " ".join(details)
        self.assertIn("actionable retrospective", joined_details)
        self.assertIn("Tao Agent OS doc, hook, validator, or test", joined_details)
        self.assertIn("--repair-cycle 1", joined_details)
        self.assertIn("--resume-checkpoint", joined_details)

    def test_hook_failure_policy_stops_after_repair_verification_fails(self) -> None:
        policy, details = hook_failure_policy(success=False, repair_cycle=1)

        self.assertEqual("stop_after_repair_verification_failed", policy["next_action"])
        self.assertEqual("promote_or_handoff_lesson", policy["recovery_required"])
        joined_details = " ".join(details)
        self.assertIn("failed after one repair cycle", joined_details)
        self.assertIn("do not resume", joined_details)

    def test_skill_followup_pending_uses_closeout_not_repair_policy(self) -> None:
        policy, details = hook_failure_policy(
            success=False,
            repair_cycle=0,
            pending_closeout=True,
        )

        self.assertEqual(
            "complete_skill_followup_then_retry_finish",
            policy["next_action"],
        )
        self.assertEqual(
            "bounded_skill_review_or_verified_maintenance",
            policy["recovery_required"],
        )
        self.assertEqual("finish", policy["resume_scope"])
        joined_details = " ".join(details)
        self.assertIn("skill-review", joined_details)
        self.assertIn("do not run repair-verify", joined_details)
        self.assertNotIn("actionable retrospective", joined_details)

    def test_hook_success_after_repair_resumes_failed_checkpoint(self) -> None:
        policy, details = hook_failure_policy(success=True, repair_cycle=1)

        self.assertEqual("resume_failed_checkpoint", policy["next_action"])
        self.assertEqual(1, policy["repair_cycle"])
        self.assertEqual([], details)

    def test_repair_context_rejects_missing_target_evidence_and_checkpoint(self) -> None:
        # repair_context_failures no longer parses free-text evidence prose
        # (see agent_repair_verification.py): --repair-evidence must now name
        # a structural repair receipt file. These are the argument-shape
        # checks that still apply before any receipt is read.
        failures = repair_context_failures("", "", "")

        self.assertEqual(3, len(failures))
        self.assertTrue(any("--repair-target" in failure for failure in failures))
        self.assertTrue(any("--repair-evidence" in failure for failure in failures))
        self.assertTrue(any("--resume-checkpoint" in failure for failure in failures))

    def test_repair_context_requires_runtime_state_to_validate_a_receipt(self) -> None:
        # With target/evidence/checkpoint present but no project/rules/
        # preflight/evidence_path supplied, there is nothing to validate the
        # claimed receipt against -- this must fail closed, not pass open.
        failures = repair_context_failures(
            "workflows/skills/retrospective-learning/SKILL.md",
            "/tmp/some-receipt.json",
            "finish",
        )
        self.assertTrue(failures)
        self.assertTrue(
            any("requires current project, rules, preflight" in failure for failure in failures)
        )

    def test_register_repair_attempt_is_race_safe(self) -> None:
        # Regression: register_repair_attempt() did an unlocked
        # read-modify-write on the gate-evidence ledger, so concurrent
        # callers could all read count=0 before any of them wrote count=1,
        # letting the "1 repair cycle" limit be exceeded. Reproduced with 40
        # concurrent callers: ~6 were incorrectly allowed before the fix.
        from concurrent.futures import ThreadPoolExecutor

        from agent_gate_evidence import record_finish_failure_checkpoints, register_repair_attempt

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_finish_failure_checkpoints(
                evidence_path=evidence_path, preflight=preflight, checkpoints=["tests"]
            )

            def attempt(_: int):
                return register_repair_attempt(
                    evidence_path=evidence_path,
                    preflight=preflight,
                    checkpoint="tests",
                    limit=1,
                )

            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(attempt, range(40)))

            allowed = [result for result in results if result[0]]
            self.assertEqual(1, len(allowed))

    def test_repair_cycle_requires_persisted_prior_failure_and_is_bounded(self) -> None:
        from agent_repair_ledger import record_failure_checkpoints
        from agent_repair_verification import create_repair_receipt

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=str(project),
                check=True,
            )
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")

            # No recorded failure yet: a receipt cannot even be generated for
            # a checkpoint that never failed.
            no_failure_receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertFalse(no_failure_receipt["created"])
            self.assertEqual("checkpoint_not_failed", no_failure_receipt["reason"])

            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests", "finish"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a", "finish": "sig-a"},
            )

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])

            # First legitimate repair claim against a real failure succeeds.
            self.assertEqual(
                [],
                repair_context_failures(
                    "target.py",
                    receipt["receipt_path"],
                    "tests",
                    route=preflight["route"],
                    evidence_path=evidence_path,
                    preflight=preflight,
                    project=project,
                    rules=ROOT,
                ),
            )

            # A second claim for the same checkpoint is blocked by the
            # persisted limit, regardless of --repair-cycle being 0 on this
            # fresh process invocation.
            failures = repair_context_failures(
                "target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertTrue(failures)
            self.assertTrue(any("repair cycle limit" in f for f in failures))

    def test_repair_evidence_must_reference_repair_target(self) -> None:
        # Regression (Codex finding): --repair-target and --repair-evidence
        # were validated independently -- an unrelated but positive-sounding
        # check ("unrelated documentation smoke test passed") satisfied the
        # evidence requirement for any target at all, consuming the one
        # repair attempt on a claim that never verified the repaired thing.
        # This is now structurally impossible: a receipt records the exact
        # target file it verified, so presenting it for a different target
        # is rejected by field comparison, not by parsing evidence prose.
        from agent_repair_ledger import record_failure_checkpoints
        from agent_repair_verification import create_repair_receipt

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=str(project),
                check=True,
            )
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            actual_target = project / "actual_target.py"
            actual_target.write_text("x = 1\n", encoding="utf-8")
            unrelated_target = project / "unrelated_target.py"
            unrelated_target.write_text("y = 1\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="actual_target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])

            # Claiming the unrelated target with a receipt that actually
            # covers actual_target.py must be rejected.
            failures = repair_context_failures(
                "unrelated_target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertTrue(failures)
            self.assertTrue(any("does not match current repair state" in f for f in failures))

    def test_repair_cycle_resets_for_a_genuinely_different_failure(self) -> None:
        # Regression (Codex finding): the repair-attempt counter was keyed
        # only by checkpoint name, with no failure signature -- so once a
        # checkpoint's single repair attempt was consumed for one failure, a
        # later, completely unrelated failure hitting the SAME checkpoint
        # name was also blocked, forcing an unnecessary promote-or-handoff.
        from agent_repair_ledger import record_failure_checkpoints
        from agent_repair_verification import create_repair_receipt

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=str(project),
                check=True,
            )
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")

            def _repair_target() -> list[str]:
                receipt = create_repair_receipt(
                    project=project,
                    rules=ROOT,
                    evidence_path=evidence_path,
                    preflight=preflight,
                    target="target.py",
                    checkpoint="tests",
                    verification_kind="py_compile",
                )
                self.assertTrue(receipt["created"])
                return repair_context_failures(
                    "target.py",
                    receipt["receipt_path"],
                    "tests",
                    route=preflight["route"],
                    evidence_path=evidence_path,
                    preflight=preflight,
                    project=project,
                    rules=ROOT,
                )

            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            self.assertEqual([], _repair_target())
            self.assertTrue(_repair_target())

            # Same checkpoint, but a genuinely different, later failure.
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-b",
                checkpoint_signatures={"tests": "sig-b"},
            )
            self.assertEqual([], _repair_target())
            self.assertTrue(_repair_target())

    def test_repair_cycle_unrelated_failure_does_not_reset_other_checkpoints(self) -> None:
        # Regression: record_failure_checkpoints wiped the ENTIRE
        # repair_attempts map whenever the overall batch failure_signature
        # (a hash of ALL failures in that run) changed. Since that signature
        # changes whenever ANY checkpoint's message differs, an unrelated
        # failure on a different checkpoint reset an already-spent checkpoint
        # back to "fresh", letting the same original failure recur and get a
        # second repair attempt it should not have.
        from agent_repair_ledger import (
            checkpoint_failure_signature,
            failure_signature,
            record_failure_checkpoints,
            register_repair_attempt,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {
                "route": {"command": "bugfix", "gates": ["tests", "boundary plan", "handoff"]}
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            tests_sig = failure_signature(["missing tests evidence"])
            boundary_sig1 = failure_signature(["missing boundary plan evidence"])
            sig1 = failure_signature(["missing tests evidence", "missing boundary plan evidence"])
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests", "boundary plan"],
                signature=sig1,
                checkpoint_signatures={
                    "tests": tests_sig,
                    "boundary plan": boundary_sig1,
                },
            )
            allowed, _ = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature=tests_sig,
            )
            self.assertTrue(allowed)

            # The same tests failure remains in the batch while only the
            # unrelated boundary-plan failure changes. The overall batch hash
            # changes, but the tests checkpoint signature must remain stable.
            boundary_sig2 = failure_signature(
                ["boundary plan evidence has a different specific issue"]
            )
            sig2 = failure_signature(
                ["missing tests evidence", "boundary plan evidence has a different specific issue"]
            )
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests", "boundary plan"],
                signature=sig2,
                checkpoint_signatures={
                    "tests": tests_sig,
                    "boundary plan": boundary_sig2,
                },
            )
            self.assertEqual(
                tests_sig,
                checkpoint_failure_signature(
                    route=preflight["route"],
                    evidence_path=evidence_path,
                    checkpoint="tests",
                ),
            )
            allowed_again, _ = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature=tests_sig,
            )
            self.assertFalse(allowed_again)

    def test_repair_cycle_empty_signature_does_not_permanently_lock_checkpoint(self) -> None:
        # Regression: register_repair_attempt only reset a checkpoint's spent
        # count when BOTH the prior and incoming failure_signature were
        # non-empty and differed. A first attempt recorded with an empty
        # signature (e.g. a call site that could not compute one) stored
        # failure_signature="" forever, so `prior_signature and ... !=` was
        # always False once the limit was hit -- locking the checkpoint out
        # of repair even for a later, genuinely different, real-signature
        # failure.
        from agent_repair_ledger import (
            failure_signature,
            record_failure_checkpoints,
            register_repair_attempt,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            record_failure_checkpoints(
                evidence_path=evidence_path, preflight=preflight,
                checkpoints=["tests"], signature="",
            )
            allowed_first, count_first = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature="",
            )
            self.assertTrue(allowed_first)
            self.assertEqual(1, count_first)

            later_sig = failure_signature(["a totally different tests failure"])
            record_failure_checkpoints(
                evidence_path=evidence_path, preflight=preflight,
                checkpoints=["tests"], signature=later_sig,
            )
            allowed_second, _ = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature=later_sig,
            )
            self.assertTrue(allowed_second)

    def test_repair_cycle_repeated_empty_signature_still_respects_bound(self) -> None:
        # Companion to the empty-signature-permanent-lock fix above: when a
        # call site can never compute a signature (stays "" every time), we
        # cannot prove a later failure is different, so the bounded-retry
        # limit must still apply -- otherwise the fix for the permanent-lock
        # bug would regress into unlimited retries for any caller that never
        # passes a real signature (which is exactly what the pre-existing
        # test_repair_cycle_requires_persisted_prior_failure_and_is_bounded
        # exercises via the default `failure_signature=""` call sites).
        from agent_repair_ledger import record_failure_checkpoints, register_repair_attempt

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            record_failure_checkpoints(
                evidence_path=evidence_path, preflight=preflight,
                checkpoints=["tests"], signature="",
            )
            allowed_first, _ = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature="",
            )
            self.assertTrue(allowed_first)

            record_failure_checkpoints(
                evidence_path=evidence_path, preflight=preflight,
                checkpoints=["tests"], signature="",
            )
            allowed_second, _ = register_repair_attempt(
                evidence_path=evidence_path, preflight=preflight,
                checkpoint="tests", limit=1, failure_signature="",
            )
            self.assertFalse(allowed_second)

    def test_repair_ledger_rejects_writes_outside_launcher_issued_worker_evidence(self) -> None:
        from agent_repair_ledger import record_failure_checkpoints

        with tempfile.TemporaryDirectory() as temp_dir:
            parent_evidence = Path(temp_dir) / "preflight.json"
            worker_evidence = Path(temp_dir) / "worker-preflight.json"
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            parent_evidence.write_text(json.dumps(preflight), encoding="utf-8")
            worker_evidence.write_text(json.dumps(preflight), encoding="utf-8")

            os.environ["TAO_WORKER_EVIDENCE"] = str(worker_evidence)
            try:
                with self.assertRaises(PermissionError):
                    record_failure_checkpoints(
                        evidence_path=parent_evidence, preflight=preflight,
                        checkpoints=["tests"], signature="sig",
                    )
            finally:
                del os.environ["TAO_WORKER_EVIDENCE"]

    def test_finish_records_checkpoint_specific_failure_signatures(self) -> None:
        from agent_repair_ledger import (
            checkpoint_failure_signature,
            register_repair_attempt,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {
                "route": {
                    "command": "bugfix",
                    "gates": ["tests", "boundary plan", "handoff"],
                }
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            def report(boundary_failure: str) -> None:
                with redirect_stderr(io.StringIO()):
                    result = agent_finish_check._report_finish_failures(
                        failures=[
                            "missing required gate evidence: tests",
                            boundary_failure,
                        ],
                        gate_policy_failures=[boundary_failure],
                        required_gates=["tests", "boundary plan", "handoff"],
                        missed_gates=["tests"],
                        gate_evidence={"boundary plan": "recorded boundary evidence"},
                        evidence_path=evidence_path,
                        preflight=preflight,
                    )
                self.assertEqual(1, result)

            report("boundary plan evidence issue A")
            tests_signature = checkpoint_failure_signature(
                route=preflight["route"],
                evidence_path=evidence_path,
                checkpoint="tests",
            )
            allowed, _ = register_repair_attempt(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoint="tests",
                limit=1,
                failure_signature=tests_signature,
            )
            self.assertTrue(allowed)

            report("boundary plan evidence issue B")
            self.assertEqual(
                tests_signature,
                checkpoint_failure_signature(
                    route=preflight["route"],
                    evidence_path=evidence_path,
                    checkpoint="tests",
                ),
            )
            allowed_again, _ = register_repair_attempt(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoint="tests",
                limit=1,
                failure_signature=tests_signature,
            )
            self.assertFalse(allowed_again)

    def test_repair_cycle_resolves_worker_isolated_evidence_path(self) -> None:
        # Regression: agent-hook.py's main() used to resolve
        # preflight_evidence_path(args) for the repair-cycle check BEFORE
        # _apply_worker_evidence_boundary() re-pointed args.evidence at the
        # worker's launcher-issued isolated path. A worker invoking a hook
        # with --repair-cycle 1 (no explicit --evidence, the normal
        # launcher-issued pattern) would have its repair claim checked
        # against the PARENT's repair-checkpoints.json instead of its own,
        # so checkpoint_has_recorded_failure always missed and every
        # legitimate worker repair-cycle claim was rejected.
        from agent_repair_ledger import record_failure_checkpoints
        from agent_repair_verification import create_repair_receipt

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=str(project),
                check=True,
            )
            worker_evidence = project / "worker" / "preflight.json"
            worker_evidence.parent.mkdir(parents=True)
            preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
            worker_evidence.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=worker_evidence,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")
            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=worker_evidence,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])

            argv = [
                "agent-hook.py",
                "gate",
                "--project",
                str(project),
                "--rules",
                str(ROOT),
                "--gate-name",
                "tests",
                "--field",
                "check=pytest",
                "--field",
                "result=passed",
                "--repair-cycle",
                "1",
                "--repair-target",
                "target.py",
                "--repair-evidence",
                receipt["receipt_path"],
                "--resume-checkpoint",
                "tests",
            ]
            env_patch = {"TAO_WORKER_EVIDENCE": str(worker_evidence)}
            old_env = {key: os.environ.get(key) for key in env_patch}
            os.environ.update(env_patch)
            try:
                with patch.object(sys, "argv", argv):
                    exit_code = agent_hook.main()
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            self.assertEqual(0, exit_code)

    def test_start_then_gate_preserves_request_intake_in_ledger(self) -> None:
        # Regression found via an end-to-end CLI rehearsal (not a unit-level
        # call): agent-hook.py's start_hook records "request intake" in the
        # gate-evidence ledger, bound to preflight.json's hash at that
        # moment. _register_started_run then rewrites preflight.json in
        # place to add agent_run_id, so the ledger's stored hash goes stale
        # immediately. The next gate write's self-heal check ("a stale
        # ledger is not the same as an empty one, so start over") could not
        # tell that apart from a genuinely new request and silently wiped
        # every already-recorded entry -- reproduced with real `start` then
        # `gate` subprocess calls: right after start entries were
        # ["request intake"], and after exactly one more `gate` call it
        # became just the new gate, with "request intake" gone.
        #
        # Run it under both runtime-session states. `start` always puts implicit
        # evidence in an isolated run directory. A session-bound caller may
        # resolve that path from its runtime identity; a runtime without a
        # session id must carry the exact path returned by start into every
        # later hook. A hard-coded shared ledger path would silently test a
        # lifecycle that the product no longer permits.
        for session_id in ("ledger-cycle-session", ""):
            with self.subTest(session=session_id or "none"):
                self._assert_start_then_gate_preserves_intake(session_id)

    def _assert_start_then_gate_preserves_intake(self, session_id: str) -> None:
        from agent_gate_evidence import gate_evidence_path_for_preflight
        from agent_runtime_session import SESSION_ENV_VARS, resolve_runtime_evidence

        session_env = {variable: session_id for _, variable in SESSION_ENV_VARS}
        with patch.dict(os.environ, session_env, clear=False):
            for variable, value in session_env.items():
                if not value:
                    os.environ.pop(variable, None)
            self._run_start_then_gate(
                bool(session_id), gate_evidence_path_for_preflight, resolve_runtime_evidence
            )

    def _run_start_then_gate(self, has_session, ledger_for, resolve_evidence) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=str(project),
                check=True,
            )

            request = "fix the stale ledger hash in scripts/agent_gate_evidence.py"
            intent_session_id = "ledger-cycle-session" if has_session else "ledger-no-session-test"
            envelope = {
                "schema_version": 1,
                "request_fingerprint": request_fingerprint({"request": request}),
                "runtime_session_id": intent_session_id,
                "mode": "work",
                "intent": "repair",
                "target_summary": "the stale gate ledger hash",
                "requested_effects": ["local_write"],
                "ambiguity": "resolved",
            }
            start_argv = [
                "agent-hook.py",
                "start",
                "--project",
                str(project),
                "--rules",
                str(ROOT),
                "--command",
                "bugfix",
                "--request-classified",
                "--classification-evidence",
                "clear-scoped: rehearsal bug reproduced with exact scope; no blockers; scope clarified",
                # The request must classify cleanly on its own: --request-classified
                # no longer suppresses classification without a parent capsule.
                "--request",
                request,
                "--intent-envelope",
                json.dumps(envelope),
                "--runtime-session-id",
                intent_session_id,
            ]
            with patch.object(sys, "argv", start_argv):
                start_exit = agent_hook.main()
            self.assertEqual(0, start_exit)

            run_evidence = tuple((project / ".tao" / "runs").glob("*/preflight.json"))
            self.assertEqual(
                1,
                len(run_evidence),
                "implicit start must allocate one unambiguous run-local evidence path",
            )
            evidence_path = run_evidence[0]
            if has_session:
                resolved_evidence = resolve_evidence(project)
                self.assertEqual(
                    evidence_path.resolve(),
                    resolved_evidence,
                    "a session-bound start must leave exactly one resolvable run",
                )
            ledger_path = ledger_for(evidence_path)
            after_start = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["request intake"], [entry["gate"] for entry in after_start["entries"]]
            )

            gate_argv = [
                "agent-hook.py",
                "gate",
                "--project",
                str(project),
                "--rules",
                str(ROOT),
                "--evidence",
                str(evidence_path),
                "--gate-name",
                "reproduce",
                "--gate-evidence",
                "reproduced the rehearsal fixture failure",
            ]
            with patch.object(sys, "argv", gate_argv):
                gate_exit = agent_hook.main()
            self.assertEqual(0, gate_exit)

            after_gate = json.loads(ledger_path.read_text(encoding="utf-8"))
            gates_after = {entry["gate"] for entry in after_gate["entries"]}
            self.assertIn("request intake", gates_after)
            self.assertIn("reproduce", gates_after)

    def test_source_docs_gate_covers_policy_and_repair_workflows(self) -> None:
        implementation_anchors = {
            "bugfix": "fix",
            "code-simplify": "small refactor",
            "refactor": "small refactor",
            "workflow-setup": "install or repair",
        }
        for command in ("bugfix", "code-simplify", "refactor", "workflow-setup"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertIn(SOURCE_DOCS_GATE, route["gates"])
                self.assertIn(DOCUMENTATION_IMPACT_GATE, route["gates"])
                self.assertIn(CYCLE_CONTRACT_GATE, route["gates"])
                self.assertIn(route_doc("common/skills/source-driven-development/SKILL.md"), route["docs"])
                self.assertIn(route_doc("workflows/skills/cycle-contract/SKILL.md"), route["docs"])
                implementation_anchor = implementation_anchors[command]
                self.assertLess(
                    route["gates"].index(DOCUMENTATION_IMPACT_GATE),
                    route["gates"].index(implementation_anchor),
                )
                self.assertLess(route["gates"].index(CYCLE_CONTRACT_GATE), route["gates"].index(implementation_anchor))
                self.assertLess(route["gates"].index(SOURCE_DOCS_GATE), route["gates"].index(AMBIGUITY_GATE))

    def test_repair_cycle_cli_requires_target_evidence_and_resume_checkpoint(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent-hook.py"),
                "gate-batch",
                "--repair-cycle",
                "1",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("--repair-target", result.stderr)
        self.assertIn("--repair-evidence", result.stderr)
        self.assertIn("--resume-checkpoint", result.stderr)


if __name__ == "__main__":
    unittest.main()
