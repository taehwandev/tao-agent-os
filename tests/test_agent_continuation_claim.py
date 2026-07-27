from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_continuation_claim
from agent_continuation_claim import claim_resume
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_run_owner import owner_death_is_proven, process_owner
from agent_run_registry import (
    recover_stale_runs,
    registry_path,
    resume_holder_state,
    resume_run,
    transition_run,
)
from test_agent_continuation_checkpoint import Fixture

CHILD = """
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from agent_continuation_checkpoint import write_continuation_checkpoint

project, rules, binding = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[5])
run_id = sys.argv[4]
if os.environ.get("TAO_TEST_CHECKPOINT") == "1":
    write_continuation_checkpoint(
        project=project,
        rules=rules,
        run_id=run_id,
        kind="initial",
        binding_path=binding,
        work={"objective": "work that must outlive this process"},
    )
registry = project / ".tao" / "run-registry.json"
payload = json.loads(registry.read_text(encoding="utf-8"))
for run in payload["runs"]:
    run["owner"] = {"pid": os.getpid(), "start_token": ""}
registry.write_text(json.dumps(payload), encoding="utf-8")
print("READY", flush=True)
time.sleep(300)
"""


def dead_pid() -> int:
    """Return a pid that has provably exited, with no reliance on a clock."""

    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    return process.pid


def age(fixture: Fixture, *, minutes: int, owner_pid: int | None = None) -> None:
    path = registry_path(fixture.project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for run in payload["runs"]:
        run["updated_at"] = old
        if owner_pid is not None:
            run["owner"] = {"pid": owner_pid, "start_token": ""}
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_record(fixture: Fixture) -> dict:
    payload = json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))
    return next(run for run in payload["runs"] if run["run_id"] == fixture.run_id)


