"""A finished publication refusal must explain current proof, not revive old work."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_publication_admission import PublicationAdmission
from support.global_state import STATE_HOME_ENV
import test_claude_pretool_gate as fixtures

gate = fixtures.gate
_decision_of = fixtures._decision_of
_reason = fixtures._reason


class FinishedEntryRefusalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        env = patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: str(base / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.session = "finished-session"
        with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "claude"}):
            self.project = fixtures.FinishAuthorizesItsOwnPublicationTests()._finished_project(base)
            self.evidence = gate.finished_session_evidence(self.project, self.session)
        self.assertIsNotNone(self.evidence)
        payload = json.loads(self.evidence.read_text())
        payload["runtime_session"]["runtime"] = "codex"
        self.evidence.write_text(json.dumps(payload))
        self.assertTrue(PublicationAdmission.record_finish(self.project, self.evidence))
        self.paused = self.project / ".tao" / "old-paused" / "preflight.json"
        self.paused.parent.mkdir()
        self.paused.write_text("{}")
        earlier = time.time() - 300
        os.utime(self.paused, (earlier, earlier))
        paused = patch.object(gate, "paused_session_evidence", return_value=self.paused)
        paused.start()
        self.addCleanup(paused.stop)

    def refuse(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            gate.entry_denial(
                self.project, self.session, "Bash", payload={
                    "tool_name": "Bash", "session_id": self.session,
                    "cwd": str(self.project), "tool_input": {"command": command},
                },
            )
        return output.getvalue()

    def test_changed_finished_bytes_explain_drift_without_old_paused_operator_prompt(self):
        (self.project / "changed.py").write_text("changed = True\n")
        output = self.refuse("git commit -m reviewed")
        self.assertEqual("deny", _decision_of(output))
        self.assertIn("project files changed after finish", _reason(output))
        self.assertNotIn("paused", _reason(output))
        self.assertNotIn("Tao operator decision required", output)

    def test_push_with_only_local_authority_explains_effect_without_old_paused_prompt(self):
        payload = json.loads(self.evidence.read_text())
        payload["route"]["request_classification"]["intent_envelope"]["effective_effect"] = "git_write"
        self.evidence.write_text(json.dumps(payload))
        self.assertTrue(PublicationAdmission.record_finish(self.project, self.evidence))
        output = self.refuse("git push origin work")
        self.assertEqual("deny", _decision_of(output))
        self.assertIn("publication needs external_write", _reason(output))
        self.assertNotIn("paused", _reason(output))
        self.assertNotIn("Tao operator decision required", output)

    def test_changed_rules_explain_revalidation_without_old_paused_prompt(self):
        rules = Path(self.temp.name) / "rules"
        rules.mkdir()
        subprocess.run(["git", "init", "-q", str(rules)], check=True, capture_output=True)
        marker = rules / "AGENTS.md"
        marker.write_text("Original rules\n")
        payload = json.loads(self.evidence.read_text())
        payload["rules"] = str(rules)
        self.evidence.write_text(json.dumps(payload))
        self.assertTrue(PublicationAdmission.record_finish(self.project, self.evidence))
        marker.write_text("Changed rules\n")
        output = self.refuse("git commit -m reviewed")
        self.assertEqual("deny", _decision_of(output))
        self.assertIn("Tao rules changed after finish", _reason(output))
        self.assertNotIn("paused", _reason(output))
        self.assertNotIn("Tao operator decision required", output)

    def test_newer_paused_work_keeps_its_exact_operator_boundary(self):
        later = time.time() + 10
        os.utime(self.paused, (later, later))
        output = self.refuse("git commit -m reviewed")
        self.assertIn("paused", _reason(output))
        self.assertIn("Tao operator decision required", output)

    def test_expired_finish_does_not_replace_paused_recovery(self):
        receipt = self.evidence.with_name("publication.json")
        earlier = time.time() - gate.max_age_seconds() - 10
        os.utime(receipt, (earlier, earlier))
        output = self.refuse("git commit -m reviewed")
        self.assertIn("paused", _reason(output))
        self.assertIn("Tao operator decision required", output)

    def test_local_write_is_not_reclassified_as_finished_publication(self):
        output = self.refuse("touch changed.txt")
        self.assertIn("paused", _reason(output))
        self.assertIn("Tao operator decision required", output)

    def test_real_gate_explains_changed_commit_proof_and_old_classifier_control_fails(self):
        (self.project / "changed.py").write_text("changed = True\n")
        payload = {
            "tool_name": "Bash", "session_id": self.session,
            "cwd": str(self.project), "tool_input": {"command": "git commit -m reviewed"},
        }
        _, output = fixtures._decide(payload)
        self.assertEqual("deny", _decision_of(output))
        self.assertIn("project files changed after finish", _reason(output))
        self.assertNotIn("Tao operator decision required", output)
        with patch.object(gate._admission, "has_finished_publication", return_value=False):
            _, old_classifier = fixtures._decide(payload)
        self.assertIn("paused", _reason(old_classifier))
        self.assertIn("Tao operator decision required", old_classifier)


if __name__ == "__main__":
    unittest.main()
