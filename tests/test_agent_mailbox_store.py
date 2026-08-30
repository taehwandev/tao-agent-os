from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_mailbox_store import MailboxStore


class MailboxStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.project = Path(self._temporary.name) / "project"
        self.run_id = "a" * 32
        self.evidence = self.project / ".tao" / "runs" / self.run_id / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.evidence.write_text("{}\n", encoding="utf-8")
        self.now = datetime(2026, 8, 30, 1, 2, 3, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _store(self, project: Path | None = None, evidence: Path | None = None) -> MailboxStore:
        return MailboxStore(
            project or self.project,
            evidence_path=evidence,
            clock=lambda: self.now,
        )

    def test_message_is_atomic_and_consumed_exactly_once(self) -> None:
        packet = self._store(evidence=self.evidence).enqueue(
            sender="codex",
            recipient="claude",
            kind="review",
            body="Check the cache invalidation boundary.",
            ttl_seconds=60,
        )
        mailbox_root = self.project / ".tao" / "agent-mailbox"

        first = self._store().consume("claude")
        second = self._store().consume("claude")

        self.assertEqual([packet], first)
        self.assertEqual([], second)
        self.assertEqual([], list(mailbox_root.rglob("*.tmp")))
        receipts = list(mailbox_root.rglob("acked/claude/*.json"))
        self.assertEqual(1, len(receipts))
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(packet["message_id"], receipt["message_id"])
        self.assertNotIn("body", receipt)

    def test_expired_message_is_removed_without_delivery(self) -> None:
        self._store(evidence=self.evidence).enqueue(
            sender="codex",
            recipient="claude",
            kind="opinion",
            body="Short-lived question",
            ttl_seconds=1,
        )
        self.now += timedelta(seconds=2)

        self.assertEqual([], self._store().consume("claude"))
        self.assertEqual(0, self._store().status("claude")["pending"])

    def test_body_free_acknowledgements_are_bounded(self) -> None:
        for index in range(70):
            self._store(evidence=self.evidence).enqueue(
                sender="codex",
                recipient="claude",
                kind="review",
                body=f"Message {index}",
                ttl_seconds=60,
            )
            self._store().consume("claude")

        receipts = list((self.project / ".tao" / "agent-mailbox").rglob("acked/claude/*.json"))
        self.assertEqual(64, len(receipts))

    def test_copied_packet_is_rejected_in_another_project(self) -> None:
        packet = self._store(evidence=self.evidence).enqueue(
            sender="codex",
            recipient="claude",
            kind="review",
            body="Project-bound question",
            ttl_seconds=60,
        )
        source = next((self.project / ".tao" / "agent-mailbox").rglob(f"{packet['message_id']}.json"))
        other = self.project.parent / "other"
        target = other / ".tao" / "agent-mailbox" / "runs" / self.run_id / "inbox" / "claude" / source.name
        target.parent.mkdir(parents=True)
        shutil.copyfile(source, target)

        with self.assertRaisesRegex(ValueError, "different project"):
            self._store(project=other).consume("claude")

    def test_packet_moved_to_another_run_is_rejected(self) -> None:
        packet = self._store(evidence=self.evidence).enqueue(
            sender="codex",
            recipient="claude",
            kind="review",
            body="Run-bound question",
            ttl_seconds=60,
        )
        source = next((self.project / ".tao" / "agent-mailbox").rglob(f"{packet['message_id']}.json"))
        target = source.parents[3] / ("b" * 32) / "inbox" / "claude" / source.name
        target.parent.mkdir(parents=True)
        source.replace(target)

        with self.assertRaisesRegex(ValueError, "different Tao run"):
            self._store().consume("claude")

    def test_tampered_packet_cannot_extend_the_maximum_ttl(self) -> None:
        packet = self._store(evidence=self.evidence).enqueue(
            sender="codex",
            recipient="claude",
            kind="review",
            body="TTL-bound question",
            ttl_seconds=60,
        )
        path = next((self.project / ".tao" / "agent-mailbox").rglob(f"{packet['message_id']}.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["expires_at"] = (self.now + timedelta(days=8)).isoformat()
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "invalid TTL"):
            self._store().consume("claude")

    def test_symlinked_mailbox_is_rejected_without_external_write(self) -> None:
        external = self.project.parent / "external"
        external.mkdir()
        tao = self.project / ".tao"
        tao.mkdir(parents=True, exist_ok=True)
        (tao / "agent-mailbox").symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(OSError, "symbolic links"):
            self._store(evidence=self.evidence).enqueue(
                sender="codex",
                recipient="claude",
                kind="review",
                body="Do not escape",
                ttl_seconds=60,
            )
        self.assertEqual([], list(external.iterdir()))


if __name__ == "__main__":
    unittest.main()
