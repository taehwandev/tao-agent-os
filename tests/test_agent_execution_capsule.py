from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_execution_capsule import (
    REUSE_POLICY,
    capsule_path_for_evidence,
    create_preflight_snapshot,
    read_execution_capsule,
    refresh_execution_capsule,
    synchronize_execution_capsule_gate_ledger,
    validate_execution_capsule,
)
from agent_execution_capsule_state import (
    execution_capsule_binding_fingerprint,
    git_states_for_paths,
    preflight_snapshot_binding_fingerprint,
)
import agent_execution_capsule_state as capsule_state
from agent_execution_capsule_bindings import preflight_identity_failures
from agent_directory_fingerprint import DIRECTORY_STATE_HEAD
from agent_execution_capsule_validation import (
    validate_preflight_snapshot,
    validate_source_docs_binding,
)
from agent_finish_final_checks import (
    record_successful_review_workflow_validation,
    reusable_review_workflow_validation,
    run_final_checks,
)
from agent_finish_check_steps import route_gate_capsule_binding_failures
from agent_gate_evidence import (
    gate_evidence_path_for_preflight,
    incomplete_gate_evidence_failures,
    latest_successful_gate_fields,
    merge_gate_evidence_from_ledger,
    bind_gate_evidence_to_capsule,
    record_gate_evidence,
)
from agent_route_state import preflight_evidence_sha256, route_fingerprint
from agent_finish_documentation import documented_required_doc_updates
from agent_repair_ledger import record_failure_checkpoints
from agent_repair_verification import create_repair_receipt
from agent_worktree_fingerprint import worktree_fingerprint
from agent_worker_evidence import reserve_isolated_worker_evidence


class ExecutionCapsuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.project = self.root / "project"
        self.rules = self.root / "rules"
        self._init_repository(self.project, {"app.txt": "app\n"})
        self._init_repository(self.rules, {"guide.md": "# Guide\n"})
        self.route = {
            "command": "task",
            "platform": None,
            "concerns": ["automation"],
            "docs": ["guide.md"],
            "required_docs": ["guide.md"],
            "reference_docs": [],
            "gates": ["verify"],
        }
        self.evidence_path = self.project / ".tao" / "preflight.json"
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_text(
            json.dumps(
                {
                    "project": str(self.project.resolve()),
                    "rules": str(self.rules.resolve()),
                    "route": self.route,
                }
            ),
            encoding="utf-8",
        )
        self._write_ledger()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_ready_capsule_is_valid_and_content_free(self) -> None:
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)

        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        self.assertEqual("ready", capsule["phase"])
        self.assertEqual(REUSE_POLICY, capsule["reuse_policy"])
        self.assertEqual(
            {"path": "guide.md", "size_bytes": 8, "sha256": self._sha256(self.rules / "guide.md")},
            capsule["required_docs"][0],
        )
        self.assertEqual(self.evidence_path.name, capsule["preflight_evidence"]["filename"])
        self.assertEqual(ledger_path.name, capsule["gate_ledger"]["filename"])
        self.assertEqual([], validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route))
        serialized = json.dumps(capsule)
        self.assertNotIn(str(self.project), serialized)
        self.assertNotIn(str(self.rules), serialized)
        self.assertNotIn("git status", serialized)

    def test_capsule_binds_an_explicit_request_fingerprint(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["request_intake"] = {
            "request": "inspect current lifecycle cost",
            "request_classified": True,
            "classification_evidence": "clear-scoped",
        }
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        self.assertRegex(capsule["request_fingerprint"], r"^[0-9a-f]{64}$")
        preflight["request_intake"]["request"] = "implement lifecycle optimization"
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()

        failures = validate_execution_capsule(
            capsule, self.project, self.rules, self.evidence_path, self.route
        )
        self.assertIn("execution capsule request fingerprint does not match", failures)

    def test_shared_git_repository_state_is_fingerprinted_once(self) -> None:
        state = {
            "head": "a" * 40,
            "worktree_fingerprint": "b" * 64,
            "worktree_signature": "c" * 64,
        }
        with patch("agent_execution_capsule_state.git_repository_root", return_value=self.project), patch(
            "agent_execution_capsule_state.git_state", return_value=state
        ) as capture:
            project_state, rules_state = git_states_for_paths(self.project, self.rules)

        self.assertEqual(state, project_state)
        self.assertEqual(state, rules_state)
        self.assertEqual(1, capture.call_count)

    def test_non_git_rules_root_uses_bounded_directory_fingerprint(self) -> None:
        plain_rules = self.root / "plain-rules"
        plain_rules.mkdir()
        (plain_rules / "guide.md").write_text("# Guide\n", encoding="utf-8")
        (plain_rules / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.rules = plain_rules
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["rules"] = str(self.rules.resolve())
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()

        capsule = refresh_execution_capsule(
            self.project,
            self.rules,
            self.evidence_path,
            self.route,
        )

        self.assertEqual(DIRECTORY_STATE_HEAD, capsule["rules_git"]["head"])
        self.assertEqual(
            [],
            validate_execution_capsule(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            ),
        )

        generated = self.rules / "graphify-out"
        generated.mkdir()
        (generated / "cache.json").write_text("{}", encoding="utf-8")
        self.assertEqual(
            [],
            validate_execution_capsule(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            ),
        )

        (self.rules / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
        failures = validate_execution_capsule(
            capsule,
            self.project,
            self.rules,
            self.evidence_path,
            self.route,
        )
        self.assertIn("execution capsule rules worktree status changed", failures)

    def test_validation_uses_one_shared_git_state_capture(self) -> None:
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)
        capsule["rules_git"] = dict(capsule["project_git"])
        with patch(
            "agent_execution_capsule_validation.git_states_for_paths",
            return_value=(capsule["project_git"], capsule["project_git"]),
        ) as capture:
            failures = validate_execution_capsule(
                capsule, self.project, self.rules, self.evidence_path, self.route
            )

        self.assertEqual([], failures)
        capture.assert_called_once_with(
            self.project.resolve(),
            self.rules.resolve(),
            project_record=capsule["project_git"],
            rules_record=capsule["rules_git"],
        )

    def test_unchanged_capsule_validation_skips_repeated_strong_capture(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )

        with patch(
            "agent_execution_capsule_state.capture_worktree_state",
            side_effect=AssertionError("unchanged capsule must reuse its strong fingerprint"),
        ):
            failures = validate_execution_capsule(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            )

        self.assertEqual([], failures)

    def test_oversized_untracked_change_invalidates_capsule_without_crashing(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.project / "large-local.bin").write_bytes(b"1234")

        with patch("agent_worktree_fingerprint.MAX_UNTRACKED_BYTES", 3):
            failures = validate_execution_capsule(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            )

        self.assertIn(
            "execution capsule worktree exceeds bounded fingerprint limits", failures
        )

    def test_serial_preflight_snapshot_preserves_source_docs_without_a_capsule(self) -> None:
        self.route = {**self.route, "gates": ["source docs"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        snapshot = create_preflight_snapshot(
            self.rules,
            self.route,
            preflight.get("request_intake") or {},
        )
        preflight["execution_snapshot"] = snapshot
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()

        self.assertIsNotNone(preflight_snapshot_binding_fingerprint(snapshot))
        self.assertEqual(
            [],
            validate_preflight_snapshot(
                snapshot,
                self.project,
                self.evidence_path,
                self.rules,
                self.route,
            ),
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                self.route,
                self.project,
                self.rules,
                self.evidence_path,
                {},
                {},
            ),
        )
        (self.rules / "guide.md").write_text("# Changed Guide\n", encoding="utf-8")
        failures = validate_preflight_snapshot(
            snapshot, self.project, self.evidence_path, self.rules, self.route
        )
        self.assertIn("execution capsule required doc hash changed: guide.md", failures)

    def test_new_serial_preflight_ignores_a_stale_previous_task_capsule(self) -> None:
        old_route = {**self.route, "gates": ["source docs"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = old_route
        preflight["request_intake"] = {"request": "previous task"}
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        stale_capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, old_route
        )

        self.route = {**self.route, "gates": ["source docs", "verify"]}
        preflight["route"] = self.route
        preflight["request_intake"] = {"request": "current serial task"}
        snapshot = create_preflight_snapshot(self.rules, self.route, preflight["request_intake"])
        preflight["execution_snapshot"] = snapshot
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        snapshot_binding = preflight_snapshot_binding_fingerprint(snapshot)

        self.assertNotEqual(
            execution_capsule_binding_fingerprint(stale_capsule), snapshot_binding
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                self.route,
                self.project,
                self.rules,
                self.evidence_path,
                {"source docs": "current docs read", "verify": "current check passed"},
                {"capsule_bindings": {"source docs": snapshot_binding, "verify": snapshot_binding}},
            ),
        )

    def test_new_analysis_preflight_ignores_a_stale_handoff_capsule(self) -> None:
        analysis_route = {
            **self.route,
            "command": "analysis",
            "docs": [],
            "required_docs": [],
            "gates": ["request intake", "investigate", "report"],
        }
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = analysis_route
        preflight["request_intake"] = {"request": "analysis A"}
        preflight["execution_snapshot"] = create_preflight_snapshot(
            self.rules,
            analysis_route,
            preflight["request_intake"],
        )
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self.route = analysis_route
        self._write_ledger()
        stale_handoff_capsule = refresh_execution_capsule(
            self.project,
            self.rules,
            self.evidence_path,
            analysis_route,
        )

        preflight["request_intake"] = {"request": "analysis B"}
        current_snapshot = create_preflight_snapshot(
            self.rules,
            analysis_route,
            preflight["request_intake"],
        )
        preflight["execution_snapshot"] = current_snapshot
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        current_binding = preflight_snapshot_binding_fingerprint(current_snapshot)

        self.assertNotEqual(
            execution_capsule_binding_fingerprint(stale_handoff_capsule),
            current_binding,
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                analysis_route,
                self.project,
                self.rules,
                self.evidence_path,
                {
                    "request intake": "analysis B intake complete",
                    "investigate": "analysis B investigation complete",
                    "report": "analysis B report complete",
                },
                {
                    "capsule_bindings": {
                        "request intake": current_binding,
                        "investigate": current_binding,
                        "report": current_binding,
                    }
                },
            ),
        )

    def test_final_checks_reuse_only_a_current_review_validation(self) -> None:
        record_successful_review_workflow_validation(
            self.project,
            self.rules,
            self.evidence_path,
            {"returncode": 0},
            {"returncode": 0},
            "pathspec: docs/example.md",
        )

        with patch(
            "agent_execution_capsule_state.capture_worktree_state",
            side_effect=AssertionError("finish must not repeat the review strong scan"),
        ):
            reused = reusable_review_workflow_validation(self.project, self.rules)
        self.assertIsNotNone(reused)
        self.assertTrue(reused["reused"])

        with patch(
            "agent_finish_final_checks.run_workflow_validate",
            side_effect=AssertionError("finish must reuse the review validation"),
        ), patch(
            "agent_finish_final_checks.cached_vibeguard",
            return_value={"returncode": 0, "overall": {"status": "Ready"}},
        ), patch(
            "agent_finish_final_checks.run_command",
            side_effect=AssertionError("finish must reuse the current review diff check"),
        ):
            validate, diff_check, _, _ = run_final_checks(
                ROOT,
                self.project,
                self.rules,
                None,
                [],
                [],
            )
        self.assertTrue(validate["reused"])
        self.assertTrue(diff_check["skipped"])
        self.assertIn("pathspec: docs/example.md", diff_check["review_note"])

        (self.project / "app.txt").write_text("changed\n", encoding="utf-8")
        self.assertIsNone(reusable_review_workflow_validation(self.project, self.rules))

    def test_capsule_without_required_doc_stays_preflight_and_is_not_reusable(self) -> None:
        (self.rules / "guide.md").unlink()
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        self.assertEqual("preflight", capsule["phase"])
        self.assertEqual([], capsule["required_docs"])
        self.assertIn(
            "execution capsule phase is not ready",
            validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route),
        )

    def test_document_free_route_creates_a_ready_empty_manifest(self) -> None:
        route = {**self.route, "docs": [], "required_docs": []}
        self.route = route
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()

        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, route
        )

        self.assertEqual("ready", capsule["phase"])
        self.assertEqual([], capsule["required_docs"])
        self.assertEqual(
            [],
            validate_execution_capsule(
                capsule, self.project, self.rules, self.evidence_path, route
            ),
        )
        self.assertEqual(
            [],
            validate_source_docs_binding(
                capsule, self.project, self.rules, self.evidence_path, route
            ),
        )

    def test_validation_detects_stale_project_and_rules_git_state(self) -> None:
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        (self.project / "app.txt").write_text("changed\n", encoding="utf-8")
        (self.rules / "guide.md").write_text("# Changed Guide\n", encoding="utf-8")
        failures = validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route)

        self.assertIn("execution capsule project worktree status changed", failures)
        self.assertIn("execution capsule rules worktree status changed", failures)
        self.assertIn("execution capsule required doc hash changed: guide.md", failures)

    def test_source_docs_binding_allows_implementation_changes_but_rejects_stale_docs(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.project / "app.txt").write_text("implementation changed\n", encoding="utf-8")

        self.assertEqual(
            [],
            validate_source_docs_binding(
                capsule, self.project, self.rules, self.evidence_path, self.route
            ),
        )

        (self.rules / "guide.md").write_text("# Changed Guide\n", encoding="utf-8")
        failures = validate_source_docs_binding(
            capsule, self.project, self.rules, self.evidence_path, self.route
        )

        self.assertIn("execution capsule required doc hash changed: guide.md", failures)

    def test_non_source_docs_route_keeps_gate_binding_without_doc_snapshot_check(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            evidence="focused test passed",
        )
        (self.rules / "guide.md").write_text("# Changed Guide\n", encoding="utf-8")
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertEqual(
            execution_capsule_binding_fingerprint(capsule),
            diagnostics["capsule_bindings"]["verify"],
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                self.route,
                self.project,
                self.rules,
                self.evidence_path,
                gate_evidence,
                diagnostics,
            ),
        )

    def test_source_docs_route_rejects_changed_required_doc_snapshot(self) -> None:
        self.route = {**self.route, "gates": ["source docs", "verify"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.rules / "guide.md").write_text("# Changed Guide\n", encoding="utf-8")

        failures = route_gate_capsule_binding_failures(
            self.route,
            self.project,
            self.rules,
            self.evidence_path,
            {},
            {},
        )

        self.assertIn("execution capsule required doc hash changed: guide.md", failures)

    def test_source_docs_binding_allows_only_an_explicit_required_doc_update(self) -> None:
        self.route = {**self.route, "gates": ["documentation", "verify"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.rules / "guide.md").write_text("# Updated Guide\n", encoding="utf-8")
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        entry = record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="documentation",
            fields={
                "decision": "updated",
                "target": "guide.md",
                "reason": "the required guide is the intentional task artifact",
                "baseline_sha256": "0" * 64,
                "final_sha256": "0" * 64,
            },
        )

        self.assertEqual("1", entry["fields"]["artifact_receipt_version"])
        self.assertEqual(
            capsule["required_docs"][0]["sha256"],
            entry["fields"]["baseline_sha256"],
        )
        self.assertEqual(
            self._sha256(self.rules / "guide.md"),
            entry["fields"]["final_sha256"],
        )
        self.assertEqual(
            str((self.rules / "guide.md").stat().st_size),
            entry["fields"]["final_size_bytes"],
        )

        documented_updates = documented_required_doc_updates(
            evidence_path=self.evidence_path,
            route=self.route,
        )

        self.assertEqual(
            entry["fields"]["final_sha256"],
            documented_updates["guide.md"]["final_sha256"],
        )
        self.assertEqual(
            [],
            validate_source_docs_binding(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
                documented_updates=documented_updates,
            ),
        )

        (self.rules / "guide.md").write_text(
            "# Changed After Documentation Evidence\n",
            encoding="utf-8",
        )
        failures = validate_source_docs_binding(
            capsule,
            self.project,
            self.rules,
            self.evidence_path,
            self.route,
            documented_updates=documented_updates,
        )

        self.assertIn(
            "execution capsule required doc changed after documentation evidence: guide.md",
            failures,
        )

    def test_off_route_documentation_cannot_bind_without_verified_repair(self) -> None:
        self.route = {
            **self.route,
            "gates": ["source docs", "verify"],
        }
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.rules / "guide.md").write_text("# Repaired Guide\n", encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError,
            "requires resume_checkpoint and repair_evidence",
        ):
            record_gate_evidence(
                evidence_path=self.evidence_path,
                preflight=preflight,
                gate="documentation",
                fields={
                    "decision": "updated",
                    "target": "guide.md",
                    "reason": "an unverified off-route entry must grant nothing",
                },
            )
        with self.assertRaisesRegex(ValueError, "requires an actual failed checkpoint"):
            record_gate_evidence(
                evidence_path=self.evidence_path,
                preflight=preflight,
                gate="documentation",
                fields={
                    "decision": "updated",
                    "target": "guide.md",
                    "reason": "fields alone cannot invent a failed checkpoint",
                    "resume_checkpoint": "source docs",
                    "repair_evidence": ".tao/repair-verification/missing.json",
                },
            )
        record_failure_checkpoints(
            evidence_path=self.evidence_path,
            preflight=preflight,
            checkpoints=["source docs"],
            signature="required-doc-drift",
            checkpoint_signatures={"source docs": "required-doc-drift"},
        )
        with self.assertRaisesRegex(ValueError, "repair evidence is invalid"):
            record_gate_evidence(
                evidence_path=self.evidence_path,
                preflight=preflight,
                gate="documentation",
                fields={
                    "decision": "updated",
                    "target": "guide.md",
                    "reason": "a failed checkpoint still needs a verified receipt",
                    "resume_checkpoint": "source docs",
                    "repair_evidence": ".tao/repair-verification/missing.json",
                },
            )

        self.assertEqual(
            {},
            documented_required_doc_updates(
                evidence_path=self.evidence_path,
                route=self.route,
            ),
        )
        self.assertIn(
            "execution capsule required doc hash changed: guide.md",
            validate_source_docs_binding(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
                documented_updates={},
            ),
        )

    def test_failed_route_can_bind_required_doc_after_verified_repair(self) -> None:
        self.route = {
            **self.route,
            "gates": ["source docs", "verify"],
        }
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.rules / "guide.md").write_text("# Repaired Guide\n", encoding="utf-8")
        (self.rules / "test_repair.py").write_text(
            "import unittest\n\n"
            "class RepairTest(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        record_failure_checkpoints(
            evidence_path=self.evidence_path,
            preflight=preflight,
            checkpoints=["source docs"],
            signature="required-doc-drift",
            checkpoint_signatures={"source docs": "required-doc-drift"},
        )
        repair = create_repair_receipt(
            project=self.project,
            rules=self.rules,
            evidence_path=self.evidence_path,
            preflight=preflight,
            target="guide.md",
            checkpoint="source docs",
            verification_kind="unittest",
            test_selector="test_repair.RepairTest.test_ok",
        )
        self.assertTrue(repair["created"])
        self.assertEqual("SUCCESS", repair["status"])

        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="documentation",
            fields={
                "decision": "updated",
                "target": "guide.md",
                "reason": "the failed checkpoint required an instruction repair",
                "resume_checkpoint": "source docs",
                "repair_evidence": repair["receipt_path"],
            },
        )
        documented_updates = documented_required_doc_updates(
            evidence_path=self.evidence_path,
            route=self.route,
        )

        self.assertEqual({"guide.md"}, set(documented_updates))
        self.assertEqual(
            [],
            validate_source_docs_binding(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
                documented_updates=documented_updates,
            ),
        )

    def test_git_repository_error_is_not_downgraded_to_non_git(self) -> None:
        with (
            patch.object(
                capsule_state,
                "git_repository_root",
                side_effect=RuntimeError("dubious ownership"),
            ),
            patch.object(capsule_state, "is_non_git_workspace", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "dubious ownership"):
                capsule_state._git_repository_root_or_none(self.project)

    def test_genuine_non_git_path_uses_directory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state, duplicate = git_states_for_paths(project, project)

        self.assertEqual(DIRECTORY_STATE_HEAD, state["head"])
        self.assertEqual(state, duplicate)

    def test_documentation_gate_cannot_mint_a_receipt_for_a_non_required_doc_target(self) -> None:
        # Required-doc receipts are exact-path capabilities. Even a documentation
        # entry carrying repair-like prose cannot authorize an unrelated target.
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        (self.rules / "guide.md").write_text("# Updated Guide\n", encoding="utf-8")
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))

        entry = record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="documentation",
            fields={
                "decision": "updated",
                "target": "notes.md",
                "reason": "a non-required artifact must not grant this capability",
            },
        )
        documented_updates = documented_required_doc_updates(
            evidence_path=self.evidence_path,
            route=self.route,
        )

        self.assertNotIn("artifact_receipt_version", entry["fields"])
        self.assertEqual({}, documented_updates)
        self.assertIn(
            "execution capsule required doc hash changed: guide.md",
            validate_source_docs_binding(
                capsule,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
                documented_updates=documented_updates,
            ),
        )

    def test_serial_snapshot_binds_an_explicit_required_doc_update_receipt(self) -> None:
        self.route = {**self.route, "gates": ["source docs", "documentation"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        snapshot = create_preflight_snapshot(
            self.rules,
            self.route,
            preflight.get("request_intake") or {},
        )
        preflight["execution_snapshot"] = snapshot
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        (self.rules / "guide.md").write_text("# Serial Update\n", encoding="utf-8")

        entry = record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="documentation",
            fields={
                "decision": "updated",
                "target": "guide.md",
                "reason": "the serial task intentionally updates its required guide",
            },
        )
        documented_updates = documented_required_doc_updates(
            evidence_path=self.evidence_path,
            route=self.route,
        )

        self.assertEqual(
            snapshot["required_docs"][0]["sha256"],
            entry["fields"]["baseline_sha256"],
        )
        self.assertEqual(
            [],
            validate_preflight_snapshot(
                snapshot,
                self.project,
                self.evidence_path,
                self.rules,
                self.route,
                documented_updates=documented_updates,
            ),
        )

    def test_every_route_gate_requires_the_current_execution_capsule_binding(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            evidence="focused test passed",
            source="manual",
        )
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertEqual(
            execution_capsule_binding_fingerprint(capsule),
            diagnostics["capsule_bindings"]["verify"],
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                self.route,
                self.project,
                self.rules,
                self.evidence_path,
                gate_evidence,
                diagnostics,
            ),
        )

        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][-1]["fields"].pop("execution_capsule_binding")
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        failures = route_gate_capsule_binding_failures(
            self.route,
            self.project,
            self.rules,
            self.evidence_path,
            gate_evidence,
            diagnostics,
        )
        self.assertIn(
            "gate evidence for verify is not bound to the current execution capsule",
            failures,
        )

    def test_cli_override_without_a_persisted_binding_is_rejected(self) -> None:
        refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        failures = route_gate_capsule_binding_failures(
            self.route,
            self.project,
            self.rules,
            self.evidence_path,
            {"verify": "cli fallback"},
            {"sources": {"verify": "cli override"}, "capsule_bindings": {}},
        )

        self.assertIn(
            "gate evidence for verify is not bound to the current execution capsule",
            failures,
        )

    def test_ledger_merge_has_no_cli_override_input(self) -> None:
        with self.assertRaises(TypeError):
            merge_gate_evidence_from_ledger(
                route=self.route,
                evidence_path=self.evidence_path,
                cli_gate_evidence={"verify": "unpersisted fallback"},
            )

    def test_latest_failed_gate_invalidates_an_earlier_success(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            status="SUCCESS",
            evidence="focused check passed",
        )
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            status="FAIL",
            evidence="focused check exposed a regression",
        )
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertNotIn("verify", gate_evidence)
        self.assertEqual(
            "focused check exposed a regression",
            diagnostics["failed_gates"]["verify"]["evidence"],
        )
        self.assertEqual(
            {},
            latest_successful_gate_fields(
                route=self.route,
                evidence_path=self.evidence_path,
                gate="verify",
            ),
        )

    def test_later_success_restores_a_failed_gate(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        for status, evidence in (
            ("SUCCESS", "initial check passed"),
            ("FAIL", "regression found"),
            ("SUCCESS", "repaired check passed"),
        ):
            record_gate_evidence(
                evidence_path=self.evidence_path,
                preflight=preflight,
                gate="verify",
                status=status,
                evidence=evidence,
            )

        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertEqual("repaired check passed", gate_evidence["verify"])
        self.assertNotIn("verify", diagnostics["failed_gates"])

    def test_later_incomplete_success_cannot_reuse_older_complete_fields(self) -> None:
        self.route = {**self.route, "gates": ["tests"]}
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        self._write_ledger()
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="tests",
            fields={"check": "focused tests", "result": "PASS"},
        )
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="tests",
            fields={"check": "changed but incomplete test run"},
        )

        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertNotIn("tests", gate_evidence)
        self.assertEqual(["result"], diagnostics["missing_fields"]["tests"])
        self.assertIn(
            "structured gate evidence for tests is incomplete: result",
            incomplete_gate_evidence_failures(diagnostics),
        )

    def test_malformed_latest_status_fails_closed_over_older_success(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            status="SUCCESS",
            evidence="initial verification passed",
        )
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["entries"].append(
            {
                "gate": "verify",
                "status": "UNKNOWN",
                "source": "malformed external state",
                "evidence": "must not preserve the older success",
                "fields": {},
            }
        )
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertNotIn("verify", gate_evidence)
        self.assertEqual("UNKNOWN", diagnostics["invalid_statuses"]["verify"])
        self.assertIn(
            "structured gate evidence for verify has invalid status: UNKNOWN",
            incomplete_gate_evidence_failures(diagnostics),
        )

    def test_sync_after_preflight_gate_binding_keeps_capsule_reusable(self) -> None:
        self.route = {**self.route, "gates": ["request intake", "verify"]}
        preflight_payload = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight_payload["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight_payload), encoding="utf-8")
        self._write_ledger()
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(1, bind_gate_evidence_to_capsule(
            evidence_path=self.evidence_path,
            preflight=preflight,
        ))
        synchronized = synchronize_execution_capsule_gate_ledger(
            capsule,
            self.evidence_path,
        )

        self.assertEqual(
            [],
            validate_execution_capsule(
                synchronized,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            ),
        )

    def test_sync_after_handoff_rebinding_keeps_all_route_gates_current(self) -> None:
        self.route = {**self.route, "gates": ["request intake", "verify"]}
        preflight_payload = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight_payload["route"] = self.route
        self.evidence_path.write_text(json.dumps(preflight_payload), encoding="utf-8")
        self._write_ledger()
        first_capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        bind_gate_evidence_to_capsule(evidence_path=self.evidence_path, preflight=preflight)
        synchronize_execution_capsule_gate_ledger(first_capsule, self.evidence_path)
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="verify",
            evidence="first verification passed",
        )

        (self.rules / "guide.md").write_text("# Updated Guide\n", encoding="utf-8")
        refreshed = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        self.assertEqual(2, bind_gate_evidence_to_capsule(
            evidence_path=self.evidence_path,
            preflight=preflight,
        ))
        synchronized = synchronize_execution_capsule_gate_ledger(
            refreshed,
            self.evidence_path,
        )
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=self.evidence_path,
        )

        self.assertEqual(
            [],
            validate_execution_capsule(
                synchronized,
                self.project,
                self.rules,
                self.evidence_path,
                self.route,
            ),
        )
        self.assertEqual(
            [],
            route_gate_capsule_binding_failures(
                self.route,
                self.project,
                self.rules,
                self.evidence_path,
                gate_evidence,
                diagnostics,
            ),
        )

    def test_lexical_symlink_aliases_do_not_invalidate_evidence_bindings(self) -> None:
        physical_root = self.root.resolve()
        private_var = Path("/private/var")
        public_var = Path("/var")
        if not str(physical_root).startswith(f"{private_var}/") or not public_var.is_dir():
            self.skipTest("the platform does not expose a /var lexical alias")
        alias_root = public_var / physical_root.relative_to(private_var)
        alias_project = alias_root / "project"
        alias_rules = alias_root / "rules"
        alias_evidence = alias_project / ".tao" / "preflight.json"

        capsule = refresh_execution_capsule(
            alias_project,
            alias_rules,
            alias_evidence,
            self.route,
        )

        self.assertEqual(
            [],
            validate_execution_capsule(
                capsule,
                alias_project,
                alias_rules,
                alias_evidence,
                self.route,
            ),
        )

    def test_validation_detects_different_content_with_same_dirty_status(self) -> None:
        (self.project / "app.txt").write_text("dirty one\n", encoding="utf-8")
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        (self.project / "app.txt").write_text("dirty two\n", encoding="utf-8")
        failures = validate_execution_capsule(
            capsule, self.project, self.rules, self.evidence_path, self.route
        )

        self.assertIn("execution capsule project worktree status changed", failures)

    def test_validation_detects_staged_and_untracked_content_changes(self) -> None:
        staged = self.project / "app.txt"
        staged.write_text("staged one\n", encoding="utf-8")
        self._git(self.project, "add", "app.txt")
        staged_capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        staged.write_text("staged two\n", encoding="utf-8")
        self._git(self.project, "add", "app.txt")
        staged_failures = validate_execution_capsule(
            staged_capsule, self.project, self.rules, self.evidence_path, self.route
        )

        self.assertIn("execution capsule project worktree status changed", staged_failures)

        untracked = self.project / "local-note.txt"
        untracked.write_text("untracked one\n", encoding="utf-8")
        untracked_capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        untracked.write_text("untracked two\n", encoding="utf-8")
        untracked_failures = validate_execution_capsule(
            untracked_capsule, self.project, self.rules, self.evidence_path, self.route
        )

        self.assertIn("execution capsule project worktree status changed", untracked_failures)

    def test_capsule_hashing_streams_files_without_path_read_bytes(self) -> None:
        (self.project / "large-local.bin").write_bytes(b"x" * (2 * 1024 * 1024))

        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
            capsule = refresh_execution_capsule(
                self.project, self.rules, self.evidence_path, self.route
            )

        self.assertEqual("ready", capsule["phase"])

    def test_worktree_fingerprint_tolerates_untracked_file_removed_mid_scan(self) -> None:
        transient = self.project / "transient.txt"
        transient.write_text("present\n", encoding="utf-8")
        original_lstat = Path.lstat

        def raced_lstat(path: Path):
            if path == transient:
                transient.unlink()
                raise FileNotFoundError(path)
            return original_lstat(path)

        with patch.object(Path, "lstat", raced_lstat):
            fingerprint = worktree_fingerprint(self.project)

        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

    def test_reusable_worker_environment_cannot_write_parent_gate_evidence(self) -> None:
        with patch.dict("os.environ", {"TAO_PARENT_EVIDENCE_READONLY": "1"}):
            with self.assertRaisesRegex(PermissionError, "cannot write parent"):
                from agent_gate_evidence import record_gate_evidence

                record_gate_evidence(
                    evidence_path=self.evidence_path,
                    preflight=json.loads(self.evidence_path.read_text(encoding="utf-8")),
                    gate="verify",
                    evidence="worker tried to write parent evidence",
                )

    def test_reserved_worker_preflight_stays_in_the_valid_evidence_root(self) -> None:
        worker_evidence, _, _ = reserve_isolated_worker_evidence(
            self.project,
            self.evidence_path,
        )
        worker_evidence.write_text(
            self.evidence_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        self.assertEqual(
            (self.project / ".tao" / "workers").resolve(),
            worker_evidence.parent.parent.resolve(),
        )
        self.assertEqual(
            [],
            preflight_identity_failures(
                worker_evidence,
                self.project.resolve(),
                self.rules.resolve(),
            ),
        )

    def test_validation_detects_stale_project_and_rules_heads(self) -> None:
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        self._commit_change(self.project, "app.txt", "new app\n")
        self._commit_change(self.rules, "other.md", "new rules file\n")
        failures = validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route)

        self.assertIn("execution capsule project git HEAD changed", failures)
        self.assertIn("execution capsule rules git HEAD changed", failures)

    def test_validation_rejects_identical_clone_with_foreign_parent_evidence(self) -> None:
        capsule = refresh_execution_capsule(
            self.project, self.rules, self.evidence_path, self.route
        )
        clone = self.root / "project-clone"
        self._git(self.root, "clone", "--local", str(self.project), str(clone))

        failures = validate_execution_capsule(
            capsule,
            clone,
            self.rules,
            self.evidence_path,
            self.route,
        )

        self.assertIn(
            "execution capsule preflight project identity does not match", failures
        )
        self.assertIn(
            "execution capsule preflight evidence is outside the current project evidence root",
            failures,
        )

    def test_validation_detects_stale_evidence_doc_and_ledger(self) -> None:
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        capsule = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)

        self.evidence_path.write_text(json.dumps({"route": self.route}, indent=2), encoding="utf-8")
        (self.rules / "guide.md").write_text("# Guide changed\n", encoding="utf-8")
        ledger_path.write_text(json.dumps({"changed": True}), encoding="utf-8")
        failures = validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route)

        self.assertIn("execution capsule preflight evidence hash does not match", failures)
        self.assertIn("execution capsule required doc hash changed: guide.md", failures)
        self.assertIn("execution capsule gate ledger hash does not match", failures)

    def test_ready_requires_current_structurally_valid_parent_ledger(self) -> None:
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        ledger_path.unlink()
        missing = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)
        self.assertEqual("preflight", missing["phase"])
        self.assertIn(
            "execution capsule parent gate ledger is missing",
            validate_execution_capsule(
                missing, self.project, self.rules, self.evidence_path, self.route
            ),
        )

        ledger_path.write_text("{not-json", encoding="utf-8")
        malformed = refresh_execution_capsule(self.project, self.rules, self.evidence_path, self.route)
        self.assertEqual("preflight", malformed["phase"])
        self.assertIn(
            "execution capsule parent gate ledger is not valid JSON",
            validate_execution_capsule(
                malformed, self.project, self.rules, self.evidence_path, self.route
            ),
        )

    def test_ready_rejects_each_stale_parent_ledger_binding(self) -> None:
        cases = {
            "schema_version": ("schema_version", 2, "schema does not match"),
            "preflight_path": ("preflight_evidence", "other.json", "preflight path does not match"),
            "preflight_hash": ("preflight_evidence_sha256", "0" * 64, "preflight hash does not match"),
            "route": ("route_fingerprint", "0" * 64, "route does not match"),
            "request_intake": ("entries", [], "lacks request intake SUCCESS evidence"),
        }
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        for label, (field, value, expected) in cases.items():
            with self.subTest(label=label):
                ledger = self._ledger_payload()
                ledger[field] = value
                ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
                capsule = refresh_execution_capsule(
                    self.project, self.rules, self.evidence_path, self.route
                )
                failures = validate_execution_capsule(
                    capsule, self.project, self.rules, self.evidence_path, self.route
                )
                self.assertEqual("preflight", capsule["phase"])
                self.assertTrue(any(expected in failure for failure in failures), failures)

    def test_malformed_capsule_fails_closed_with_deterministic_reason(self) -> None:
        capsule_path = capsule_path_for_evidence(self.evidence_path)
        capsule_path.write_text("{not-json", encoding="utf-8")

        capsule = read_execution_capsule(capsule_path)

        self.assertEqual({"invalid_json": True}, capsule)
        self.assertEqual(
            ["execution capsule is not valid JSON"],
            validate_execution_capsule(capsule, self.project, self.rules, self.evidence_path, self.route),
        )

    def test_custom_preflight_path_gets_isolated_capsule(self) -> None:
        default_path = capsule_path_for_evidence(self.evidence_path)
        custom_evidence = self.evidence_path.with_name("worker-a.json")

        self.assertEqual(self.evidence_path.parent / "execution-capsule.json", default_path)
        self.assertEqual(self.evidence_path.parent / "worker-a-execution-capsule.json", capsule_path_for_evidence(custom_evidence))

    def test_cli_refresh_and_check_use_atomic_output(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "agent_execution_capsule.py"),
            "refresh",
            "--project",
            str(self.project),
            "--rules",
            str(self.rules),
            "--evidence",
            str(self.evidence_path),
        ]

        refreshed = subprocess.run(command, check=False, capture_output=True, text=True)
        checked = subprocess.run(
            [*command[:2], "check", *command[3:]],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, refreshed.returncode, refreshed.stderr + refreshed.stdout)
        self.assertEqual("ready", json.loads(refreshed.stdout)["phase"])
        self.assertEqual(0, checked.returncode, checked.stderr + checked.stdout)
        self.assertTrue(json.loads(checked.stdout)["reusable"])
        self.assertFalse(list(self.evidence_path.parent.glob("*.tmp")))

    def _write_ledger(self) -> Path:
        ledger_path = gate_evidence_path_for_preflight(self.evidence_path)
        ledger_path.write_text(json.dumps(self._ledger_payload()), encoding="utf-8")
        return ledger_path

    def _ledger_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "created_at": "2026-07-14T00:00:00+00:00",
            "preflight_evidence": str(self.evidence_path),
            "preflight_evidence_sha256": preflight_evidence_sha256(self.evidence_path),
            "route_fingerprint": route_fingerprint(self.route),
            "entries": [
                {
                    "created_at": "2026-07-14T00:00:00+00:00",
                    "gate": "request intake",
                    "status": "SUCCESS",
                    "source": "start",
                    "evidence": "preflight request intake completed",
                    "fields": {"classification_evidence": "clear-scoped"},
                }
            ],
        }

    def _init_repository(self, path: Path, files: dict[str, str]) -> None:
        path.mkdir(parents=True)
        (path / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        for relative, content in files.items():
            destination = path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        self._git(path, "init", "-q")
        self._git(path, "config", "user.email", "tests@example.invalid")
        self._git(path, "config", "user.name", "Tao Agent OS Tests")
        self._git(path, "add", "-A")
        self._git(path, "commit", "-qm", "initial")

    def _commit_change(self, path: Path, relative: str, content: str) -> None:
        destination = path / relative
        destination.write_text(content, encoding="utf-8")
        self._git(path, "add", relative)
        self._git(path, "commit", "-qm", "change")

    def _git(self, path: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _sha256(self, path: Path) -> str:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
