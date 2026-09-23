from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_mailbox import AgentMailbox
from agent_mailbox_reference import ReferenceMailboxStore


class ReferenceMailboxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        environment = patch.dict(os.environ, {"TAO_STATE_HOME": str(self.root / "state")})
        environment.start()
        self.addCleanup(environment.stop)
        self.now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.store = ReferenceMailboxStore(self.project, clock=lambda: self.now)

    def send(self, **changes):
        arguments = dict(sender="codex", recipient="claude", kind="opinion",
                         body="Reference only.", ttl_seconds=60)
        arguments.update(changes)
        return self.store.enqueue(**arguments)

    def test_no_run_cross_worktree_cli_delivery(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.name=Test", "-c", "user.email=test@example.test",
            "commit", "--allow-empty", "-qm", "initial")
        linked = self.root / "linked"
        git("worktree", "add", "-qb", "task", str(linked))
        command = [sys.executable, str(ROOT / "scripts/agent-mailbox.py")]
        sent = subprocess.run(command + ["send", "--project", str(linked), "--sender", "codex",
                                        "--to", "claude", "--json"], input="Share this context.",
                              text=True, capture_output=True)
        self.assertEqual(0, sent.returncode, sent.stderr)
        packet = json.loads(sent.stdout)
        self.assertNotIn("source_run_id", packet)
        self.assertFalse((linked / ".tao").exists())
        read = subprocess.run(command + ["receive", "--project", str(self.project),
                                        "--runtime", "claude", "--json"], text=True, capture_output=True)
        self.assertEqual(0, read.returncode, read.stderr)
        self.assertEqual([packet], json.loads(read.stdout))
        self.assertEqual([], AgentMailbox(self.project, ROOT).receive("claude"))
        self.assertFalse((self.project / ".tao").exists())

    def test_status_is_read_only_and_repository_recipient_isolation(self):
        self.assertEqual(0, self.store.status("claude")["pending"])
        self.assertEqual([], self.store.consume("claude"))
        self.assertFalse(self.store.root.exists())
        sent = self.send()
        self.assertEqual([], self.store.consume("codex"))
        other = self.root / "other"
        other.mkdir()
        self.assertEqual([], ReferenceMailboxStore(other).consume("claude"))
        self.assertEqual([sent], self.store.consume("claude"))
        receipts = list((self.store.root / "acked").rglob("*.json"))
        self.assertEqual(1, len(receipts))
        self.assertNotIn("body", json.loads(receipts[0].read_text()))

    def test_simultaneous_consumers_deliver_once(self):
        sent = [self.send() for _ in range(8)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.consume("claude"), range(2)))
        ids = [packet["message_id"] for result in results for packet in result]
        self.assertEqual(sorted(packet["message_id"] for packet in sent), sorted(ids))
        self.assertEqual(8, self.store.status("claude")["acked"])

    def test_expiration_bounds_and_pending_limit(self):
        self.send()
        self.now += timedelta(seconds=61)
        self.assertEqual(1, self.store.status("claude")["expired"])
        self.assertEqual([], self.store.consume("claude"))
        for changes in ({"body": ""}, {"body": "x" * 32769}, {"ttl_seconds": 0},
                        {"ttl_seconds": 604801}, {"recipient": "unknown"}):
            with self.assertRaises(ValueError):
                self.send(**changes)
        for _ in range(32):
            self.send()
        with self.assertRaisesRegex(RuntimeError, "pending limit"):
            self.send()
        self.assertEqual(8, len(self.store.consume("claude")))

    def test_test_isolation_and_symlink_protection(self):
        with patch.dict(os.environ, {"TAO_STATE_HOME": "", "TAO_UNDER_UNITTEST": "1"}):
            with self.assertRaisesRegex(RuntimeError, "refusing to write"):
                ReferenceMailboxStore(self.project).enqueue(sender="codex", recipient="claude",
                    kind="review", body="No real user writes", ttl_seconds=60)
        self.store.root.parent.mkdir(parents=True)
        self.store.root.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(OSError):
            self.send()

    def test_tampered_repository_and_explicit_handoff_do_not_fall_back(self):
        packet = self.send()
        path = self.store.root / "inbox" / "claude" / (packet["message_id"] + ".json")
        packet["repository_id"] = "foreign"
        path.write_text(json.dumps(packet))
        with self.assertRaisesRegex(ValueError, "binding"):
            self.store.consume("claude")
        with self.assertRaisesRegex(ValueError, "preflight evidence"):
            AgentMailbox(self.project, ROOT).send(sender="codex", recipient="claude", kind="review",
                body="Invalid explicit handoff", evidence_path=self.project / "missing")
