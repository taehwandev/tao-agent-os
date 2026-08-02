from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_run_registry import (
    active_run_bindings,
    active_run_conflict,
    active_runs,
    claim_run,
    recover_stale_runs,
    register_run,
    registry_path,
    resume_run,
    touch_run,
    transition_run,
)


def dead_pid() -> int:
    """Return a pid that has provably exited, with no reliance on a clock."""

    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    return process.pid


def age_runs(project: Path, *, minutes: int, owner_pid: int | None = None) -> None:
    """Backdate every run, optionally rewriting who owns it."""

    registry = registry_path(project)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for run in payload["runs"]:
        run["updated_at"] = old
        if owner_pid is not None:
            owner_field = "claim_owner" if run.get("state") == "claiming" else "owner"
            run[owner_field] = {"pid": owner_pid, "start_token": ""}
    registry.write_text(json.dumps(payload), encoding="utf-8")


def abandon_runs(project: Path, *, minutes: int) -> None:
    """Simulate a crashed agent: an old timestamp and a dead owning process."""

    age_runs(project, minutes=minutes, owner_pid=dead_pid())


def _strip_owners(project: Path) -> None:
    """Simulate a host that cannot identify an owning process at all."""

    registry = registry_path(project)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    for run in payload["runs"]:
        run.pop("owner", None)
        run.pop("claim_owner", None)
    registry.write_text(json.dumps(payload), encoding="utf-8")


def claiming_runs(project: Path) -> list[dict]:
    payload = json.loads(registry_path(project).read_text(encoding="utf-8"))
    return [run for run in payload["runs"] if run.get("state") == "claiming"]


class AgentRunRegistryTests(unittest.TestCase):
    def test_register_and_transition_run_without_content_or_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            run = register_run(
                project,
                evidence,
                {"command": "task", "gates": [], "required_docs": []},
                {"request": "private request text", "request_classified": True},
            )

            self.assertEqual("running", run["state"])
            self.assertNotIn("private request text", json.dumps(run))
            self.assertNotIn(str(project), json.dumps(run))
            self.assertEqual([run["run_id"]], [item["run_id"] for item in active_runs(project)])

            completed = transition_run(project, evidence, "completed")
            self.assertEqual("completed", completed["state"])
            self.assertEqual([], active_runs(project))

    def test_unknown_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                transition_run(Path(directory), Path(directory) / "preflight.json", "unknown")

    def test_run_id_transition_avoids_same_evidence_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / "preflight.json"
            first = register_run(project, evidence, {"command": "task"}, {})
            second = register_run(project, evidence, {"command": "task"}, {})
            completed = transition_run(project, evidence, "completed", run_id=first["run_id"])
            self.assertEqual(first["run_id"], completed["run_id"])
            self.assertEqual("running", [run for run in active_runs(project) if run["run_id"] == second["run_id"]][0]["state"])

    def test_stale_run_is_recovered_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = register_run(project, project / "preflight.json", {"command": "task"}, {})
            abandon_runs(project, minutes=120)

            recovered = recover_stale_runs(project, stale_after_seconds=60)
            self.assertEqual([run["run_id"]], [item["run_id"] for item in recovered])
            self.assertEqual("failed", recovered[0]["state"])
            self.assertEqual("running", resume_run(project, run["run_id"])["state"])

    def test_active_request_cannot_overwrite_the_same_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(
                project,
                evidence,
                {"command": "task"},
                {"request": "first", "request_classified": False},
            )

            self.assertTrue(
                active_run_conflict(
                    project,
                    evidence,
                    command="task",
                    request_intake={"request": "second", "request_classified": False},
                )
            )
            self.assertFalse(
                active_run_conflict(
                    project,
                    project / ".tao" / "runs" / "second" / "preflight.json",
                    command="task",
                    request_intake={"request": "second", "request_classified": False},
                )
            )

            persisted = (project / ".tao" / "run-registry.json").read_text()
            self.assertNotIn("first", persisted)
            self.assertNotIn("second", persisted)


