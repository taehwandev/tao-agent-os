from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests import test_agent_gate_reuse as fixture
from agent_gate_evidence import gate_evidence_path_for_preflight, merge_gate_evidence_from_ledger
from agent_hook_gate_records import _normalize_gate_record, record_hook_gate_batch
from agent_work_continuity import WorkContinuity


class WorkContinuityTests(unittest.TestCase):
    setUp = fixture.GateEvidenceReuseTests.setUp
    git = staticmethod(fixture.GateEvidenceReuseTests.git)
    make_run = fixture.GateEvidenceReuseTests.make_run
    record_source = fixture.GateEvidenceReuseTests.record_source

    def continuation(self, reason="Same check scope, toolchain, artifacts and external inputs"):
        self.target.continue_from = self.source_id
        self.target.reuse_inputs = reason
        session = json.loads(self.source.evidence.read_text())["runtime_session"]
        with patch("agent_work_continuity.runtime_session", return_value=session):
            return WorkContinuity(self.target)

    def passed(self):
        payload = json.loads(self.target.evidence.read_text())
        return merge_gate_evidence_from_ledger(route=payload["route"], evidence_path=self.target.evidence)[0]

    def scoped_test(self, paths):
        return record_hook_gate_batch(self.source, [_normalize_gate_record({
            "gate": "tests", "input_paths": paths,
            "fields": {"check": "local content test", "result": "7 tests passed, exit 0"},
        })])[0]

    def test_different_followup_words_and_routes_keep_work_and_copy_no_authority(self):
        self.record_source()
        original = self.source.evidence.read_bytes()
        for words, command in (("메인에 반영해", "commit"), ("계속 진행", "bugfix"), ("같은 번호로 다시 배포해", "release")):
            with self.subTest(words=words):
                payload = json.loads(self.target.evidence.read_text())
                payload["request_intake"]["request"] = words
                payload["route"]["command"] = command
                payload["intent_envelope"] = {"requested_effects": ["read"]}
                self.target.evidence.write_text(json.dumps(payload))
                result = self.continuation().apply(self.target.evidence)
                current = json.loads(self.target.evidence.read_text())
                self.assertEqual(self.source_id, current["work"]["id"])
                self.assertEqual({"requested_effects": ["read"]}, current["intent_envelope"])
                self.assertIn("tests", self.passed())
                self.assertNotIn("config", self.passed())
                self.assertNotIn("review hook", self.passed())
                self.assertTrue(any("Carried local gates: ['tests']" == line for line in result))
        self.assertEqual(original, self.source.evidence.read_bytes())

    def test_changed_external_inputs_preserve_history_but_do_not_pass_gates(self):
        self.record_source()
        self.continuation(reason="").apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())
        self.assertEqual(self.source_id, json.loads(self.target.evidence.read_text())["work"]["id"])

    def test_only_affected_check_is_invalidated(self):
        self.scoped_test(["README.md"])
        (self.project / "unrelated.txt").write_text("a new unrelated input")
        self.continuation().apply(self.target.evidence)
        self.assertIn("tests", self.passed())
        gate_evidence_path_for_preflight(self.target.evidence).unlink()
        (self.project / "README.md").write_text("changed check input")
        self.continuation().apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())

    def test_commit_keeps_revision_independent_evidence(self):
        (self.project / "README.md").write_text("tested new content")
        self.scoped_test([])
        self.git(self.project, "add", "README.md")
        self.git(self.project, "commit", "-qm", "same tested contents")
        self.continuation().apply(self.target.evidence)
        self.assertIn("tests", self.passed())

    def test_default_revision_sensitive_evidence_still_invalidates(self):
        self.record_source()
        self.git(self.project, "commit", "--allow-empty", "-qm", "new revision")
        self.continuation().apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())

    def test_latest_failure_cannot_be_hidden_by_continuation(self):
        self.record_source()
        self.record_source(status="FAIL")
        self.continuation().apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())

    def test_no_implicit_link_from_identical_words(self):
        self.record_source()
        self.target.continue_from = ""
        self.target.reuse_inputs = ""
        WorkContinuity(self.target).apply(self.target.evidence)
        self.assertEqual(self.target_id, json.loads(self.target.evidence.read_text())["work"]["id"])
        self.assertNotIn("tests", self.passed())

    def test_same_action_refresh_preserves_retained_work_identity(self):
        self.target.continue_from = ""
        self.target.reuse_inputs = ""
        identity = {"schema_version": 1, "id": self.source_id, "previous_action": self.source_id}
        WorkContinuity(self.target).apply(self.target.evidence, retained_work=identity)
        self.assertEqual(identity, json.loads(self.target.evidence.read_text())["work"])

    def test_cancelled_foreign_or_mutating_source_refused(self):
        with patch("agent_work_continuity.runtime_session", return_value={"runtime": "codex", "session_id": "other"}):
            self.target.continue_from = self.source_id
            with self.assertRaisesRegex(ValueError, "differs"):
                WorkContinuity(self.target)
        path = self.project / ".tao" / "run-registry.json"
        registry = json.loads(path.read_text())
        registry["runs"][0]["state"] = "cancelled"
        path.write_text(json.dumps(registry))
        with self.assertRaisesRegex(ValueError, "non-cancelled"):
            self.continuation()

    def test_admission_race_does_not_copy_or_overwrite_source(self):
        self.record_source()
        continuation = self.continuation()
        original = self.target.evidence.read_bytes()
        prior = json.loads(self.source.evidence.read_text())
        prior["changed"] = True
        self.source.evidence.write_text(json.dumps(prior))
        with self.assertRaisesRegex(ValueError, "changed during"):
            continuation.apply(self.target.evidence)
        self.assertEqual(original, self.target.evidence.read_bytes())

    def test_chain_retains_first_work_identity(self):
        self.record_source()
        self.continuation().apply(self.target.evidence)
        first_work = self.source_id
        self.source = self.target
        self.source_id = self.target_id
        self.target_id = "c" * 32
        self.target = self.make_run(self.target_id, "다음 단계까지")
        self.continuation().apply(self.target.evidence)
        self.assertEqual(first_work, json.loads(self.target.evidence.read_text())["work"]["id"])
        self.assertIn("tests", self.passed())

    def test_intermediate_action_without_test_gate_keeps_earlier_verification(self):
        self.record_source()
        payload = json.loads(self.target.evidence.read_text())
        payload["route"]["gates"] = ["config"]
        self.target.evidence.write_text(json.dumps(payload))
        self.continuation().apply(self.target.evidence)
        self.source = self.target
        self.source_id = self.target_id
        self.target_id = "c" * 32
        self.target = self.make_run(self.target_id, "마저 해줘")
        self.continuation().apply(self.target.evidence)
        self.assertIn("tests", self.passed())

    def test_explicit_dependency_is_preserved_after_inheritance(self):
        self.scoped_test(["README.md"])
        self.continuation().apply(self.target.evidence)
        ledger = json.loads(gate_evidence_path_for_preflight(self.target.evidence).read_text())
        self.assertEqual(["README.md"], ledger["entries"][-1]["reuse_snapshot"]["input_paths"])
        self.source = self.target
        self.source_id = self.target_id
        self.target_id = "c" * 32
        self.target = self.make_run(self.target_id, "마저 해줘")
        (self.project / "README.md").write_text("changed after inheritance")
        self.continuation().apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())

    def test_rules_drift_invalidates_scoped_project_check(self):
        self.scoped_test(["README.md"])
        (self.rules / "README.md").write_text("new policy")
        self.continuation().apply(self.target.evidence)
        self.assertNotIn("tests", self.passed())

    def test_input_change_after_carry_invalidates_current_ledger_for_finish(self):
        self.scoped_test(["README.md"])
        self.continuation().apply(self.target.evidence)
        self.assertIn("tests", self.passed())
        (self.project / "README.md").write_text("changed after carry")
        self.assertNotIn("tests", self.passed())


if __name__ == "__main__":
    unittest.main()
