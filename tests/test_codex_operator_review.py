from __future__ import annotations

import copy
import json
import os
import re
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from codex_operator_review import OperatorReview
from support.global_state import STATE_HOME_ENV
from support.stable_launcher import _launcher_script_text


class CodexOperatorReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {STATE_HOME_ENV: self.temporary.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.payload = {"session_id": "codex-session", "cwd": "/project",
                        "tool_name": "Bash", "tool_input": {"command": "git status && git fetch"},
                        "turn_id": "before-question"}

    def pending(self):
        approved, message = OperatorReview.request(self.payload, "reason", "unreadable_command_effect")
        self.assertFalse(approved)
        return re.search(r"--request-id ([a-f0-9]{64})", message).group(1)

    def test_question_then_explicit_answer_then_one_identical_retry(self):
        request_id = self.pending()
        self.assertEqual(request_id, self.pending(), "waiting does not imply consent")
        OperatorReview.resolve(request_id, "approve", "codex-session")
        self.payload["turn_id"] = "user-answered"
        self.assertTrue(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])
        self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_operator_codes_match_the_gate_and_paused_run_can_be_approved(self):
        from claude_pretool_gate import OPERATOR_DECIDES
        self.assertEqual(OPERATOR_DECIDES, OperatorReview.CODES)
        approved, message = OperatorReview.request(self.payload, "paused run", "paused_run_refused")
        self.assertFalse(approved)
        request_id = re.search(r"--request-id ([a-f0-9]{64})", message).group(1)
        OperatorReview.resolve(request_id, "approve", "codex-session")
        self.assertTrue(OperatorReview.request(self.payload, "paused run", "paused_run_refused")[0])

    def test_always_reuses_exact_scope_across_turns_and_sessions_then_revokes(self):
        request_id = self.pending()
        OperatorReview.resolve(request_id, "always", "codex-session")
        self.payload["session_id"] = "next-session"
        self.payload["turn_id"] = "next-turn"
        with patch("codex_operator_review.time.time", return_value=10**12):
            for _ in range(2):
                self.assertTrue(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])
            OperatorReview.resolve(request_id, "revoke", "next-session")
            self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_always_never_covers_other_commands_targets_or_policy(self):
        request_id = self.pending()
        OperatorReview.resolve(request_id, "always", "codex-session")
        changed = copy.deepcopy(self.payload)
        changed["tool_input"]["command"] = "git reset --hard"
        self.assertFalse(OperatorReview.request(changed, "reason", "unreadable_command_effect")[0])
        changed = copy.deepcopy(self.payload)
        changed["cwd"] = "/other-project"
        self.assertFalse(OperatorReview.request(changed, "reason", "unreadable_command_effect")[0])
        with patch("codex_operator_review.Path.read_bytes", return_value=b"changed policy"):
            self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])
        self.assertTrue(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_launcher_records_explicit_always_answer_and_revocation(self):
        request_id = self.pending()
        launcher = Path(self.temporary.name) / "tao-hook"
        launcher.write_text(_launcher_script_text())
        command = [sys.executable, str(launcher), "operator-review", "--request-id", request_id,
                   "--decision"]
        environment = {**os.environ, "TAO_HOME": str(ROOT), "CODEX_THREAD_ID": "codex-session"}
        for decision, expected in (("always", True), ("revoke", False)):
            result = subprocess.run([*command, decision], env=environment, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(expected, OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_cli_without_runtime_session_cannot_record_an_answer(self):
        request_id = self.pending()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/codex_operator_review.py"),
             "--request-id", request_id, "--decision", "approve"],
            env={**os.environ, "CODEX_THREAD_ID": ""}, capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_rejection_keeps_the_same_call_blocked(self):
        request_id = self.pending()
        OperatorReview.resolve(request_id, "reject", "codex-session")
        approved, message = OperatorReview.request(self.payload, "reason", "unreadable_command_effect")
        self.assertFalse(approved)
        self.assertIn("rejected", message)

    def test_command_session_cwd_and_reason_do_not_share_approval(self):
        for field, value in (("session_id", "other"), ("cwd", "/elsewhere"),
                             ("tool_input", {"command": "git reset --hard"})):
            with self.subTest(field=field):
                request_id = self.pending()
                OperatorReview.resolve(request_id, "approve", "codex-session")
                changed = copy.deepcopy(self.payload)
                changed[field] = value
                self.assertFalse(OperatorReview.request(changed, "reason", "unreadable_command_effect")[0])
                self.assertFalse(OperatorReview.request(self.payload, "new reason", "unreadable_command_effect")[0])
                self.assertTrue(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_an_edit_approval_does_not_cover_changed_content(self):
        self.payload.update(tool_name="Write", tool_input={"file_path": "/project/file.py", "content": "before"})
        approved, message = OperatorReview.request(self.payload, "reason", "ticketed_product_branch")
        request_id = re.search(r"--request-id ([a-f0-9]{64})", message).group(1)
        OperatorReview.resolve(request_id, "approve", "codex-session")
        self.payload["tool_input"]["content"] = "after"
        self.assertFalse(OperatorReview.request(self.payload, "reason", "ticketed_product_branch")[0])

    def test_expiration_foreign_session_missing_and_settled_requests_reject(self):
        request_id = self.pending()
        with self.assertRaises(ValueError):
            OperatorReview.resolve(request_id, "approve", "other-session")
        with self.assertRaises(ValueError):
            OperatorReview.resolve("0" * 64, "approve", "codex-session")
        with patch("codex_operator_review.time.time", return_value=10**12):
            with self.assertRaises(ValueError):
                OperatorReview.resolve(request_id, "approve", "codex-session")
        OperatorReview.resolve(request_id, "approve", "codex-session")
        with self.assertRaises(ValueError):
            OperatorReview.resolve(request_id, "approve", "codex-session")

    def test_policy_change_and_expired_approval_require_a_new_answer(self):
        request_id = self.pending()
        OperatorReview.resolve(request_id, "approve", "codex-session")
        with patch("codex_operator_review.Path.read_bytes", return_value=b"changed policy"):
            self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])
        with patch("codex_operator_review.time.time", return_value=10**12):
            self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_changed_project_policy_invalidates_standing_consent(self):
        project = Path(self.temporary.name) / "project"
        project.mkdir()
        (project / ".git").mkdir()
        policy = project / "AGENTS.md"
        policy.write_text("original policy")
        self.payload["cwd"] = str(project)
        request_id = self.pending()
        OperatorReview.resolve(request_id, "always", "codex-session")
        policy.write_text("changed policy")
        self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])

    def test_no_raw_command_answer_or_edit_content_is_persisted(self):
        self.pending()
        files = list(Path(self.temporary.name).rglob("*.json"))
        self.assertEqual(1, len(files))
        record = json.loads(files[0].read_text())
        self.assertEqual({"session_id", "code", "status", "expires_at", "approval_id"}, set(record))

    def test_missing_session_and_non_operator_codes_never_get_approval(self):
        self.payload["session_id"] = ""
        self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])
        self.payload["session_id"] = "codex-session"
        self.assertFalse(OperatorReview.request(self.payload, "reason", "workflow_entry_missing")[0])
        self.assertEqual([], list(Path(self.temporary.name).rglob("*.json")))

    def test_malformed_state_is_not_approval(self):
        request_id = self.pending()
        OperatorReview._path(request_id).write_text('{"status":"approved"}')
        self.assertFalse(OperatorReview.request(self.payload, "reason", "unreadable_command_effect")[0])


if __name__ == "__main__":
    unittest.main()
