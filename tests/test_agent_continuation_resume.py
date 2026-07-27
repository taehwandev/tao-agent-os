from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_continuation_resume import resume_last, resume_list
from agent_continuation_store import continuation_path
from agent_execution_capsule_state import git_states_for_paths
from agent_run_owner import process_owner
from agent_run_registry import registry_path, transition_run
from test_agent_continuation_checkpoint import Fixture
from test_agent_continuation_claim import dead_pid


def age(fixture: Fixture, *, minutes: int, owner_pid: int | None = None, run_id: str = "") -> None:
    path = registry_path(fixture.project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for run in payload["runs"]:
        if run_id and run["run_id"] != run_id:
            continue
        run["updated_at"] = old
        if owner_pid is not None:
            run["owner"] = {"pid": owner_pid, "start_token": ""}
    path.write_text(json.dumps(payload), encoding="utf-8")


def entry_for(entries: list[dict], run_id: str) -> dict:
    return next(entry for entry in entries if entry["run_id"] == run_id)


def free_fixture(directory: str, objective: str, **keywords) -> Fixture:
    fixture = Fixture(directory, **keywords)
    fixture.checkpoint("initial", work={"objective": objective})
    # Proven death frees a run at any age, so nothing here backdates a
    # timestamp; the recorded times stay honest for ordering.
    age(fixture, minutes=0, owner_pid=dead_pid(), run_id=fixture.run_id)
    return fixture


class ListTests(unittest.TestCase):
    def test_a_free_packet_is_listed_with_its_bounded_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "finish the resume protocol")

            entry = entry_for(resume_list(fixture.project)["entries"], fixture.run_id)

            self.assertEqual("ok", entry["status"])
            self.assertEqual("free", entry["holder"])
            self.assertEqual("dead_proven", entry["holder_state"])
            self.assertEqual("clean", entry["drift"])
            self.assertEqual("scope", entry["first_unfinished"])
            self.assertEqual("finish the resume protocol", entry["objective"])
            self.assertEqual("task", entry["route_command"])

    def test_holder_states_separate_held_from_unproven_from_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            age(fixture, minutes=90, owner_pid=os.getpid())
            self.assertEqual("held", entry_for(resume_list(fixture.project)["entries"], fixture.run_id)["holder"])

            path = registry_path(fixture.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for run in payload["runs"]:
                run.pop("owner", None)
                run["updated_at"] = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                "unproven", entry_for(resume_list(fixture.project)["entries"], fixture.run_id)["holder"]
            )

    def test_drift_is_reported_without_resuming_anything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "objective under moved bytes")
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            entry = entry_for(resume_list(fixture.project)["entries"], fixture.run_id)

            self.assertEqual("worktree_drift", entry["drift"])
            self.assertEqual(["project_worktree"], entry["changed_signals"])

    def test_a_run_without_a_packet_is_listed_as_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)

            entry = entry_for(resume_list(fixture.project)["entries"], fixture.run_id)

            self.assertEqual("legacy_no_packet", entry["status"])
            self.assertEqual("", entry["objective"])

    def test_an_invalid_packet_is_listed_by_run_id_without_its_prose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "prose that must not be rendered")
            path = continuation_path(fixture.project, fixture.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["notes"] = "a transcript"
            path.write_text(json.dumps(payload), encoding="utf-8")

            entry = entry_for(resume_list(fixture.project)["entries"], fixture.run_id)

            self.assertEqual("invalid_packet", entry["status"])
            self.assertEqual("", entry["objective"])
            self.assertNotIn("prose that must not be rendered", json.dumps(entry))

    def test_completed_and_cancelled_runs_are_not_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "already finished")
            transition_run(
                fixture.project,
                fixture.project / ".tao" / "preflight.json",
                "completed",
                run_id=fixture.run_id,
            )

            self.assertEqual([], resume_list(fixture.project)["entries"])


class ReadOnlyTests(unittest.TestCase):
    """Listing reports; only resuming may take what it inspected."""

    def test_listing_leaves_registry_packet_and_worktree_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "leave everything as it was")
            registry = registry_path(fixture.project).read_bytes()
            packet = continuation_path(fixture.project, fixture.run_id).read_bytes()
            state = git_states_for_paths(fixture.project, fixture.rules)

            resume_list(fixture.project)

            self.assertEqual(registry, registry_path(fixture.project).read_bytes())
            self.assertEqual(packet, continuation_path(fixture.project, fixture.run_id).read_bytes())
            self.assertEqual(state, git_states_for_paths(fixture.project, fixture.rules))