def kill_after_checkpoint(fixture: Fixture, *, write_checkpoint: bool) -> None:
    """Run a real process that dies with no shutdown path of any kind."""

    environment = dict(os.environ, TAO_TEST_CHECKPOINT="1" if write_checkpoint else "0")
    process = subprocess.Popen(
        [
            sys.executable, "-c", CHILD, str(ROOT / "scripts"),
            str(fixture.project), str(fixture.rules), fixture.run_id, str(fixture.binding_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        if process.stdout.readline().strip() != "READY":
            raise AssertionError("the child never reached its checkpoint")
    finally:
        process.kill()
        process.wait()
        process.stdout.close()


class KilledOwnerTests(unittest.TestCase):
    def test_a_checkpoint_survives_a_process_that_never_shut_down(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)

            kill_after_checkpoint(fixture, write_checkpoint=True)

            stored = read_continuation_packet(
                fixture.project, continuation_path(fixture.project, fixture.run_id)
            )
            self.assertEqual("ok", stored["status"])
            self.assertEqual("dead_proven", resume_holder_state(run_record(fixture)))

            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("ready", result["result"])
            self.assertEqual("running", run_record(fixture)["state"])
            self.assertEqual(
                "work that must outlive this process", result["packet"]["work"]["objective"]
            )

    def test_negative_control_without_the_during_work_writer_nothing_survives(self) -> None:
        """The control: the packet is what survives, not the registry record.

        A design that wrote only at shutdown leaves this exact state, and the
        run becomes unresumable rather than resumable-from-an-older-point.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)

            kill_after_checkpoint(fixture, write_checkpoint=False)

            self.assertEqual(
                "not_found",
                read_continuation_packet(
                    fixture.project, continuation_path(fixture.project, fixture.run_id)
                )["status"],
            )
            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)
            self.assertEqual("invalid_packet", result["result"])

    def test_the_resuming_process_becomes_the_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())

            claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            record = run_record(fixture)
            self.assertEqual(process_owner(), record["owner"])
            self.assertFalse(owner_death_is_proven(record["owner"]))
            self.assertEqual([], recover_stale_runs(fixture.project, stale_after_seconds=1))

    def test_negative_control_the_low_level_state_flip_is_swept_again_at_once(self) -> None:
        """The control: this is why ``resume_run`` is not the public primitive.

        It returns the record to running with the dead owner still installed,
        so proof of death still holds and the next sweep fails it immediately.
        The resume achieves nothing until the new owner is installed.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())
            transition_run(
                fixture.project,
                fixture.project / ".tao" / "preflight.json",
                "failed",
                run_id=fixture.run_id,
            )

            revived = resume_run(fixture.project, fixture.run_id)

            self.assertEqual("running", revived["state"])
            self.assertTrue(owner_death_is_proven(revived["owner"]))
            self.assertEqual(1, len(recover_stale_runs(fixture.project, stale_after_seconds=1)))


class InterruptedMutationTests(unittest.TestCase):
    def _interrupted(self, directory: str, *, change_bytes: bool) -> Fixture:
        fixture = Fixture(directory)
        fixture.checkpoint("initial")
        fixture.checkpoint("pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]})
        if change_bytes:
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
        age(fixture, minutes=1, owner_pid=dead_pid())
        return fixture

    def test_untouched_bytes_resume_and_clear_the_pending_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._interrupted(directory, change_bytes=False)

            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("ready", result["result"])
            self.assertIsNone(result["packet"]["checkpoint"]["mutation_pending"])
            self.assertEqual("running", run_record(fixture)["state"])
            self.assertFalse((fixture.binding_path.parent / ".mutation-baseline.json").exists())

    def test_changed_bytes_require_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._interrupted(directory, change_bytes=True)
            before = continuation_path(fixture.project, fixture.run_id).read_bytes()

            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual("reconcile_required", result["phase"])
            self.assertIsNone(result["packet"])
            self.assertEqual("reconcile_required", run_record(fixture)["state"])
            self.assertEqual(
                before, continuation_path(fixture.project, fixture.run_id).read_bytes()
            )
            self.assertTrue((fixture.binding_path.parent / ".mutation-baseline.json").exists())


class AuthoritativeDriftTests(unittest.TestCase):
    def test_a_caller_cannot_inject_a_forged_clean_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())

            with self.assertRaises(TypeError):
                claim_resume(
                    fixture.project,
                    fixture.run_id,
                    expected_generation=0,
                    drift={"status": "clean"},  # type: ignore[call-arg]
                )

            self.assertEqual(0, run_record(fixture)["resume_generation"])

    def test_disabling_the_verifier_cannot_bless_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
            age(fixture, minutes=1, owner_pid=dead_pid())
            forged = {
                "status": "clean",
                "phase": "scoped",
                "changed_signals": [],
                "affected_paths": [],
                "pending_state": None,
            }

            with patch.object(agent_continuation_claim, "verify_drift", return_value=forged):
                result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("drift_refused", result["result"])
            self.assertIn("project_worktree", result["changed_signals"])

    def test_mutation_between_capture_and_registry_cas_prevents_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())
            capture = agent_continuation_claim._capture_validation

            def capture_then_mutate(*args):
                result = capture(*args)
                (fixture.project / "src" / "module.py").write_text(
                    "value = 2\n", encoding="utf-8"
                )
                return result

            with patch.object(
                agent_continuation_claim,
                "_capture_validation",
                side_effect=capture_then_mutate,
            ):
                result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual("reconcile_required", run_record(fixture)["state"])
            self.assertIn("project_worktree", result["changed_signals"])

    def test_final_invalidation_capture_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())

            with patch.object(
                agent_continuation_claim,
                "_current_capture",
                side_effect=RuntimeError("capture unavailable"),
            ):
                result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual("reconcile_required", run_record(fixture)["state"])
            self.assertIsNone(result["packet"])

    def test_pending_clear_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.checkpoint(
                "pre_mutation",
                mutation={"kind": "update", "paths": ["src/module.py"]},
            )
            age(fixture, minutes=1, owner_pid=dead_pid())

            with patch.object(
                agent_continuation_claim,
                "_clear_pending_mutation",
                side_effect=OSError("replace unavailable"),
            ):
                result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual("reconcile_required", run_record(fixture)["state"])
            self.assertIn("pending_mutation", result["changed_signals"])


