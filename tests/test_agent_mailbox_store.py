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

        self.assertEqual([], self._store(project=other).consume("claude"))
        self.assertFalse(target.exists())
        rejected = other / ".tao" / "agent-mailbox" / "runs" / self.run_id / "rejected" / "claude"
        self.assertTrue((rejected / source.name).is_file())

    def _send(self, body: str) -> dict[str, object]:
        return self._store(evidence=self.evidence).enqueue(
            sender="codex", recipient="claude", kind="review", body=body, ttl_seconds=60,
        )

    def test_bad_packet_between_good_ones_neither_loses_nor_blocks_messages(self) -> None:
        inbox = self.project / ".tao" / "agent-mailbox" / "runs" / self.run_id / "inbox" / "claude"
        first = self._send("first")
        bad_path = inbox / ("7" * 32 + ".json")
        bad_path.write_text("{not json", encoding="utf-8")
        second = self._send("second")
        # Force the order good, bad, good regardless of the random ids.
        (inbox / f"{first['message_id']}.json").rename(inbox / ("0" * 32 + ".json"))
        (inbox / f"{second['message_id']}.json").rename(inbox / ("f" * 32 + ".json"))
        for packet, name in ((first, "0" * 32), (second, "f" * 32)):
            path = inbox / f"{name}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["message_id"] = name
            path.write_text(json.dumps(payload), encoding="utf-8")
            packet["message_id"] = name

        self.assertEqual(1, self._store().status("claude")["rejected"])
        self.assertEqual([first, second], self._store().consume("claude"))
        self.assertEqual([], self._store().consume("claude"))
        rejected = inbox.parents[1] / "rejected" / "claude"
        self.assertEqual([bad_path.name], [path.name for path in rejected.iterdir()])
        self.assertEqual(0, self._store().status("claude")["rejected"])
        third = self._send("third")
        self.assertEqual([third], self._store().consume("claude"))

    def test_rejected_packets_are_bounded(self) -> None:
        inbox = self.project / ".tao" / "agent-mailbox" / "runs" / self.run_id / "inbox" / "claude"
        inbox.mkdir(parents=True)
        for index in range(20):
            (inbox / f"{index:032x}.json").write_text("[]", encoding="utf-8")
        self.assertEqual([], self._store().consume("claude"))
        self.assertEqual(16, len(list((inbox.parents[1] / "rejected" / "claude").iterdir())))

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

        self.assertEqual([], self._store().consume("claude"))
        self.assertTrue((source.parents[3] / ("b" * 32) / "rejected" / "claude" / source.name).is_file())

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

        self.assertEqual([], self._store().consume("claude"))
        self.assertFalse(path.exists())

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
