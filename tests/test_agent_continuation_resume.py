from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_continuation_resume
from agent_continuation_resume import resume_last, resume_list
from agent_continuation_store import continuation_path
from agent_execution_capsule_state import git_states_for_paths
from agent_hook_resume import _ready_lines
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


def forget_run(fixture: Fixture, run_id: str) -> None:
    """Prune one run from the registry the way its bounded history does."""

    path = registry_path(fixture.project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runs"] = [run for run in payload["runs"] if run["run_id"] != run_id]
    path.write_text(json.dumps(payload), encoding="utf-8")


class UnregisteredPacketTests(unittest.TestCase):
    """The registry keeps a bounded history; packets outlive what it drops.

    A packet whose record was pruned cannot be claimed -- the owner and
    generation a claim compares against are gone, so it returns `claim_lost` --
    and cannot be checkpointed either. Listing it as free advertised work
    nobody could take, and paid a drift verification each time to advertise it.
    """

    def test_a_packet_whose_run_the_registry_dropped_is_not_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kept = free_fixture(directory, "the run still on record")
            forgotten = free_fixture(
                directory, "a run the registry no longer has", project=kept.project, rules=kept.rules
            )
            forget_run(kept, forgotten.run_id)

            listing = resume_list(kept.project)

            self.assertEqual([kept.run_id], [entry["run_id"] for entry in listing["entries"]])
            self.assertEqual(1, listing["unregistered_packets"])
            self.assertTrue(
                continuation_path(kept.project, forgotten.run_id).is_file(),
                "the packet is still on disk; only its candidacy is withdrawn",
            )

    def test_resume_never_selects_or_names_a_dropped_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kept = free_fixture(directory, "the run still on record")
            forgotten = free_fixture(
                directory,
                "a run the registry no longer has",
                project=kept.project,
                rules=kept.rules,
            )
            forget_run(kept, forgotten.run_id)

            newest = resume_last(kept.project)
            named = resume_last(kept.project, run_id=forgotten.run_id)

            self.assertEqual("ready", newest["result"])
            self.assertEqual(kept.run_id, newest["run_id"], "the newest slot skips the dropped run")
            self.assertEqual("not_found", named["result"])
            self.assertEqual("run_id_not_unfinished", named["reason"])
            self.assertNotIn("a run the registry no longer has", json.dumps(named))

    def test_a_dropped_run_costs_no_drift_verification(self) -> None:
        """Verifying drift is the expensive half, and it bought nothing here."""

        with tempfile.TemporaryDirectory() as directory:
            kept = free_fixture(directory, "the run still on record")
            for index in range(3):
                dropped = free_fixture(
                    directory, f"dropped {index}", project=kept.project, rules=kept.rules
                )
                forget_run(kept, dropped.run_id)
            verified: list[int] = []
            real = agent_continuation_resume.verify_drift

            def counted(*args, **keywords):
                verified.append(1)
                return real(*args, **keywords)

            with patch.object(agent_continuation_resume, "verify_drift", counted):
                listing = resume_list(kept.project)

            self.assertEqual(1, len(verified))
            self.assertEqual(3, listing["unregistered_packets"])


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

    def test_ready_claim_exposes_only_content_free_reusable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            route = {
                "command": "task",
                "gates": ["source docs", "act", "verify"],
                "required_docs": ["guidance.md"],
            }
            with patch("test_agent_continuation_checkpoint.ROUTE", route):
                fixture = Fixture(directory)
            fixture.gate("source docs")
            fixture.checkpoint(
                "initial",
                work={
                    "objective": "saved prose must stay outside the reuse summary",
                    "decisions": [
                        {"id": "keep_boundary", "status": "accepted", "text": "private prose"},
                        {"id": "old_option", "status": "rejected", "text": "more private prose"},
                    ],
                    "inspected_scope": [
                        {"path": "src/module.py", "role": "inspected"},
                        {"path": "tests/module_test.py", "role": "inspected"},
                    ],
                    "verification": [
                        {
                            "id": "focused_unit",
                            "kind": "unit",
                            "result": "success",
                            "evidence_sha256": None,
                            "completed_at": None,
                        },
                        {
                            "id": "stale_lint",
                            "kind": "lint",
                            "result": "fail",
                            "evidence_sha256": None,
                            "completed_at": None,
                        },
                        {
                            "id": "manual_skip",
                            "kind": "manual",
                            "result": "skipped",
                            "evidence_sha256": None,
                            "completed_at": None,
                        },
                    ],
                },
            )
            age(fixture, minutes=0, owner_pid=dead_pid(), run_id=fixture.run_id)

            result = resume_last(fixture.project)

            self.assertEqual(
                {
                    "decision": "reuse_unchanged_evidence",
                    "required_docs": "reuse",
                    "inspected_scope_count": 2,
                    "accepted_decisions": [
                        {"id": "keep_boundary", "status": "accepted"}
                    ],
                    "successful_verification": [
                        {"id": "focused_unit", "kind": "unit"}
                    ],
                    "rerun_when": [
                        "state_changed",
                        "external_freshness_required",
                        "different_acceptance_boundary",
                    ],
                },
                result["reuse"],
            )
            rendered = json.dumps(result["reuse"])
            self.assertNotIn("saved prose", rendered)
            self.assertNotIn("private prose", rendered)
            self.assertNotIn("src/module.py", rendered)
            self.assertNotIn("old_option", rendered)
            self.assertNotIn("stale_lint", rendered)
            reuse_lines = "\n".join(
                line for line in _ready_lines(result) if line.startswith(("reuse ", "rerun "))
            )
            self.assertIn(
                "required_docs=reuse inspected_scope=2 decisions=keep_boundary",
                reuse_lines,
            )
            self.assertIn("verification=focused_unit(unit)", reuse_lines)
            self.assertNotIn("src/module.py", reuse_lines)
            self.assertNotIn("stale_lint", reuse_lines)

    def test_ready_claim_with_no_prior_analysis_still_has_a_reuse_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "continue without repeated analysis")

            result = resume_last(fixture.project)

            self.assertEqual(0, result["reuse"]["inspected_scope_count"])
            self.assertEqual("not_recorded", result["reuse"]["required_docs"])
            self.assertEqual([], result["reuse"]["accepted_decisions"])
            self.assertEqual([], result["reuse"]["successful_verification"])

    def test_a_post_mutation_checkpoint_invalidates_earlier_successes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            verification = [{
                "id": "before_edit",
                "kind": "unit",
                "result": "success",
                "evidence_sha256": None,
                "completed_at": None,
            }]
            fixture.checkpoint("initial", work={"objective": "edit after checking", "verification": verification})
            fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
            fixture.checkpoint("post_mutation")
            age(fixture, minutes=0, owner_pid=dead_pid(), run_id=fixture.run_id)

            result = resume_last(fixture.project)

            self.assertEqual("ready", result["result"])
            self.assertEqual([], result["work"]["verification"])
            self.assertEqual([], result["reuse"]["successful_verification"])