class OwnerPolicyTests(unittest.TestCase):
    def _claim(self, fixture: Fixture) -> dict:
        return claim_resume(fixture.project, fixture.run_id, expected_generation=0)

    def test_a_live_owner_holds_the_run_inside_its_grace_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=90, owner_pid=os.getpid())

            result = self._claim(fixture)

            self.assertEqual("live_owner_refused", result["result"])
            self.assertEqual("running", run_record(fixture)["state"])
            self.assertEqual(0, run_record(fixture).get("resume_generation", 0))

    def test_the_grace_ceiling_still_releases_a_live_looking_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=13 * 60, owner_pid=os.getpid())

            self.assertEqual("ready", self._claim(fixture)["result"])

    def test_proven_death_releases_the_run_at_any_age(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=0, owner_pid=dead_pid())

            self.assertEqual("ready", self._claim(fixture)["result"])

    def test_absent_owner_evidence_waits_out_its_bounded_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            path = registry_path(fixture.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for run in payload["runs"]:
                run.pop("owner", None)
            path.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual("owner_unproven_wait", self._claim(fixture)["result"])

            age(fixture, minutes=90)

            self.assertEqual("ready", self._claim(fixture)["result"])

    def test_a_killed_resuming_owner_is_recovered_by_the_shared_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            path = registry_path(fixture.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runs"][0].update(state="resuming", owner={"pid": dead_pid(), "start_token": ""})
            path.write_text(json.dumps(payload), encoding="utf-8")

            recovered = recover_stale_runs(fixture.project, stale_after_seconds=1)

            self.assertEqual([fixture.run_id], [item["run_id"] for item in recovered])
            self.assertEqual("failed", run_record(fixture)["state"])


class GenerationTests(unittest.TestCase):
    def test_only_one_of_two_concurrent_claims_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())
            results: list[dict] = []
            ready = threading.Barrier(2)

            def claim() -> None:
                ready.wait()
                results.append(
                    claim_resume(fixture.project, fixture.run_id, expected_generation=0)
                )

            threads = [threading.Thread(target=claim) for _index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(1, sum(item["result"] == "ready" for item in results))
            self.assertEqual(1, sum(item["result"] == "claim_lost" for item in results))
            self.assertEqual(1, run_record(fixture)["resume_generation"])

    def test_a_stale_generation_cannot_take_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())
            self.assertEqual(
                "ready",
                claim_resume(fixture.project, fixture.run_id, expected_generation=0)["result"],
            )
            age(fixture, minutes=1, owner_pid=dead_pid())

            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("claim_lost", result["result"])
            self.assertEqual(1, run_record(fixture)["resume_generation"])


class BindingTests(unittest.TestCase):
    def test_a_moved_binding_invalidates_the_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=1, owner_pid=dead_pid())
            preflight = dict(fixture.preflight)
            preflight["route"] = {**preflight["route"], "gates": ["scope"]}
            fixture.binding_path.write_text(json.dumps(preflight), encoding="utf-8")

            result = claim_resume(fixture.project, fixture.run_id, expected_generation=0)

            self.assertEqual("invalid_packet", result["result"])
            self.assertEqual("running", run_record(fixture)["state"])

    def test_a_completed_run_is_not_a_resume_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            transition_run(
                fixture.project,
                fixture.project / ".tao" / "preflight.json",
                "completed",
                run_id=fixture.run_id,
            )

            self.assertEqual(
                "not_found",
                claim_resume(fixture.project, fixture.run_id, expected_generation=0)["result"],
            )


if __name__ == "__main__":
    unittest.main()