class LiveRunSurvivalTests(unittest.TestCase):
    """A long task must not be failed for being long.

    `updated_at` moved only at register and transition, so a run that stayed
    alive longer than the staleness window between those two points looked
    abandoned and start's sweep failed it out from under a working agent.
    """

    @staticmethod
    def _age(project: Path, minutes: int) -> None:
        registry = project / ".tao" / "run-registry.json"
        payload = json.loads(registry.read_text())
        old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        for run in payload["runs"]:
            run["updated_at"] = old
        registry.write_text(json.dumps(payload), encoding="utf-8")

    def test_heartbeat_keeps_a_long_running_run_alive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(project, evidence, {"command": "task"}, {"request": "long build"})
            self._age(project, minutes=90)

            self.assertIsNotNone(touch_run(project, evidence))

            self.assertEqual([], recover_stale_runs(project))
            self.assertEqual(1, len(active_runs(project)))

    def test_negative_control_abandoned_run_is_still_recovered(self) -> None:
        """The control: without a heartbeat the sweep must still free the path.

        If the heartbeat made recovery unreachable, the original deadlock would
        come straight back and this assertion would break.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "task"},
                {"request": "abandoned"},
            )
            abandon_runs(project, minutes=90)

            self.assertEqual(1, len(recover_stale_runs(project)))
            self.assertEqual([], active_runs(project))

    def test_scoped_sweep_spares_a_run_on_another_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "runs" / "peer" / "preflight.json",
                {"command": "task"},
                {"request": "concurrent peer"},
            )
            abandon_runs(project, minutes=90)

            recovered = recover_stale_runs(
                project,
                evidence_path=project / ".tao" / "preflight.json",
            )

            self.assertEqual([], recovered)
            self.assertEqual(1, len(active_runs(project)))

    def test_heartbeat_ignores_finished_runs_and_other_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(project, evidence, {"command": "task"}, {"request": "done"})
            transition_run(project, evidence, "completed")

            self.assertIsNone(touch_run(project, evidence))
            self.assertIsNone(touch_run(project, project / ".tao" / "other.json"))


class CrashedClaimantRetryTests(unittest.TestCase):
    """An interrupted agent must be able to retry its own request at once.

    Claims are exclusive per invocation, so the retry no longer reuses the
    binding its predecessor left behind. Waiting out the staleness window for a
    claimant already known to be dead locks the most common failure mode --
    session interrupted, user retries immediately -- out of its own path.
    """

    def test_crashed_claimant_frees_a_fresh_binding_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "the task", "request_classified": False}
            claim_run(project, evidence, {"command": "bugfix"}, intake)
            age_runs(project, minutes=10, owner_pid=dead_pid())

            retry = claim_run(project, evidence, {"command": "bugfix"}, intake)

            self.assertFalse(retry["conflict"])
            self.assertEqual(1, len(retry["recovered"]))
            self.assertEqual(
                [retry["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )
            self.assertEqual([], active_runs(project))

    def test_negative_control_a_live_claimant_still_conflicts_at_once(self) -> None:
        """The control: proof of death must not become a general bypass.

        A living claimant holds its path from the first second, or exclusivity
        would degrade into two agents sharing one preflight file.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "the task", "request_classified": False}
            first = claim_run(project, evidence, {"command": "bugfix"}, intake)
            age_runs(project, minutes=10)

            retry = claim_run(project, evidence, {"command": "bugfix"}, intake)

            self.assertTrue(retry["conflict"])
            self.assertEqual([], retry["recovered"])
            self.assertEqual(
                [first["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )

    def test_negative_control_no_owner_evidence_still_waits_out_the_window(self) -> None:
        """The control: absent evidence is not proof, on any host.

        Hosts that cannot identify an owning process record none at all. If
        that counted as death, every run there would be swept the moment it
        registered.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "the task", "request_classified": False}
            claim_run(project, evidence, {"command": "bugfix"}, intake)
            _strip_owners(project)
            age_runs(project, minutes=10)

            self.assertTrue(
                claim_run(project, evidence, {"command": "bugfix"}, intake)["conflict"]
            )

            age_runs(project, minutes=90)

            self.assertFalse(
                claim_run(project, evidence, {"command": "bugfix"}, intake)["conflict"]
            )

    def test_live_owner_keeps_its_extended_window_and_its_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "the task", "request_classified": False}
            claim_run(project, evidence, {"command": "bugfix"}, intake)
            age_runs(project, minutes=90, owner_pid=os.getpid())

            self.assertTrue(
                claim_run(project, evidence, {"command": "bugfix"}, intake)["conflict"]
            )

            age_runs(project, minutes=13 * 60, owner_pid=os.getpid())

            self.assertFalse(
                claim_run(project, evidence, {"command": "bugfix"}, intake)["conflict"]
            )


class ClaimRunTests(unittest.TestCase):
    """Claiming an evidence path must be one decision, not three.

    Checking for a conflict released the lock before the registration took it
    again, so two concurrent starts could both read "free" and both claim the
    same preflight file.
    """

    @staticmethod
    def _claim(project: Path, evidence: Path, request: str, results: list) -> None:
        results.append(
            claim_run(
                project,
                evidence,
                {"command": "bugfix"},
                {"request": request, "request_classified": False},
            )
        )

    def test_only_one_of_two_concurrent_same_request_claims_takes_the_path(self) -> None:
        for attempt in range(5):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                evidence = project / ".tao" / "preflight.json"
                results: list = []
                ready = threading.Barrier(2)

                def claim(request: str) -> None:
                    ready.wait()
                    self._claim(project, evidence, request, results)

                threads = [
                    threading.Thread(target=claim, args=("same request",))
                    for _index in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                self.assertEqual(1, sum(result["conflict"] for result in results))
                self.assertEqual(1, len(claiming_runs(project)))
                self.assertEqual([], active_runs(project))

    def test_negative_control_a_live_conflicting_claim_is_still_rejected(self) -> None:
        """The control: exclusivity must reject, not silently take turns."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            first = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "first"}
            )

            second = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "second"}
            )

            self.assertTrue(second["conflict"])
            self.assertIsNone(second["run"])
            self.assertEqual(
                [first["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )

    def test_successive_same_request_independent_claim_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "same request", "request_classified": False}

            first = claim_run(project, evidence, {"command": "bugfix"}, intake)
            second = claim_run(project, evidence, {"command": "bugfix"}, intake)

            self.assertFalse(first["conflict"])
            self.assertTrue(second["conflict"])
            self.assertIsNone(second["run"])
            self.assertEqual(
                [first["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )

    def test_claimed_run_can_be_explicitly_rebound_by_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            intake = {"request": "same request", "request_classified": False}
            claim = claim_run(project, evidence, {"command": "bugfix"}, intake)

            rebound = register_run(
                project,
                evidence,
                {"command": "bugfix", "gates": ["review"]},
                intake,
                reuse_run_id=claim["run"]["run_id"],
            )

            self.assertEqual(claim["run"]["run_id"], rebound["run_id"])
            self.assertEqual("running", rebound["state"])
            self.assertNotIn("claim_owner", rebound)
            self.assertIn("owner", rebound)
            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in active_runs(project)],
            )
            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in active_run_bindings(project).values()],
            )

    def test_direct_registration_cannot_bypass_an_existing_transient_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            claim = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "work"}
            )

            with self.assertRaisesRegex(ValueError, "requires its reuse_run_id"):
                register_run(
                    project,
                    evidence,
                    {"command": "bugfix"},
                    {"request": "work"},
                )

            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )
            self.assertEqual([], active_runs(project))

    def test_negative_control_direct_registration_without_a_claim_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"

            run = register_run(
                project, evidence, {"command": "bugfix"}, {"request": "work"}
            )

            self.assertEqual("running", run["state"])
            self.assertEqual(
                [run["run_id"]], [item["run_id"] for item in active_runs(project)]
            )

    def test_foreign_process_cannot_promote_a_transient_claim(self) -> None:
        claimant = {"pid": 101, "start_token": "claimant"}
        foreign = {"pid": 202, "start_token": "foreign"}

        def claimant_owner(*, current_process: bool = False) -> dict:
            return claimant

        def foreign_hook_same_runtime(*, current_process: bool = False) -> dict:
            return foreign if current_process else claimant

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            with patch("agent_run_registry.process_owner", side_effect=claimant_owner):
                claim = claim_run(
                    project, evidence, {"command": "bugfix"}, {"request": "work"}
                )

            with (
                patch(
                    "agent_run_registry.process_owner",
                    side_effect=foreign_hook_same_runtime,
                ),
                self.assertRaisesRegex(ValueError, "owned by another process"),
            ):
                register_run(
                    project,
                    evidence,
                    {"command": "bugfix"},
                    {"request": "work"},
                    reuse_run_id=claim["run"]["run_id"],
                )

            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )
            self.assertEqual([], active_runs(project))

    def test_foreign_process_cannot_cancel_or_fail_a_transient_claim(self) -> None:
        claimant = {"pid": 101, "start_token": "claimant"}
        foreign = {"pid": 202, "start_token": "foreign"}

        def claimant_owner(*, current_process: bool = False) -> dict:
            return claimant

        def foreign_hook_same_runtime(*, current_process: bool = False) -> dict:
            return foreign if current_process else claimant

        for state in ("cancelled", "failed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                evidence = project / ".tao" / "preflight.json"
                with patch(
                    "agent_run_registry.process_owner", side_effect=claimant_owner
                ):
                    claim = claim_run(
                        project,
                        evidence,
                        {"command": "bugfix"},
                        {"request": "work"},
                    )

                with (
                    patch(
                        "agent_run_registry.process_owner",
                        side_effect=foreign_hook_same_runtime,
                    ),
                    self.assertRaisesRegex(ValueError, "owned by another process"),
                ):
                    transition_run(
                        project, evidence, state, run_id=claim["run"]["run_id"]
                    )

                self.assertEqual(
                    [claim["run"]["run_id"]],
                    [run["run_id"] for run in claiming_runs(project)],
                )

    def test_claim_owner_can_cancel_its_own_transient_claim(self) -> None:
        claimant = {"pid": 101, "start_token": "claimant"}
        runtime_owner = {"pid": 303, "start_token": "runtime"}

        def owner_identity(*, current_process: bool = False) -> dict:
            return claimant if current_process else runtime_owner

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            with patch("agent_run_registry.process_owner", side_effect=owner_identity):
                claim = claim_run(
                    project, evidence, {"command": "bugfix"}, {"request": "work"}
                )
                cancelled = transition_run(
                    project,
                    evidence,
                    "cancelled",
                    run_id=claim["run"]["run_id"],
                )

            self.assertEqual("cancelled", cancelled["state"])
            self.assertEqual([], claiming_runs(project))

    def test_transient_claim_is_not_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"

            claim = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "new work"}
            )

            self.assertEqual("claiming", claim["run"]["state"])
            self.assertEqual([], active_runs(project))
            self.assertEqual({}, active_run_bindings(project))

    def test_wrong_reuse_id_cannot_append_a_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            claim_run(project, evidence, {"command": "bugfix"}, {"request": "work"})

            with self.assertRaises(ValueError):
                register_run(
                    project,
                    evidence,
                    {"command": "bugfix"},
                    {"request": "work"},
                    reuse_run_id="not-the-claim-id",
                )

            self.assertEqual(1, len(claiming_runs(project)))
            self.assertEqual([], active_runs(project))

    def test_generic_transition_cannot_publish_an_incomplete_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            claim = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "work"}
            )

            with self.assertRaisesRegex(ValueError, "atomic promotion"):
                transition_run(
                    project, evidence, "running", run_id=claim["run"]["run_id"]
                )

            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )
            self.assertEqual({}, active_run_bindings(project))

    def test_generic_transition_cannot_create_a_transient_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            run = register_run(
                project, evidence, {"command": "bugfix"}, {"request": "work"}
            )

            with self.assertRaisesRegex(ValueError, "creation-only"):
                transition_run(project, evidence, "claiming", run_id=run["run_id"])

            self.assertEqual(
                [run["run_id"]], [item["run_id"] for item in active_runs(project)]
            )
            self.assertEqual([], claiming_runs(project))

    def test_claim_recovers_an_abandoned_holder_of_the_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(project, evidence, {"command": "docs"}, {"request": "crashed"})
            abandon_runs(project, minutes=90)

            claim = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "new work"}
            )

            self.assertFalse(claim["conflict"])
            self.assertEqual(1, len(claim["recovered"]))
            self.assertEqual(
                [claim["run"]["run_id"]],
                [run["run_id"] for run in claiming_runs(project)],
            )

    def test_claim_reports_a_silent_holder_it_refused_to_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(project, evidence, {"command": "docs"}, {"request": "long build"})
            age_runs(project, minutes=90)

            claim = claim_run(
                project, evidence, {"command": "bugfix"}, {"request": "new work"}
            )

            self.assertTrue(claim["conflict"])
            self.assertEqual([], claim["recovered"])
            self.assertEqual(1, len(claim["held"]))


if __name__ == "__main__":
    unittest.main()
