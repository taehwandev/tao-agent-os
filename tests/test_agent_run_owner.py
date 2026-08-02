from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_run_owner
from agent_run_owner import owner_death_is_proven, owner_is_gone
from agent_run_registry import (
    active_runs,
    recover_stale_runs,
    register_run,
    registry_path,
)


def dead_pid() -> int:
    """Return a pid that has provably exited, with no reliance on a clock."""

    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    return process.pid


def abandon_runs(project: Path, *, minutes: int) -> None:
    """Simulate a crashed agent: an old timestamp and a dead owning process."""

    registry = registry_path(project)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for run in payload["runs"]:
        run["updated_at"] = old
        run["owner"] = {"pid": dead_pid(), "start_token": ""}
    registry.write_text(json.dumps(payload), encoding="utf-8")


class OwnerLivenessTests(unittest.TestCase):
    """Silence is not death, and a living owner is not a permanent lease.

    A heartbeat only proves life while hooks keep arriving, so one long build
    between two hooks looked abandoned and another agent's start failed a
    working run out from under it. An owner that is provably gone still frees
    the path at the normal window; an owner that looks alive only buys the run
    a longer window, never an unlimited one.
    """

    @staticmethod
    def _age(project: Path, minutes: int, *, owner_pid: int | None = None) -> None:
        registry = registry_path(project)
        payload = json.loads(registry.read_text(encoding="utf-8"))
        old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        for run in payload["runs"]:
            run["updated_at"] = old
            if owner_pid is not None:
                run["owner"] = {"pid": owner_pid, "start_token": ""}
        registry.write_text(json.dumps(payload), encoding="utf-8")

    def test_silent_run_with_a_living_owner_survives_the_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "one very long build"},
            )
            self._age(project, minutes=90)

            self.assertEqual([], recover_stale_runs(project))
            self.assertEqual(1, len(active_runs(project)))

    def test_negative_control_dead_owner_still_releases_the_path(self) -> None:
        """The control: preserving live work must not resurrect the deadlock."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "crashed agent"},
            )
            abandon_runs(project, minutes=90)

            self.assertEqual(1, len(recover_stale_runs(project)))
            self.assertEqual([], active_runs(project))

    def test_crashed_agent_whose_owner_outlives_it_frees_the_path(self) -> None:
        """The case a liveness veto would deadlock forever.

        An agent can die while the process recorded as its owner keeps running,
        and no hook will ever refresh that record again. Without the ceiling
        the path stays claimed for good, start keeps refusing it, and the edit
        gate that only reads the default evidence file denies every edit.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "agent killed, owner still running"},
            )
            self._age(project, minutes=13 * 60, owner_pid=os.getpid())

            self.assertEqual(1, len(recover_stale_runs(project)))
            self.assertEqual([], active_runs(project))

    def test_negative_control_a_live_owner_still_survives_the_normal_window(self) -> None:
        """The control: the ceiling must not collapse back into a plain sweep."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "still building"},
            )
            self._age(project, minutes=11 * 60, owner_pid=os.getpid())

            self.assertEqual([], recover_stale_runs(project))
            self.assertEqual(1, len(active_runs(project)))

    def test_grace_ceiling_scales_with_the_configured_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "short window"},
            )
            self._age(project, minutes=30, owner_pid=os.getpid())

            self.assertEqual(1, len(recover_stale_runs(project, stale_after_seconds=60)))

    def test_run_recorded_before_owners_existed_is_still_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "pre-upgrade record"},
            )
            registry = registry_path(project)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            for run in payload["runs"]:
                run.pop("owner", None)
            registry.write_text(json.dumps(payload), encoding="utf-8")
            self._age(project, minutes=90)

            self.assertEqual(1, len(recover_stale_runs(project)))

    def test_unusable_owner_identities_never_pass_as_alive(self) -> None:
        self.assertTrue(owner_is_gone(None))
        self.assertTrue(owner_is_gone({}))
        self.assertTrue(owner_is_gone({"pid": "not-a-pid"}))
        self.assertTrue(owner_is_gone({"pid": 0}))
        self.assertTrue(owner_is_gone({"pid": -1}))
        self.assertFalse(owner_is_gone({"pid": os.getpid()}))

    def test_proof_of_death_requires_evidence_that_was_recorded(self) -> None:
        """Callers that skip the waiting period need more than "not alive".

        ``owner_is_gone`` answers True for a record that never had an owner, so
        a sweep acting on it alone would fail every fresh run on a host that
        cannot identify one.
        """

        self.assertTrue(owner_death_is_proven({"pid": dead_pid()}))
        self.assertFalse(owner_death_is_proven({"pid": os.getpid()}))

        for absent in (None, {}, {"pid": None}, {"pid": "not-a-pid"}, {"pid": 0}):
            with self.subTest(owner=absent):
                self.assertTrue(owner_is_gone(absent))
                self.assertFalse(owner_death_is_proven(absent))

    def test_a_host_that_cannot_probe_never_proves_death(self) -> None:
        with patch.object(agent_run_owner.os, "name", "nt"):
            self.assertFalse(owner_death_is_proven({"pid": dead_pid()}))

    def test_parent_lookup_survives_a_host_without_proc(self) -> None:
        """macOS has no /proc, and the whole anchor rests on this lookup."""

        self.assertEqual(os.getppid(), agent_run_owner._parent_pid(os.getpid()))

    def test_linux_parent_lookup_keeps_proc_as_the_first_choice(self) -> None:
        """Darwin support must not add subprocess or libproc work on Linux."""

        with (
            patch.object(
                agent_run_owner.Path,
                "read_text",
                return_value="44001 (python worker) S 44002 0 0 0",
            ),
            patch.object(agent_run_owner, "_darwin_parent_pid") as darwin_parent,
            patch.object(agent_run_owner.subprocess, "run") as ps_run,
        ):
            self.assertEqual(44_002, agent_run_owner._parent_pid(44_001))

        darwin_parent.assert_not_called()
        ps_run.assert_not_called()

    def test_darwin_sandbox_uses_libproc_before_denied_ps(self) -> None:
        """The default sandbox denies ``ps``; do not record the hook as owner."""

        leader = 41_001
        launcher = 41_002
        agent_run_owner._owner_identity.cache_clear()
        try:
            with (
                patch.object(agent_run_owner.os, "name", "posix"),
                patch.object(agent_run_owner.sys, "platform", "darwin"),
                patch.object(agent_run_owner.os, "getsid", return_value=leader),
                patch.object(agent_run_owner.Path, "read_text", side_effect=PermissionError),
                patch.object(
                    agent_run_owner,
                    "_darwin_parent_pid",
                    return_value=launcher,
                    create=True,
                ),
                patch.object(
                    agent_run_owner.subprocess,
                    "run",
                    side_effect=PermissionError,
                ) as ps_run,
                patch.object(agent_run_owner, "_process_start_token", return_value=""),
            ):
                owner = agent_run_owner.process_owner()
        finally:
            agent_run_owner._owner_identity.cache_clear()

        self.assertEqual(launcher, owner["pid"])
        self.assertNotEqual(leader, owner["pid"])
        ps_run.assert_not_called()

    def test_unavailable_parent_lookup_records_no_owner(self) -> None:
        """Unknown is timestamp-only evidence, not the short-lived leader."""

        leader = 42_001
        agent_run_owner._owner_identity.cache_clear()
        try:
            with (
                patch.object(agent_run_owner.os, "name", "posix"),
                patch.object(agent_run_owner.sys, "platform", "darwin"),
                patch.object(agent_run_owner.os, "getsid", return_value=leader),
                patch.object(agent_run_owner.Path, "read_text", side_effect=PermissionError),
                patch.object(
                    agent_run_owner,
                    "_darwin_parent_pid",
                    return_value=0,
                    create=True,
                ),
                patch.object(agent_run_owner.subprocess, "run", side_effect=PermissionError),
            ):
                owner = agent_run_owner.process_owner()
        finally:
            agent_run_owner._owner_identity.cache_clear()

        self.assertEqual({}, owner)

    def test_unavailable_session_lookup_records_no_owner(self) -> None:
        """A direct parent is not proof that it spans the whole agent session."""

        for getsid in (None, Mock(side_effect=OSError)):
            agent_run_owner._owner_identity.cache_clear()
            try:
                with (
                    patch.object(agent_run_owner.os, "name", "posix"),
                    patch.object(agent_run_owner.os, "getsid", getsid),
                    patch.object(agent_run_owner.os, "getppid", return_value=44_001),
                ):
                    owner = agent_run_owner.process_owner()
            finally:
                agent_run_owner._owner_identity.cache_clear()

            self.assertEqual({}, owner)

    def test_owner_is_gone_requires_positive_liveness_evidence(self) -> None:
        """Cover dead, live, reused, and unavailable start-token probes."""

        owner = {"pid": 43_001, "start_token": "recorded"}
        with patch.object(agent_run_owner, "_pid_exists", return_value=False):
            self.assertTrue(owner_is_gone(owner))
        with (
            patch.object(agent_run_owner, "_pid_exists", return_value=True),
            patch.object(agent_run_owner, "_process_start_token", return_value="recorded"),
        ):
            self.assertFalse(owner_is_gone(owner))
        with (
            patch.object(agent_run_owner, "_pid_exists", return_value=True),
            patch.object(agent_run_owner, "_process_start_token", return_value="reused"),
        ):
            self.assertTrue(owner_is_gone(owner))
        with (
            patch.object(agent_run_owner, "_pid_exists", return_value=True),
            patch.object(agent_run_owner, "_process_start_token", return_value=""),
        ):
            self.assertFalse(owner_is_gone(owner))

    def test_owner_anchor_skips_the_short_lived_session_leader(self) -> None:
        """The session leader is the job itself and dies with the tool call."""

        launcher = agent_run_owner._parent_pid(os.getsid(0))
        if launcher <= 1:
            self.skipTest("this session was started by init; no launcher above it")

        self.assertEqual(launcher, agent_run_owner._owner_pid())
        self.assertNotEqual(os.getsid(0), agent_run_owner._owner_pid())

    def test_host_without_a_safe_pid_probe_keeps_the_timestamp_contract(self) -> None:
        """A Windows ``os.kill(pid, 0)`` terminates the target instead of asking."""

        with patch.object(agent_run_owner.os, "name", "nt"):
            self.assertEqual({}, agent_run_owner.process_owner())
            self.assertTrue(owner_is_gone({"pid": os.getpid(), "start_token": ""}))

    def test_current_process_owner_does_not_use_the_runtime_launcher_anchor(self) -> None:
        with (
            patch.object(agent_run_owner.os, "name", "posix"),
            patch.object(agent_run_owner.os, "getpid", return_value=45_001),
            patch.object(agent_run_owner, "_process_start_token", return_value="hook-token"),
            patch.object(
                agent_run_owner,
                "_owner_identity",
                side_effect=AssertionError("runtime launcher lookup must not run"),
            ),
        ):
            owner = agent_run_owner.process_owner(current_process=True)

        self.assertEqual({"pid": 45_001, "start_token": "hook-token"}, owner)


if __name__ == "__main__":
    unittest.main()
