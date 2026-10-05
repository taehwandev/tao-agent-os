"""Receipts for failures recorded by external test runners through the gate hook."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_gate_evidence import record_gate_evidence
from agent_repair_ledger import checkpoint_failure_signature, record_failure_checkpoints
from agent_repair_verification import create_repair_receipt, validate_repair_receipt


class AgentRepairGateReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"],
                       cwd=self.project, check=True)
        self.preflight = {"route": {"command": "task", "gates": ["tests", "handoff"]}}
        self.evidence = self.project / ".tao" / "preflight.json"
        self.evidence.parent.mkdir()
        self.evidence.write_text(json.dumps(self.preflight))
        (self.project / "target.py").write_text("VALUE = 1\n")

    def record(self, status):
        record_gate_evidence(
            evidence_path=self.evidence, preflight=self.preflight, gate="tests",
            evidence="external runner exited 1" if status == "FAIL" else "external runner passed",
            status=status, fields={"check": "external test", "result": status}, source="agent",
        )

    def receipt(self):
        return create_repair_receipt(
            project=self.project, rules=ROOT, evidence_path=self.evidence,
            preflight=self.preflight, target="target.py", checkpoint="tests",
            verification_kind="py_compile",
        )

    def test_latest_failed_gate_can_produce_a_valid_receipt(self):
        self.record("FAIL")
        receipt = self.receipt()
        self.assertTrue(receipt["created"])
        self.assertEqual("SUCCESS", receipt["status"])
        self.assertEqual([], validate_repair_receipt(
            project=self.project, rules=ROOT, evidence_path=self.evidence,
            preflight=self.preflight, target="target.py", checkpoint="tests",
            receipt_path=Path(receipt["receipt_path"]),
        ))

    def test_success_after_failure_cannot_be_imported_as_a_failed_checkpoint(self):
        self.record("FAIL")
        self.record("SUCCESS")
        self.assertEqual("checkpoint_not_failed", self.receipt()["reason"])

    def test_a_stale_preflight_ledger_cannot_authorize_a_receipt(self):
        self.record("FAIL")
        self.preflight["revision"] = "changed input"
        self.evidence.write_text(json.dumps(self.preflight))
        self.assertEqual("checkpoint_not_failed", self.receipt()["reason"])

    def test_an_unrecorded_failure_cannot_authorize_a_receipt(self):
        self.assertEqual("checkpoint_not_failed", self.receipt()["reason"])

    def test_other_recorded_failure_signatures_are_preserved(self):
        record_failure_checkpoints(
            evidence_path=self.evidence, preflight=self.preflight,
            checkpoints=["handoff"], signature="original-signature",
            checkpoint_signatures={"handoff": "original-signature"},
        )
        self.record("FAIL")
        self.assertTrue(self.receipt()["created"])
        self.assertEqual("original-signature", checkpoint_failure_signature(
            route=self.preflight["route"], evidence_path=self.evidence, checkpoint="handoff",
        ))


if __name__ == "__main__":
    unittest.main()
