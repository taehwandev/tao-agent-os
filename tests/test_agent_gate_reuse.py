from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_gate_evidence import gate_evidence_path_for_preflight, merge_gate_evidence_from_ledger
from agent_hook_gate_records import _normalize_gate_record, record_hook_gate_batch


class GateEvidenceReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.rules = self.root / "rules"
        for root in (self.project, self.rules):
            root.mkdir()
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "test@example.invalid")
            self.git(root, "config", "user.name", "Test")
            (root / ".gitignore").write_text(".tao/\n")
            (root / "README.md").write_text("Existing release contract.\n")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "baseline")
        self.source_id, self.target_id = "a" * 32, "b" * 32
        self.source = self.make_run(self.source_id, "배포")
        self.target = self.make_run(self.target_id, "아니 바로 배포는 알아서 다시해야하는거 아니니? 왜 자꾸 멈춰")
        registry = self.project / ".tao" / "run-registry.json"
        registry.write_text(json.dumps({"schema_version": 1, "runs": [
            {"run_id": self.source_id, "state": "completed", "evidence_name": "preflight.json"},
            {"run_id": self.target_id, "state": "running", "evidence_name": "preflight.json"},
        ]}))

    @staticmethod
    def git(root, *args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    def make_run(self, run_id, request):
        path = self.project / ".tao" / "runs" / run_id / "preflight.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"project": str(self.project), "rules": str(self.rules),
            "agent_run_id": run_id, "runtime_session": {"runtime": "codex", "session_id": "same-session"},
            "request_intake": {"request": request, "continuation_scope": "same release recovery"},
            "route": {"command": "release", "gates": ["documentation impact", "tests", "review hook", "config"],
                      "required_docs": []}}))
        return SimpleNamespace(project=self.project, rules=self.rules, evidence=path)

    def record_source(self, gate="tests", status="SUCCESS"):
        if gate == "tests":
            fields = {"check": "python3 -m unittest tests.test_sample", "result": "7 tests passed, exit 0"}
        else:
            fields = {"artifact": "README.md", "decision": "unchanged", "reason": "release behavior matches the existing contract",
                      "inspected": "README.md", "coverage": "release target and artifact names match"}
        return record_hook_gate_batch(self.source, [{"gate": gate, "status": status,
            "fields": fields, "evidence": "Retained original verification."}])[0]

    def reuse(self, gate="tests", **extra):
        return {"gate": gate, "reuse_from": self.source_id,
                "reuse_reason": "Same release target, artifacts, toolchain and external inputs; unchanged local result", **extra}

    def test_followup_reuses_accepted_record_without_rewriting_fields(self):
        original = self.record_source()
        reference = _normalize_gate_record(self.reuse())
        reused = record_hook_gate_batch(self.target, [reference])[0]
        self.assertEqual(original["fields"], reused["fields"])
        self.assertEqual(original["evidence"], reused["evidence"])
        self.assertEqual("reuse", reused["source"])
        self.assertEqual(self.source_id, reused["reuse_provenance"]["run_id"])
        current = json.loads(self.target.evidence.read_text())
        merged, _ = merge_gate_evidence_from_ledger(route=current["route"], evidence_path=self.target.evidence)
        self.assertIn("tests", merged)
        self.assertNotIn("review hook", merged)
        self.assertNotIn("config", merged)

    def test_structured_document_inspection_survives_rendering_and_reuse(self):
        original = self.record_source("documentation impact")
        reused = record_hook_gate_batch(self.target, [self.reuse("documentation impact")])[0]
        self.assertEqual(original["evidence"], reused["evidence"])
        self.assertEqual("README.md", reused["fields"]["inspected"])

    def test_bare_unchanged_claim_still_fails(self):
        with self.assertRaisesRegex(ValueError, "opened/inspected"):
            record_hook_gate_batch(self.source, [{"gate": "documentation impact", "fields": {
                "artifact": "README.md", "decision": "unchanged", "reason": "already covers release behavior"}}])

    def test_source_or_rules_drift_refuses_reuse(self):
        self.record_source()
        for root in (self.project, self.rules):
            with self.subTest(root=root):
                path = root / "README.md"
                old = path.read_text()
                path.write_text("changed")
                with self.assertRaisesRegex(ValueError, "inputs changed"):
                    record_hook_gate_batch(self.target, [self.reuse()])
                path.write_text(old)

    def test_new_commit_invalidates_conservative_snapshot(self):
        self.record_source()
        self.git(self.project, "commit", "--allow-empty", "-qm", "new revision")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            record_hook_gate_batch(self.target, [self.reuse()])

    def test_failed_latest_record_cannot_fall_back_to_old_success(self):
        self.record_source()
        self.record_source(status="FAIL")
        with self.assertRaisesRegex(ValueError, "latest SUCCESS"):
            record_hook_gate_batch(self.target, [self.reuse()])

    def test_other_session_refused(self):
        self.record_source()
        current = json.loads(self.target.evidence.read_text())
        current["runtime_session"]["session_id"] = "other"
        self.target.evidence.write_text(json.dumps(current))
        with self.assertRaisesRegex(ValueError, "session differs"):
            record_hook_gate_batch(self.target, [self.reuse()])

    def test_authority_review_and_external_gates_are_not_reusable(self):
        for gate in ("review hook", "config", "request intake", "rollback"):
            with self.subTest(gate=gate), self.assertRaisesRegex(ValueError, "not allowed"):
                record_hook_gate_batch(self.target, [self.reuse(gate)])

    def test_legacy_snapshot_or_stale_ledger_refused(self):
        self.record_source()
        path = gate_evidence_path_for_preflight(self.source.evidence)
        ledger = json.loads(path.read_text())
        del ledger["entries"][-1]["reuse_snapshot"]
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "snapshot is unavailable"):
            record_hook_gate_batch(self.target, [self.reuse()])
        ledger["preflight_evidence_sha256"] = "wrong"
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "latest SUCCESS"):
            record_hook_gate_batch(self.target, [self.reuse()])

    def test_reference_cannot_override_evidence_or_omit_input_attestation(self):
        self.record_source()
        for extra in ({"evidence": "override"}, {"status": "FAIL"}, {"reuse_reason": ""}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                record_hook_gate_batch(self.target, [self.reuse(**extra)])

    def test_bad_reference_does_not_partially_write_batch(self):
        self.record_source()
        with self.assertRaises(ValueError):
            record_hook_gate_batch(self.target, [self.reuse(), self.reuse("config")])
        self.assertFalse(gate_evidence_path_for_preflight(self.target.evidence).exists())


if __name__ == "__main__":
    unittest.main()
