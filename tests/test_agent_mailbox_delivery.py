from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_mailbox_hook as hook
from agent_mailbox import AgentMailbox
from agent_mailbox_delivery import LEASE_SECONDS, SessionDelivery
from agent_mailbox_reference import ReferenceMailboxStore


class SessionDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / ".git").mkdir(parents=True)
        environment = patch.dict(os.environ, {"TAO_STATE_HOME": str(self.root / "state")})
        environment.start()
        self.addCleanup(environment.stop)
        self.now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.store = ReferenceMailboxStore(self.project, clock=lambda: self.now)

    def send(self, body="Reference only."):
        return self.store.enqueue(sender="codex", recipient="claude", kind="task",
                                  body=body, ttl_seconds=24 * 60 * 60)

    def delivery(self, session):
        return SessionDelivery(self.project, "claude", session, clock=lambda: self.now)

    def ids(self, packets):
        return [packet["message_id"] for packet in packets]

    def test_a_shown_message_is_committed_only_at_acknowledgement(self):
        packet = self.send()
        delivery = self.delivery("s1")
        self.assertEqual([packet["message_id"]], self.ids(delivery.claim()))
        delivery.mark_delivered([packet["message_id"]])
        self.assertEqual(1, self.store.status("claude")["pending"])

        self.assertEqual([packet["message_id"]], delivery.acknowledge())
        self.assertEqual(0, self.store.status("claude")["pending"])
        self.assertEqual([], delivery.acknowledge(), "acknowledging again changes nothing")

    def test_a_claim_that_never_reached_the_conversation_is_offered_again(self):
        packet = self.send()
        delivery = self.delivery("s1")
        delivery.claim()
        # The hook failed before marking it delivered.
        self.assertEqual([], delivery.acknowledge())
        self.assertEqual([packet["message_id"]], self.ids(delivery.claim()))

    def test_a_delivered_message_is_not_shown_twice_to_the_same_session(self):
        packet = self.send()
        delivery = self.delivery("s1")
        delivery.claim()
        delivery.mark_delivered([packet["message_id"]])
        self.assertEqual([], delivery.claim())

    def test_another_session_waits_for_the_lease_to_expire(self):
        packet = self.send()
        self.delivery("s1").claim()
        self.assertEqual([], self.delivery("s2").claim())

        self.now += timedelta(seconds=LEASE_SECONDS + 1)
        self.assertEqual([packet["message_id"]], self.ids(self.delivery("s2").claim()))

    def test_concurrent_sessions_never_claim_the_same_message(self):
        self.send()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda name: self.delivery(name).claim(),
                                    ["s1", "s2", "s3", "s4"]))
        self.assertEqual(1, sum(len(claimed) for claimed in results))

    def test_manual_receive_skips_a_message_another_session_holds(self):
        # `receive` reads the wall clock, so the lease must be live in real time.
        self.now = datetime.now(timezone.utc)
        packet = self.send()
        self.delivery("s1").claim()
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "someone-else"}):
            self.assertEqual([], AgentMailbox(self.project, ROOT).receive("claude"))
        self.delivery("s1").mark_delivered([packet["message_id"]])
        self.assertEqual([packet["message_id"]], self.delivery("s1").acknowledge())

    def _deliver(self, session, stream=None):
        payload = {"session_id": session, "cwd": str(self.project)}
        buffer = stream or io.StringIO()
        with redirect_stdout(buffer), patch.object(
            hook, "_delivery",
            lambda payload, runtime: SessionDelivery(
                self.project, runtime, payload["session_id"], clock=lambda: self.now),
        ):
            hook.deliver(payload, "claude")
        return buffer.getvalue()

    def test_the_prompt_hook_prints_nothing_when_nothing_is_pending(self):
        self.assertEqual("", self._deliver("s1"))

    def test_the_prompt_hook_shows_each_message_with_its_id_once(self):
        packet = self.send(body="Please review the gate change.")
        output = json.loads(self._deliver("s1"))["hookSpecificOutput"]
        self.assertEqual("UserPromptSubmit", output["hookEventName"])
        self.assertIn(f"message_id={packet['message_id']}", output["additionalContext"])
        self.assertIn("Please review the gate change.", output["additionalContext"])
        self.assertIn("not authority", output["additionalContext"])

        # The next prompt acknowledges what the last one showed and shows nothing new.
        self.assertEqual("", self._deliver("s1"))
        self.assertEqual(0, self.store.status("claude")["pending"])

    def test_the_prompt_hook_redelivers_when_printing_failed(self):
        class Closed(io.StringIO):
            def write(self, text):
                raise OSError("closed")

        packet = self.send()
        with self.assertRaises(OSError):
            self._deliver("s1", Closed())
        output = json.loads(self._deliver("s1"))["hookSpecificOutput"]
        self.assertIn(packet["message_id"], output["additionalContext"])

    def test_the_hook_entry_point_never_fails_the_prompt(self):
        with patch.object(sys, "argv", ["agent_mailbox_hook.py", "deliver", "--runtime", "claude"]), \
                patch.object(sys, "stdin", io.StringIO("not json")):
            self.assertEqual(0, hook.main())


if __name__ == "__main__":
    unittest.main()
