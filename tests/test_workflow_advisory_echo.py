from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_advisory_echo import (  # noqa: E402
    MAX_REMEMBERED_SESSIONS,
    already_delivered,
    hook_session_id,
    record_delivery,
)


class AdvisoryRouteIsDeliveredOncePerSessionTests(unittest.TestCase):
    """The prompt hook renders the same route every turn, so it repeats itself.

    It never sees the prompt: a bug fix, a haiku and a release all produced the
    same 10,262 bytes on the reference machine. Delivering that once per
    session is the whole point of this state; every failure mode below has to
    end with the route delivered again rather than lost.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / ".tao").mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_the_first_delivery_is_not_a_repeat(self) -> None:
        self.assertFalse(already_delivered(self.root, "session-a", "digest-1"))

    def test_the_same_route_to_the_same_session_is_a_repeat(self) -> None:
        record_delivery(self.root, "session-a", "digest-1")

        self.assertTrue(already_delivered(self.root, "session-a", "digest-1"))

    def test_a_second_session_is_told_the_route(self) -> None:
        record_delivery(self.root, "session-a", "digest-1")

        self.assertFalse(already_delivered(self.root, "session-b", "digest-1"))

    def test_edited_guidance_is_delivered_again(self) -> None:
        """The digest is the point: a route that changed is news."""

        record_delivery(self.root, "session-a", "digest-1")

        self.assertFalse(already_delivered(self.root, "session-a", "digest-2"))

    def test_a_session_holds_one_route_at_a_time(self) -> None:
        """Reverting the guidance must not resurrect a suppression.

        The session was shown digest-2 last; it no longer holds digest-1, so
        going back to digest-1 is news to it even though it saw that text once.
        """

        record_delivery(self.root, "session-a", "digest-1")
        record_delivery(self.root, "session-a", "digest-2")

        self.assertFalse(already_delivered(self.root, "session-a", "digest-1"))
        self.assertTrue(already_delivered(self.root, "session-a", "digest-2"))

    def test_an_unknown_session_is_always_told(self) -> None:
        record_delivery(self.root, "", "digest-1")

        self.assertFalse(already_delivered(self.root, "", "digest-1"))

    def test_a_project_with_no_run_state_is_not_given_one(self) -> None:
        """Creating `.tao` here could put a cache file in someone's commit."""

        with tempfile.TemporaryDirectory() as bare:
            root = Path(bare)
            record_delivery(root, "session-a", "digest-1")

            self.assertFalse((root / ".tao").exists())
            self.assertFalse(already_delivered(root, "session-a", "digest-1"))

    def test_a_corrupt_cache_costs_a_delivery_not_a_crash(self) -> None:
        record_delivery(self.root, "session-a", "digest-1")
        (self.root / ".tao" / "cache" / "advisory-route.json").write_text(
            "{ not json", encoding="utf-8"
        )

        self.assertFalse(already_delivered(self.root, "session-a", "digest-1"))

    def test_a_cache_that_cannot_be_written_is_not_a_failure(self) -> None:
        """This runs inside a prompt hook; it may never raise into one."""

        with patch(
            "workflow_advisory_echo.Path.replace", side_effect=PermissionError("read-only")
        ):
            record_delivery(self.root, "session-a", "digest-1")

        self.assertFalse(already_delivered(self.root, "session-a", "digest-1"))

    def test_the_remembered_sessions_are_bounded(self) -> None:
        for index in range(MAX_REMEMBERED_SESSIONS + 5):
            record_delivery(self.root, f"session-{index}", "digest-1")

        payload = json.loads(
            (self.root / ".tao" / "cache" / "advisory-route.json").read_text(encoding="utf-8")
        )

        self.assertEqual(MAX_REMEMBERED_SESSIONS, len(payload["deliveries"]))
        self.assertTrue(already_delivered(self.root, "session-36", "digest-1"))
        self.assertFalse(already_delivered(self.root, "session-0", "digest-1"))


class HookPayloadReadsOnlyTheSessionIdTests(unittest.TestCase):
    def test_the_session_id_is_read(self) -> None:
        payload = json.dumps({"session_id": "abc", "prompt": "delete production"})

        self.assertEqual("abc", hook_session_id(payload))

    def test_a_payload_without_a_session_is_unknown(self) -> None:
        self.assertEqual("", hook_session_id(json.dumps({"prompt": "hello"})))

    def test_a_non_json_payload_is_unknown(self) -> None:
        self.assertEqual("", hook_session_id("not json at all"))

    def test_an_empty_payload_is_unknown(self) -> None:
        self.assertEqual("", hook_session_id(""))

    def test_a_non_string_session_is_unknown(self) -> None:
        self.assertEqual("", hook_session_id(json.dumps({"session_id": 7})))


class AdvisoryRouteCommandLineTests(unittest.TestCase):
    """End to end, because the saving only exists if the hook's call gets it."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary_directory.name)
        (self.project / ".tao").mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _route(self, command: str, payload: str, *flags: str) -> str:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "workflow.py"),
                "route",
                command,
                "--advisory",
                "--project",
                str(self.project),
                *flags,
            ],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout

    def test_the_first_prompt_of_a_session_gets_the_whole_route(self) -> None:
        output = self._route("triage", '{"session_id": "s1"}', "--hook-stdin")

        self.assertIn("# Tao Agent OS Workflow Route", output)

    def test_the_next_prompt_gets_one_line_instead(self) -> None:
        self._route("triage", '{"session_id": "s1"}', "--hook-stdin")

        output = self._route("triage", '{"session_id": "s1"}', "--hook-stdin")

        self.assertNotIn("# Tao Agent OS Workflow Route", output)
        self.assertIn("already received it", output)
        self.assertLess(len(output), 300)

    def test_without_the_flag_every_call_prints_the_route(self) -> None:
        """A person running this by hand asked for the route, not a receipt."""

        self._route("triage", '{"session_id": "s1"}', "--hook-stdin")

        output = self._route("triage", '{"session_id": "s1"}')

        self.assertIn("# Tao Agent OS Workflow Route", output)

    def test_the_auto_sentinel_still_sees_the_prompt(self) -> None:
        """Both features want stdin, and stdin can only be drained once.

        `auto` reads the prompt to pick the route and `--hook-stdin` reads the
        session id to decide whether to print it. Reading twice left the second
        one with an empty pipe, so this pins that one read serves both.
        """

        payload = '{"session_id": "s1", "prompt": "테스터에게 앱 배포"}'

        first = self._route("auto", payload, "--hook-stdin")
        second = self._route("auto", payload, "--hook-stdin")

        self.assertIn("Command: `release`", first)
        self.assertIn("`release`", second)
        self.assertIn("already received it", second)


if __name__ == "__main__":
    unittest.main()
