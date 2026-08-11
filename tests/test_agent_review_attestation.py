from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_finish_check_steps import enforce_review_hook_attestation
from agent_gate_evidence import (
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    reset_gate_evidence_ledger,
)
from agent_review_attestation import ReviewAttestation


def load_finish_check_module():
    spec = importlib.util.spec_from_file_location(
        "agent_finish_check_entrypoint",
        SCRIPTS / "agent-finish-check.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-finish-check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def initialize_repository(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    (project / "tracked.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=project,
        check=True,
    )


class ReviewAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.project = Path(self.temporary_directory.name)
        initialize_repository(self.project)
        self.route = {"command": "review", "gates": ["review hook"]}
        self.evidence_path = self._write_preflight("a" * 32)

    def _write_preflight(self, run_id: str) -> Path:
        evidence_path = self.project / ".tao" / "runs" / run_id / "preflight.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        preflight = {
            "agent_run_id": run_id,
            "project": str(self.project),
            "rules": str(self.project),
            "route": self.route,
        }
        evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        reset_gate_evidence_ledger(evidence_path, preflight)
        return evidence_path

    def _record_real_review(self, evidence_path: Path | None = None) -> dict[str, object]:
        selected = evidence_path or self.evidence_path
        preflight = json.loads(selected.read_text(encoding="utf-8"))
        attestation = ReviewAttestation.record(
            project=self.project,
            rules=self.project,
            evidence_path=selected,
            preflight=preflight,
            review_scope="pathspec: tracked.txt",
            review_paths=["tracked.txt"],
            changed_path_count=0,
            checks={
                "review_outcome": "pass",
                "workflow_validate": {"returncode": 0},
                "diff_check": {"returncode": 0},
                "vibeguard": {"returncode": 0, "overall": "Ready"},
            },
        )
        record_gate_evidence(
            evidence_path=selected,
            preflight=preflight,
            gate="review hook",
            evidence="review hook completed successfully and left worktree unchanged",
            fields=ReviewAttestation.ledger_fields(attestation),
            status="SUCCESS",
            source="review",
        )
        return attestation

    def _finish_merge(self, evidence_path: Path | None = None) -> tuple[dict[str, str], dict[str, object], list[str]]:
        selected = evidence_path or self.evidence_path
        gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
            route=self.route,
            evidence_path=selected,
        )
        failures: list[str] = []
        enforce_review_hook_attestation(
            route=self.route,
            project=self.project,
            rules=self.project,
            evidence_path=selected,
            gate_evidence=gate_evidence,
            gate_evidence_ledger=diagnostics,
            failures=failures,
        )
        return gate_evidence, diagnostics, failures

    def test_finish_accepts_only_the_current_real_review_attestation(self) -> None:
        self._record_real_review()

        gate_evidence, diagnostics, failures = self._finish_merge()

        self.assertIn("review hook", gate_evidence)
        self.assertEqual([], failures)
        self.assertTrue(diagnostics["review_attestation"]["valid"])

    def test_review_cannot_attest_an_unbound_legacy_preflight(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        preflight.pop("agent_run_id")

        with self.assertRaisesRegex(ValueError, "requires a bound agent run id"):
            ReviewAttestation.record(
                project=self.project,
                rules=self.project,
                evidence_path=self.evidence_path,
                preflight=preflight,
                review_scope="working-tree",
                review_paths=[],
                changed_path_count=0,
                checks={
                    "review_outcome": "pass",
                    "workflow_validate": {"returncode": 0},
                    "diff_check": {"returncode": 0},
                    "vibeguard": {"returncode": 0, "overall": "Ready"},
                },
            )

    def test_manual_review_success_without_attestation_is_removed_before_finish(self) -> None:
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="review hook",
            evidence="manual success",
            fields={
                "review_attestation": "0" * 64,
                "review_scope": "working-tree",
                "review_paths_fingerprint": "0" * 64,
                "changed_path_count": "1",
            },
            status="SUCCESS",
            source="review",
        )

        gate_evidence, diagnostics, failures = self._finish_merge()

        self.assertNotIn("review hook", gate_evidence)
        self.assertTrue(failures)
        self.assertFalse(diagnostics["review_attestation"]["valid"])

    def test_worktree_drift_after_review_invalidates_the_gate(self) -> None:
        self._record_real_review()
        (self.project / "tracked.txt").write_text("changed after review\n", encoding="utf-8")

        gate_evidence, _, failures = self._finish_merge()

        self.assertNotIn("review hook", gate_evidence)
        self.assertTrue(any("worktree" in failure for failure in failures))

    def test_staging_after_review_invalidates_the_gate_without_changing_file_bytes(self) -> None:
        (self.project / "tracked.txt").write_text("ready to stage\n", encoding="utf-8")
        self._record_real_review()

        subprocess.run(["git", "add", "tracked.txt"], cwd=self.project, check=True)
        gate_evidence, _, failures = self._finish_merge()

        self.assertNotIn("review hook", gate_evidence)
        self.assertTrue(any("worktree" in failure for failure in failures))

    def test_rules_drift_after_review_is_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as rules_directory:
            rules = Path(rules_directory)
            rules_file = rules / "rules.md"
            rules_file.write_text("initial\n", encoding="utf-8")
            preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
            attestation = ReviewAttestation.record(
                project=self.project,
                rules=rules,
                evidence_path=self.evidence_path,
                preflight=preflight,
                review_scope="pathspec: tracked.txt",
                review_paths=["tracked.txt"],
                changed_path_count=0,
                checks={
                    "review_outcome": "pass",
                    "workflow_validate": {"returncode": 0},
                    "diff_check": {"returncode": 0},
                    "vibeguard": {"returncode": 0, "overall": "Ready"},
                },
            )
            rules_file.write_text("changed after review\n", encoding="utf-8")

            failures = ReviewAttestation.failures(
                project=self.project,
                rules=rules,
                evidence_path=self.evidence_path,
                route=self.route,
                ledger_fields=ReviewAttestation.ledger_fields(attestation),
                ledger_source="review",
            )

            self.assertEqual(
                ["review hook attestation rules worktree binding is stale"],
                failures,
            )

    def test_attestation_copied_to_another_run_is_rejected(self) -> None:
        attestation = self._record_real_review()
        other_evidence = self._write_preflight("b" * 32)
        shutil.copyfile(
            ReviewAttestation.path(self.evidence_path),
            ReviewAttestation.path(other_evidence),
        )
        other_preflight = json.loads(other_evidence.read_text(encoding="utf-8"))
        record_gate_evidence(
            evidence_path=other_evidence,
            preflight=other_preflight,
            gate="review hook",
            evidence="copied review success",
            fields=ReviewAttestation.ledger_fields(attestation),
            status="SUCCESS",
            source="review",
        )

        gate_evidence, _, failures = self._finish_merge(other_evidence)

        self.assertNotIn("review hook", gate_evidence)
        self.assertTrue(any("preflight" in failure or "run" in failure for failure in failures))

    def test_ledger_scope_cannot_claim_more_than_the_attestation(self) -> None:
        attestation = self._record_real_review()
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        forged_fields = ReviewAttestation.ledger_fields(attestation)
        forged_fields["review_scope"] = "working-tree"
        record_gate_evidence(
            evidence_path=self.evidence_path,
            preflight=preflight,
            gate="review hook",
            evidence="forged broader scope",
            fields=forged_fields,
            status="SUCCESS",
            source="review",
        )

        gate_evidence, _, failures = self._finish_merge()

        self.assertNotIn("review hook", gate_evidence)
        self.assertTrue(any("scope" in failure for failure in failures))

    def test_finish_entrypoint_refuses_ledger_only_review_success(self) -> None:
        finish_check = load_finish_check_module()
        output_path = self.project / ".tao" / "finish.json"
        preflight = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        ledger = {
            "entry_fields": {
                "review hook": {
                    "review_attestation": "0" * 64,
                    "review_scope": "working-tree",
                    "review_paths_fingerprint": "0" * 64,
                    "changed_path_count": "1",
                }
            },
            "sources": {"review hook": "review"},
        }
        captured: dict[str, object] = {}

        def report_finish_failures(**kwargs):
            captured.update(kwargs)
            return 1 if kwargs["failures"] else 0

        parser_result = type(
            "Args",
            (),
            {
                "project": self.project,
                "rules": self.project,
                "evidence": self.evidence_path,
                "output": output_path,
                "allow_vibeguard_review": None,
            },
        )()
        with (
            patch.object(
                finish_check,
                "build_parser",
                return_value=type(
                    "Parser",
                    (),
                    {"parse_args": lambda self: parser_result},
                )(),
            ),
            patch.object(finish_check, "read_preflight", return_value=preflight),
            patch.object(finish_check, "read_delegation_plan", return_value={}),
            patch.object(
                finish_check,
                "merge_gate_evidence_from_ledger",
                return_value=({"review hook": "manual success"}, ledger),
            ),
            patch.object(finish_check, "incomplete_gate_evidence_failures", return_value=[]),
            patch.object(finish_check, "canonical_skill_ids", return_value=set()),
            patch.object(
                finish_check,
                "route_gate_capsule_binding_failures",
                return_value=[],
            ),
            patch.object(finish_check, "check_request_intake", return_value=False),
            patch.object(finish_check, "check_preflight_vibeguard"),
            patch.object(finish_check, "check_read_only_execution"),
            patch.object(
                finish_check,
                "run_final_checks",
                return_value=(
                    {"returncode": 0},
                    {"returncode": 0},
                    {"returncode": 0, "overall": "Ready"},
                    "Ready",
                ),
            ),
            patch.object(
                finish_check,
                "process_failure_learning",
                return_value=(True, {}),
            ),
            patch.object(finish_check, "write_json"),
            patch.object(finish_check, "print_result"),
            patch.object(
                finish_check,
                "_report_finish_failures",
                side_effect=report_finish_failures,
            ),
        ):
            returncode = finish_check.main()

        self.assertEqual(1, returncode)
        self.assertIn("review hook", captured["missed_gates"])
        self.assertTrue(
            any("attestation" in failure for failure in captured["failures"])
        )

    def test_finish_revalidates_attestation_after_final_checks(self) -> None:
        finish_check = load_finish_check_module()
        self._record_real_review()
        output_path = self.project / ".tao" / "finish.json"
        captured: dict[str, object] = {}

        def validate_then_drift(**kwargs):
            enforce_review_hook_attestation(**kwargs)
            (self.project / "tracked.txt").write_text(
                "changed after initial attestation validation\n",
                encoding="utf-8",
            )

        def report_finish_failures(**kwargs):
            captured.update(kwargs)
            return 1 if kwargs["failures"] else 0

        parser_result = type(
            "Args",
            (),
            {
                "project": self.project,
                "rules": self.project,
                "evidence": self.evidence_path,
                "output": output_path,
                "allow_vibeguard_review": None,
            },
        )()
        with (
            patch.object(
                finish_check,
                "build_parser",
                return_value=type(
                    "Parser",
                    (),
                    {"parse_args": lambda self: parser_result},
                )(),
            ),
            patch.object(finish_check, "read_delegation_plan", return_value={}),
            patch.object(
                finish_check,
                "enforce_review_hook_attestation",
                side_effect=validate_then_drift,
            ),
            patch.object(finish_check, "canonical_skill_ids", return_value=set()),
            patch.object(
                finish_check,
                "route_gate_capsule_binding_failures",
                return_value=[],
            ),
            patch.object(finish_check, "check_request_intake", return_value=False),
            patch.object(finish_check, "check_preflight_vibeguard"),
            patch.object(finish_check, "check_read_only_execution"),
            patch.object(
                finish_check,
                "run_final_checks",
                return_value=(
                    {"returncode": 0},
                    {"returncode": 0},
                    {"returncode": 0, "overall": {"status": "Ready"}},
                    "Ready",
                ),
            ),
            patch.object(
                finish_check,
                "process_failure_learning",
                return_value=(False, {}),
            ),
            patch.object(finish_check, "write_json"),
            patch.object(finish_check, "record_session_finished"),
            patch.object(finish_check, "print_result"),
            patch.object(
                finish_check,
                "_report_finish_failures",
                side_effect=report_finish_failures,
            ),
        ):
            returncode = finish_check.main()

        self.assertEqual(1, returncode)
        self.assertIn("review hook", captured["missed_gates"])
        self.assertTrue(
            any("worktree" in failure for failure in captured["failures"])
        )


if __name__ == "__main__":
    unittest.main()
