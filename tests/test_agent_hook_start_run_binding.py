from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_start_binding_test", "agent-hook.py")

from agent_run_registry import active_runs, claim_run, register_run, registry_path


def _rewrite_runs(project: Path, *, hours: int, owner_pid: int) -> None:
    registry = registry_path(project)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    for run in payload["runs"]:
        run["updated_at"] = old
        run["owner"] = {"pid": owner_pid, "start_token": ""}
    registry.write_text(json.dumps(payload), encoding="utf-8")


def start_args(project: Path, request: str) -> Namespace:
    return Namespace(
        project=project,
        rules=ROOT,
        command="bugfix",
        request=request,
        request_classified=True,
        classification_evidence="clear-scoped; blockers resolved",
        platform=[],
        concern=[],
        read_only=False,
        evidence=None,
        worker_reservation_token="",
        output=None,
        repair_cycle=0,
    )


class StartRunBindingTests(unittest.TestCase):
    """Start refuses evidence held by another live request -- but only a live one.

    An interrupted run keeps its `running` record forever: recovery lives in a
    separate maintenance entrypoint that no lifecycle hook invokes. Because the
    Claude pre-tool gate only ever reads the default `.tao/preflight.json`, an
    abandoned run that still claims that path denies every later edit with no
    in-band way out. Start therefore sweeps stale runs before deciding whether a
    conflicting request is actually active.
    """

    def _args(self, project: Path, request: str) -> Namespace:
        return start_args(project, request)

    @staticmethod
    def _abandon_runs(project: Path, *, hours: int) -> None:
        """Simulate a crashed agent: an old timestamp and a dead owning process.

        An old timestamp alone no longer means abandoned, because one long build
        between hooks produces exactly the same record as a dead agent.
        """

        exited = subprocess.Popen([sys.executable, "-c", ""])
        exited.wait()
        _rewrite_runs(project, hours=hours, owner_pid=exited.pid)

    def _start(self, args: Namespace) -> tuple[bool, list[str]]:
        """Run start far enough to observe the conflict decision, no further."""

        captured: dict[str, object] = {}

        def record(hook, success, details, *rest, **kwargs):
            captured["success"] = success
            captured["details"] = details
            return 0 if success else 1

        with (
            patch.object(agent_hook, "run_script_main", return_value={"returncode": 1, "stdout": "", "stderr": ""}),
            patch.object(agent_hook, "finish_with_result", side_effect=record),
        ):
            agent_hook.start_hook(args)

        return bool(captured.get("success")), list(captured.get("details") or [])

    def test_abandoned_run_no_longer_holds_the_default_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "docs"},
                {"request": "an earlier, unrelated request", "request_classified": False},
            )
            self._abandon_runs(project, hours=2)

            _success, details = self._start(self._args(project, "repair the review gate defects"))

            self.assertFalse(
                any("already bound to another active request" in line for line in details),
                msg=f"stale run still blocked the default evidence path: {details}",
            )
            self.assertEqual([], active_runs(project))

    def test_start_reclaims_a_path_whose_owner_outlived_a_crashed_agent(self) -> None:
        """An interrupted agent can leave an owner process that keeps running.

        No hook will ever refresh that record again, so if a living owner could
        veto recovery outright the default evidence path would stay claimed for
        good and the edit gate that reads only that path would deny every edit.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "docs"},
                {"request": "an interrupted earlier request", "request_classified": False},
            )
            _rewrite_runs(project, hours=13, owner_pid=os.getpid())

            _success, details = self._start(self._args(project, "repair the review gate defects"))

            self.assertFalse(
                any("already bound to another active request" in line for line in details),
                msg=f"a crashed agent's surviving owner still held the path: {details}",
            )
            self.assertEqual([], active_runs(project))

    def test_negative_control_live_run_still_blocks_the_shared_path(self) -> None:
        """The control: recovery must not turn the conflict guard into a no-op.

        A genuinely concurrent agent holding the same evidence file must still
        be protected, or this fix would trade a deadlock for silent clobbering.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "docs"},
                {"request": "a concurrent live request", "request_classified": False},
            )

            success, details = self._start(self._args(project, "repair the review gate defects"))

            self.assertFalse(success)
            self.assertTrue(
                any("already bound to another active request" in line for line in details),
                msg=f"a live run stopped blocking the shared evidence path: {details}",
            )

    def test_recovery_leaves_an_unrelated_evidence_path_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "runs" / "other" / "preflight.json",
                {"command": "review"},
                {"request": "another agent's isolated run", "request_classified": False},
            )

            self._start(self._args(project, "repair the review gate defects"))

            self.assertEqual(
                ["preflight.json"],
                [run["evidence_name"] for run in active_runs(project)],
            )


