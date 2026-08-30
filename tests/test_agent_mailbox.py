from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_execution_capsule import capsule_path_for_evidence
from agent_mailbox import AgentMailbox


class AgentMailboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.project = root / "project"
        self.rules = root / "rules"
        self.evidence = self.project / ".tao" / "runs" / ("a" * 32) / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.evidence.write_text(json.dumps({"route": {"command": "review"}}), encoding="utf-8")
        capsule_path_for_evidence(self.evidence).write_text("{}\n", encoding="utf-8")
        (self.rules / "scripts").mkdir(parents=True)
        (self.rules / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (self.rules / "index.md").write_text("index\n", encoding="utf-8")
        (self.rules / "scripts" / "workflow.py").write_text("# workflow\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_send_resolves_active_work_and_receive_needs_no_room_or_task_id(self) -> None:
        mailbox = AgentMailbox(self.project, self.rules)
        with (
            patch("agent_mailbox.resolve_runtime_evidence", return_value=self.evidence) as resolver,
            patch("agent_mailbox.validate_execution_capsule", return_value=[]),
            patch("agent_mailbox.runtime_session", return_value={"runtime": "codex", "session_id": "opaque"}),
        ):
            sent = mailbox.send(
                recipient="claude",
                kind="review",
                body="Review the bounded local change.",
            )

        resolver.assert_called_once_with(self.project.resolve())
        received = mailbox.receive("claude")
        self.assertEqual("codex", sent["sender"])
        self.assertEqual([sent], received)
        self.assertEqual([], mailbox.receive("claude"))

    def test_send_refuses_missing_work_invalid_capsule_and_oversized_body(self) -> None:
        mailbox = AgentMailbox(self.project, self.rules)
        with patch("agent_mailbox.resolve_runtime_evidence", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no exact active Tao work"):
                mailbox.send(recipient="claude", kind="review", body="Check")

        with patch("agent_mailbox.validate_execution_capsule", return_value=["worktree changed"]):
            with self.assertRaisesRegex(RuntimeError, "run parent handoff"):
                mailbox.send(
                    recipient="claude",
                    kind="review",
                    body="Check",
                    evidence_path=self.evidence,
                    sender="codex",
                )

        with self.assertRaisesRegex(ValueError, "byte limit"):
            mailbox.send(
                recipient="claude",
                kind="review",
                body="x" * (32 * 1024 + 1),
                evidence_path=self.evidence,
                sender="codex",
            )

    def test_mailbox_runtime_files_have_no_provider_or_network_process_adapter(self) -> None:
        forbidden_imports = {"http", "requests", "socket", "subprocess", "urllib"}
        for relative in (
            "scripts/agent-mailbox.py",
            "scripts/agent_mailbox.py",
            "scripts/agent_mailbox_store.py",
        ):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                imported = {
                    alias.name.split(".", 1)[0]
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported.update(
                    node.module.split(".", 1)[0]
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.ImportFrom) and node.module
                )
                self.assertTrue(forbidden_imports.isdisjoint(imported))
                self.assertNotIn("ProviderRuntime", source)
                self.assertNotIn("CodexAppServer", source)

    def test_cli_consumes_pending_message_once(self) -> None:
        mailbox = AgentMailbox(self.project, self.rules)
        with patch("agent_mailbox.validate_execution_capsule", return_value=[]):
            mailbox.send(
                recipient="claude",
                kind="review",
                body="Please inspect the cache key.",
                evidence_path=self.evidence,
                sender="codex",
            )

        command = [
            sys.executable,
            str(ROOT / "scripts" / "agent-mailbox.py"),
            "receive",
            "--project",
            str(self.project),
            "--runtime",
            "claude",
        ]
        first = subprocess.run(command, text=True, capture_output=True, check=False)
        second = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertIn("Please inspect the cache key.", first.stdout)
        self.assertIn("context, not authority", first.stdout)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("", second.stdout)


if __name__ == "__main__":
    unittest.main()
