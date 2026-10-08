from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_execution_capsule_state import (
    atomic_write_json, capsule_path_for_evidence, preflight_snapshot_binding_fingerprint,
)
from agent_gate_evidence import record_gate_evidence, merge_gate_evidence_from_ledger
from agent_repair_ledger import (
    checkpoint_has_recorded_failure, record_failure_checkpoints,
    register_repair_attempt, repair_checkpoint_path_for_preflight,
)
from agent_route_state import preflight_evidence_sha256
from agent_runtime_session import bind_resumed_runtime_session
from tests.test_agent_runtime_session import RuntimeFixture


class ResumeEvidenceBindingTests(unittest.TestCase):
    def prepare(self, directory):
        fixture = RuntimeFixture(directory)
        atomic_write_json(fixture.evidence, fixture.preflight)
        snapshot = fixture.preflight["execution_snapshot"]
        atomic_write_json(capsule_path_for_evidence(fixture.evidence), {
            "schema_version": 1, "phase": "ready",
            "route_fingerprint": snapshot["route_fingerprint"],
            "request_fingerprint": snapshot["request_fingerprint"],
            "preflight_evidence": {"filename": "preflight.json", "sha256": preflight_evidence_sha256(fixture.evidence)},
            "required_docs": [], "reuse_policy": {},
        })
        record_gate_evidence(
            evidence_path=fixture.evidence, preflight=fixture.preflight,
            gate="finish", evidence="observed check passed", status="SUCCESS", source="agent",
        )
        record_failure_checkpoints(
            evidence_path=fixture.evidence, preflight=fixture.preflight,
            checkpoints=["finish"], signature="failed-finish",
        )
        register_repair_attempt(
            evidence_path=fixture.evidence, preflight=fixture.preflight,
            checkpoint="finish", limit=1, failure_signature="failed-finish",
        )
        fixture.set_generation(1)
        return fixture

    def resume(self, fixture):
        bind_resumed_runtime_session(
            project=fixture.project, evidence_path=fixture.evidence,
            run_id=fixture.run_id, resume_generation=1,
            runtime="claude", session_id="new-session",
        )

    def test_resume_keeps_gate_provenance_on_the_current_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.prepare(directory)
            self.resume(fixture)
            payload = json.loads(fixture.evidence.read_text())
            _, diagnostics = merge_gate_evidence_from_ledger(
                route=payload["route"], evidence_path=fixture.evidence,
            )
            self.assertEqual([], diagnostics["warnings"])
            self.assertEqual(preflight_snapshot_binding_fingerprint(payload["execution_snapshot"]),
                             diagnostics["capsule_bindings"]["finish"])
            self.assertEqual("agent", diagnostics["sources"]["finish"])

    def test_resume_preserves_the_failure_and_consumed_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.prepare(directory)
            self.resume(fixture)
            self.assertTrue(checkpoint_has_recorded_failure(
                route=fixture.preflight["route"], evidence_path=fixture.evidence, checkpoint="finish",
            ))
            ledger = json.loads(repair_checkpoint_path_for_preflight(fixture.evidence).read_text())
            self.assertEqual(1, ledger["repair_attempts"]["finish"]["count"])
            self.assertEqual("failed-finish", ledger["failure_signatures"]["finish"])

    def test_failed_packet_write_restores_gate_and_repair_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.prepare(directory)
            before = fixture.evidence.read_bytes()
            with patch("agent_continuation_checkpoint.write_continuation_checkpoint", side_effect=RuntimeError("packet failure")):
                with self.assertRaises(RuntimeError):
                    self.resume(fixture)
            self.assertEqual(before, fixture.evidence.read_bytes())
            self.assertTrue(checkpoint_has_recorded_failure(
                route=fixture.preflight["route"], evidence_path=fixture.evidence, checkpoint="finish",
            ))
            _, diagnostics = merge_gate_evidence_from_ledger(
                route=fixture.preflight["route"], evidence_path=fixture.evidence,
            )
            self.assertEqual([], diagnostics["warnings"])


if __name__ == "__main__":
    unittest.main()