class NamedRunResumeTests(unittest.TestCase):
    """One checkout worked by several sessions at once.

    The newest slot is then whichever session wrote last, so a session coming
    back to its own work almost never finds it there. Refusing to substitute an
    older task is right, but on its own it left that session with no way to
    reach its own run at all. Naming the run says which packet is the
    candidate; it does not say the claim is allowed.
    """

    def test_naming_a_run_reaches_it_past_another_session_holding_the_newest_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "the task this session left behind")
            other = free_fixture(
                directory, "another session's task", project=mine.project, rules=mine.rules
            )
            age(other, minutes=1, owner_pid=os.getpid(), run_id=other.run_id)

            self.assertEqual("live_owner_refused", resume_last(mine.project)["result"])

            result = resume_last(mine.project, run_id=mine.run_id)

            self.assertEqual("ready", result["result"])
            self.assertEqual(mine.run_id, result["run_id"])
            self.assertEqual("the task this session left behind", result["work"]["objective"])
            self.assertEqual("scope", result["checkpoint"])
            self.assertEqual(process_owner(), run_state(mine, mine.run_id)["owner"])
            self.assertEqual(0, run_state(other, other.run_id).get("resume_generation", 0))

    def test_naming_another_session_s_live_run_is_refused_rather_than_granted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "the task this session left behind")
            other = free_fixture(
                directory, "another session's task", project=mine.project, rules=mine.rules
            )
            age(other, minutes=1, owner_pid=os.getpid(), run_id=other.run_id)

            result = resume_last(mine.project, run_id=other.run_id)

            self.assertEqual("live_owner_refused", result["result"])
            self.assertEqual(other.run_id, result["run_id"])
            self.assertIsNone(result["work"])
            self.assertIsNone(result["checkpoint"])
            self.assertIsNone(result["reuse"])
            self.assertEqual(0, run_state(other, other.run_id).get("resume_generation", 0))

    def test_naming_a_drifted_run_refuses_by_name_without_falling_through(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "the task this session left behind")
            free_fixture(
                directory, "another session's task", project=mine.project, rules=mine.rules
            )
            (mine.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            result = resume_last(mine.project, run_id=mine.run_id)

            self.assertEqual("drift_refused", result["result"])
            self.assertEqual(mine.run_id, result["run_id"])
            self.assertEqual(["project_worktree"], result["changed_signals"])
            self.assertIsNone(result["work"])

    def test_an_omitted_run_id_still_means_the_newest_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(
                directory, "the newer task", project=older.project, rules=older.rules
            )

            result = resume_last(older.project, run_id="")

            self.assertEqual("ready", result["result"])
            self.assertEqual(newer.run_id, result["run_id"])


class RefusesRatherThanSkipsTests(unittest.TestCase):
    """The property the whole command depends on.

    A caller asking for the last thing they were doing has the least context in
    which to notice they were handed a different, older task instead. Naming the
    blocker is the honest answer; substituting another run is not.
    """

    def test_boundary_and_claim_loss_refusals_expose_no_reusable_work(self) -> None:
        boundary_entry = {
            "status": "local_boundary_failed",
            "run_id": "opaque-run",
            "route_command": "task",
            "holder_state": "dead_proven",
            "changed_signals": [],
            "affected_paths": [],
        }
        with patch.object(
            agent_continuation_resume,
            "resume_list",
            return_value={"result": "ok", "entries": [boundary_entry]},
        ):
            boundary = resume_last(Path("/unused"))
        self.assertIsNone(boundary["work"])
        self.assertIsNone(boundary["checkpoint"])
        self.assertIsNone(boundary["reuse"])

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "claim race")
            refusal = {
                "result": "claim_lost",
                "resume_generation": 0,
                "holder_state": "dead_proven",
                "changed_signals": [],
                "affected_paths": [],
                "packet": None,
            }
            with patch.object(agent_continuation_resume, "claim_resume", return_value=refusal):
                lost = resume_last(fixture.project)
        self.assertIsNone(lost["work"])
        self.assertIsNone(lost["checkpoint"])
        self.assertIsNone(lost["reuse"])

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
            self.assertIsNone(result["reuse"])
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
            self.assertIsNone(result["work"])
            self.assertIsNone(result["checkpoint"])
            self.assertIsNone(result["reuse"])
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
            self.assertIsNone(result["reuse"])
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
            self.assertIsNone(result["reuse"])
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

    def test_a_named_run_that_is_not_unfinished_never_substitutes_the_newest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "the older task")
            newer = free_fixture(directory, "the newer task", project=older.project, rules=older.rules)

            result = resume_last(older.project, run_id="0" * 32)

            self.assertEqual("not_found", result["result"])
            self.assertEqual("run_id_not_unfinished", result["reason"])
            self.assertEqual("", result["run_id"])
            self.assertIsNone(result["work"])
            self.assertEqual(0, run_state(newer, newer.run_id).get("resume_generation", 0))
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
