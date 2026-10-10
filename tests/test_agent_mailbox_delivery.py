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
        self.guidance = self.root / "guidance.md"
        self.guidance.write_text("## Live Session Continuity\n\nKeep passed checks.\n\n## Other\n")
        source = patch.object(hook, "_CONTINUITY_SOURCE", self.guidance, create=True)
        source.start()
        self.addCleanup(source.stop)

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

    def test_the_prompt_hook_refreshes_guidance_once_without_pending_messages(self):
        output = json.loads(self._deliver("s1"))["hookSpecificOutput"]
        self.assertEqual("UserPromptSubmit", output["hookEventName"])
        self.assertIn("Keep passed checks.", output["additionalContext"])
        self.assertEqual("", self._deliver("s1"))

    def test_an_existing_session_receives_changed_guidance_without_a_new_task(self):
        self._deliver("s1")
        self.guidance.write_text("## Live Session Continuity\n\nDo not restart checks.\n\n## Other\n")
        output = json.loads(self._deliver("s1"))["hookSpecificOutput"]
        self.assertIn("Do not restart checks.", output["additionalContext"])
        self.assertEqual("", self._deliver("s1"))
        self.assertFalse((self.project / ".tao" / "run-registry.json").exists())

    def test_guidance_is_independent_for_each_runtime_and_session(self):
        payload = {"session_id": "s1", "cwd": str(self.project)}
        self._deliver("s1")
        output = io.StringIO()
        with redirect_stdout(output):
            hook.deliver(payload, "codex")
        self.assertIn("Keep passed checks.", output.getvalue())
        self.assertIn("Keep passed checks.", self._deliver("s2"))

    def test_missing_guidance_does_not_suppress_mailbox_delivery(self):
        self.guidance.unlink()
        packet = self.send()
        self.assertIn(packet["message_id"], self._deliver("s1"))

    def test_other_skill_sections_do_not_trigger_repeated_guidance(self):
        self._deliver("s1")
        self.guidance.write_text(
            "## Live Session Continuity\n\nKeep passed checks.\n\n## Other\nChanged.\n"
        )
        self.assertEqual("", self._deliver("s1"))

    def test_guidance_only_delivery_retries_when_output_fails(self):
        class Closed(io.StringIO):
            def write(self, text):
                raise OSError("closed")

        with self.assertRaises(OSError):
            self._deliver("s1", Closed())
        self.assertIn("Keep passed checks.", self._deliver("s1"))
        self.assertEqual("", self._deliver("s1"))

    def test_mailbox_failure_does_not_suppress_changed_guidance(self):
        with patch.object(SessionDelivery, "claim", side_effect=OSError("unavailable")):
            self.assertIn("Keep passed checks.", self._deliver("s1"))

    def test_real_canonical_section_contains_the_repetition_safeguard(self):
        source = ROOT / "common/skills/agent-operating-skill/SKILL.md"
        with patch.object(hook, "_CONTINUITY_SOURCE", source):
            output = json.loads(self._deliver("s1"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Status questions, impatience", output)
        self.assertIn("Automatic hook checkpoints need no manual checkpoint", output)
        self.assertIn("a completed task stays completed", output)
        self.assertNotIn("## Proportionate Execution", output)

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
