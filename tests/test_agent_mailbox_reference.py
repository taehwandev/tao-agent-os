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
    def test_receipt_cleanup_failure_returns_committed_packet(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        import io
        store = self.store
        send = self.send
        send(body="previous")
        store.consume("claude")
        packet = send(body="cleanup")
        unlink = Path.unlink
        def failing_cleanup(path, *args, **kwargs):
            if "acked" in path.parts:
                raise OSError("cleanup failed")
            return unlink(path, *args, **kwargs)
        with patch("agent_mailbox_reference._MAX_ACKS", 1), patch.object(Path, "unlink", failing_cleanup), redirect_stderr(io.StringIO()):
            self.assertEqual([packet], store.consume("claude"))
        self.assertEqual([], store.consume("claude"))

    def test_io_failures_preserve_delivery_and_retry(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        import io
        from agent_mailbox_reference import atomic_write_json
        store = self.store
        send = self.send
        packets = sorted([send(body="first"), send(body="second")],
                         key=lambda packet: packet["message_id"])
        calls = 0
        def failing_write(path, payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated ack failure")
            return atomic_write_json(path, payload)
        warning = io.StringIO()
        with patch("agent_mailbox_reference.atomic_write_json", side_effect=failing_write), redirect_stderr(warning):
            self.assertEqual(packets[:1], store.consume("claude"))
        self.assertIn("partial delivery", warning.getvalue())
        self.assertEqual(packets[1:], store.consume("claude"))
        self.assertEqual([], store.consume("claude"))

    def test_unlink_failure_after_ack_delivers_once(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        import io
        store = self.store
        send = self.send
        packet = send(body="kept")
        unlink = Path.unlink
        def failing_unlink(path, *args, **kwargs):
            if "inbox" in path.parts:
                raise OSError("simulated unlink failure")
            return unlink(path, *args, **kwargs)
        warning = io.StringIO()
        with patch.object(Path, "unlink", failing_unlink), redirect_stderr(warning):
            self.assertEqual([packet], store.consume("claude"))
        self.assertIn("partial delivery", warning.getvalue())
        self.assertEqual([], store.consume("claude"))

    def test_first_ack_failure_raises_and_preserves_message(self):
        from unittest.mock import patch
        store = self.store
        send = self.send
        packet = send(body="retry")
        with patch("agent_mailbox_reference.atomic_write_json", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                store.consume("claude")
        self.assertEqual([packet], store.consume("claude"))

    def test_read_io_failure_preserves_packet_for_retry(self):
        from unittest.mock import patch
        store = self.store
        send = self.send
        packet = send(body="retry read")
        read_text = Path.read_text
        def failing_read(path, *args, **kwargs):
            if "inbox" in path.parts:
                raise OSError("read failed")
            return read_text(path, *args, **kwargs)
        with patch.object(Path, "read_text", failing_read):
            with self.assertRaises(OSError):
                store.consume("claude")
        self.assertEqual([packet], store.consume("claude"))

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

    def _ordered_good_bad_good(self):
        inbox = self.store.root / "inbox" / "claude"
        good = []
        for name, body in (("0" * 32, "first"), ("f" * 32, "second")):
            packet = self.send(body=body)
            (inbox / f"{packet['message_id']}.json").unlink()
            packet["message_id"] = name
            (inbox / f"{name}.json").write_text(json.dumps(packet))
            good.append(packet)
        bad = inbox / ("7" * 32 + ".json")
        bad.write_bytes(b"\xff\xfe not utf-8")
        return good, bad

    def test_bad_packet_between_good_ones_is_quarantined_not_blocking(self):
        good, bad = self._ordered_good_bad_good()
        self.assertEqual(1, self.store.status("claude")["rejected"])
        self.assertEqual(good, self.store.consume("claude"))
        self.assertEqual([], self.store.consume("claude"))
        self.assertTrue((self.store.root / "rejected" / "claude" / bad.name).is_file())
        third = self.send(body="third")
        self.assertEqual([third], self.store.consume("claude"))
        self.assertEqual(0, self.store.status("claude")["rejected"])

    def test_send_expiry_sweep_survives_a_bad_packet(self):
        good, bad = self._ordered_good_bad_good()
        sent = self.send(body="after bad")
        self.assertFalse(bad.exists())
        received = self.store.consume("claude")
        self.assertEqual(sorted(p["message_id"] for p in good + [sent]),
                         sorted(p["message_id"] for p in received))

    def test_tampered_repository_and_explicit_handoff_do_not_fall_back(self):
        packet = self.send()
        path = self.store.root / "inbox" / "claude" / (packet["message_id"] + ".json")
        packet["repository_id"] = "foreign"
        path.write_text(json.dumps(packet))
        self.assertEqual([], self.store.consume("claude"))
        self.assertTrue((self.store.root / "rejected" / "claude" / path.name).is_file())
        with self.assertRaisesRegex(ValueError, "preflight evidence"):
            AgentMailbox(self.project, ROOT).send(sender="codex", recipient="claude", kind="review",
                body="Invalid explicit handoff", evidence_path=self.project / "missing")