class ConcurrentStartClaimTests(unittest.TestCase):
    """Racing starts must produce one winner, not two holders of one file.

    The conflict check released its lock before the registration took it again,
    and the whole preflight ran inside that window. A second start could read
    "no active run" while the first was still working and then overwrite its
    preflight evidence, so both agents ran against one shared ledger.
    """

    def _race(self, project: Path) -> tuple[list[str], list[list[str]]]:
        reached_preflight: list[str] = []
        reported: list[list[str]] = []
        loser_finished = threading.Event()
        ready = threading.Barrier(2)
        guard = threading.Lock()

        def preflight(*_args, **_kwargs) -> dict[str, object]:
            with guard:
                reached_preflight.append("preflight")
            # Hold the winner inside preflight until the other start has
            # decided. That is exactly the window the old check-then-register
            # sequence left open, so a lost claim shows up as a second entry
            # here rather than as a timing-dependent flake.
            loser_finished.wait(timeout=2)
            return {"returncode": 1, "stdout": "", "stderr": ""}

        def record(_hook, _success, details, *_rest, **_kwargs) -> int:
            with guard:
                reported.append(list(details))
            return 1

        def start(request: str) -> None:
            ready.wait()
            agent_hook.start_hook(start_args(project, request))
            loser_finished.set()

        with (
            patch.object(agent_hook, "run_script_main", side_effect=preflight),
            patch.object(agent_hook, "finish_with_result", side_effect=record),
        ):
            threads = [
                threading.Thread(target=start, args=("same concurrent request",))
                for _index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        return reached_preflight, reported

    def test_only_one_of_two_concurrent_starts_claims_the_shared_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            reached_preflight, reported = self._race(project)

            refusals = [
                details
                for details in reported
                if any("already bound to another active request" in line for line in details)
            ]
            self.assertEqual(1, len(reached_preflight), msg=f"both starts claimed the path: {reported}")
            self.assertEqual(1, len(refusals), msg=f"no start was refused: {reported}")

    def test_successive_same_request_start_is_refused_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            request = "same successive request"
            claimed = claim_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "bugfix"},
                {
                    "request": request,
                    "request_classified": True,
                    "classification_evidence": "clear-scoped; blockers resolved",
                },
            )
            captured: dict[str, object] = {}

            def record(_hook, success, details, *_rest, **_kwargs):
                captured["success"] = success
                captured["details"] = details
                return 0 if success else 1

            with (
                patch.object(
                    agent_hook,
                    "run_script_main",
                    side_effect=AssertionError("conflicting start reached preflight"),
                ),
                patch.object(agent_hook, "finish_with_result", side_effect=record),
            ):
                agent_hook.start_hook(start_args(project, request))

            self.assertFalse(captured["success"])
            self.assertTrue(
                any(
                    "already bound to another active request" in line
                    for line in captured["details"]
                )
            )
            self.assertEqual(
                [claimed["run"]["run_id"]],
                [run["run_id"] for run in active_runs(project)],
            )

    def test_negative_control_a_failed_start_gives_the_path_back(self) -> None:
        """The control: claiming before preflight must not strand the path.

        Claiming early is what makes the decision atomic, so a start that then
        fails has to release its claim or the next attempt would be refused for
        a whole staleness window.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            self._race(project)

            self.assertEqual([], active_runs(project))
            states = [
                run["state"]
                for run in json.loads(registry_path(project).read_text(encoding="utf-8"))["runs"]
            ]
            self.assertEqual(["cancelled"], states)


class HeartbeatPlacementTests(unittest.TestCase):
    """The heartbeat must cover every hook except `start`.

    `start` is the one caller that must not refresh: it sweeps stale runs to
    claim an evidence path, and touching the record first would revive the very
    run it needs to replace. Every other hook is an agent at work.
    """

    HOOKS = ("review", "gate", "gate-batch", "handoff", "finish", "repair-verify")

    def _hooks_that_refresh(self) -> set:
        refreshed = set()

        for hook in self.HOOKS + ("start",):
            with (
                patch.object(agent_hook, "_refresh_run_heartbeat") as heartbeat,
                patch.object(agent_hook, "_parse_args") as parse,
                patch.object(agent_hook, "_lifecycle_evidence_error", return_value=""),
                patch.object(agent_hook, "_apply_worker_evidence_boundary", return_value=""),
                patch.object(agent_hook, "start_hook", return_value=0),
                patch.object(agent_hook, "review_hook", return_value=0),
                patch.object(agent_hook, "handoff_hook", return_value=0),
                patch.object(agent_hook, "gate_hook", return_value=0),
                patch.object(agent_hook, "gate_batch_hook", return_value=0),
                patch.object(agent_hook, "finish_hook", return_value=0),
                patch.object(agent_hook, "create_repair_receipt", return_value={}),
                patch.object(agent_hook, "finish_with_result", return_value=0),
            ):
                parse.return_value = Namespace(
                    hook=hook,
                    project=Path("/tmp/project"),
                    rules=ROOT,
                    evidence=None,
                    output=None,
                    repair_cycle=0,
                    request="a clear scoped request",
                    request_classified=False,
                    classification_evidence="",
                    gate_name="orient",
                    review_path=[],
                    review_scope="working-tree",
                    worker_reservation_token="",
                    repair_target=None,
                    resume_checkpoint=None,
                    repair_verification_kind=None,
                    repair_test_selector=None,
                    repair_receipt_output=None,
                )
                try:
                    agent_hook.main()
                except SystemExit:
                    pass
                if heartbeat.called:
                    refreshed.add(hook)
        return refreshed

    def test_every_post_start_hook_refreshes_the_run(self) -> None:
        refreshed = self._hooks_that_refresh()

        for hook in self.HOOKS:
            with self.subTest(hook=hook):
                self.assertIn(hook, refreshed)

    def test_negative_control_start_never_refreshes(self) -> None:
        """The control: a refreshing start would revive the run it must claim."""

        self.assertNotIn("start", self._hooks_that_refresh())


if __name__ == "__main__":
    unittest.main()