def run_state(fixture: Fixture, run_id: str) -> dict:
    payload = json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))
    return next(run for run in payload["runs"] if run["run_id"] == run_id)


class LastResumeTests(unittest.TestCase):
    def test_the_newest_packet_is_claimed_with_its_resumable_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)

            result = resume_last(older.project)

            self.assertEqual("ready", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])
            self.assertEqual(str(newer.binding_path.resolve()), result["evidence_path"])
            self.assertEqual("task", result["route_command"])
            self.assertEqual("scope", result["checkpoint"])
            self.assertEqual("the newer task", result["work"]["objective"])
            self.assertEqual(1, result["resume_generation"])
            self.assertEqual("running", run_state(newer, newer.run_id)["state"])

    def test_a_stale_heartbeat_cannot_demote_a_fresh_packet(self) -> None:
        """Ordering must not become another way to substitute an older task.

        A run checkpoints far more often than it reaches a lifecycle hook, so
        its registry heartbeat can lag its own packet. If ordering used the
        heartbeat alone the newest work would silently sort below an older run
        and be resumed in its place.
        """

        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)
            age(newer, minutes=5, owner_pid=dead_pid(), run_id=newer.run_id)

            result = resume_last(older.project)

            self.assertEqual("ready", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])

    def test_the_claim_installs_the_resuming_process_as_the_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "taken over by this session")

            resume_last(fixture.project)

            self.assertEqual(process_owner(), run_state(fixture, fixture.run_id)["owner"])


class RefusesRatherThanSkipsTests(unittest.TestCase):
    """The property the whole command depends on.

    A caller asking for the last thing they were doing has the least context in
    which to notice they were handed a different, older task instead. Naming the
    blocker is the honest answer; substituting another run is not.
    """

    def test_a_held_newest_packet_refuses_instead_of_resuming_an_older_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)
            age(newer, minutes=1, owner_pid=os.getpid(), run_id=newer.run_id)

            result = resume_last(older.project)

            self.assertEqual("live_owner_refused", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])
            self.assertIsNone(result["work"])
            self.assertIsNone(result["checkpoint"])
            self.assertEqual(0, run_state(older, older.run_id).get("resume_generation", 0))
            self.assertEqual(
                "the older task",
                entry_for(resume_list(older.project)["entries"], older.run_id)["objective"],
            )

    def test_an_unproven_newest_owner_refuses_instead_of_falling_through(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)
            path = registry_path(older.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for run in payload["runs"]:
                if run["run_id"] == newer.run_id:
                    run.pop("owner", None)
                    run["updated_at"] = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = resume_last(older.project)

            self.assertEqual("owner_unproven_wait", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])
            self.assertEqual(0, run_state(older, older.run_id).get("resume_generation", 0))

    def test_a_drifted_newest_packet_refuses_and_names_the_signal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)
            (older.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            result = resume_last(older.project)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])
            self.assertEqual(["project_worktree"], result["changed_signals"])
            self.assertIsNone(result["work"])
            self.assertEqual("reconcile_required", run_state(newer, newer.run_id)["state"])
            self.assertEqual("running", run_state(older, older.run_id)["state"])

    def test_an_invalid_newest_packet_refuses_without_rendering_its_prose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)
            path = continuation_path(newer.project, newer.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["notes"] = "a transcript"
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = resume_last(older.project)

            self.assertEqual("invalid_packet", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])
            self.assertIsNone(result["work"])
            self.assertNotIn("the newer task", json.dumps(result))
            self.assertEqual(0, run_state(older, older.run_id).get("resume_generation", 0))

    def test_a_newest_legacy_run_refuses_rather_than_resuming_an_older_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            legacy = Fixture(directory, project=older.project, rules=older.rules)

            result = resume_last(older.project)

            self.assertEqual("not_found", result["result"])
            self.assertEqual("legacy_no_packet", result["reason"])
            self.assertEqual(legacy.run_id, result["run_id"])
            self.assertEqual(0, run_state(older, older.run_id).get("resume_generation", 0))

    def test_an_empty_checkout_reports_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            project.mkdir(exist_ok=True)

            result = resume_last(project)

            self.assertEqual("not_found", result["result"])
            self.assertEqual("no_unfinished_packet", result["reason"])


if __name__ == "__main__":
    unittest.main()
