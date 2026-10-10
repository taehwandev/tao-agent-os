"""Work cards through the real hook CLI: start opens, continuation keeps, closeout settles."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _tao_test_support import ROOT, fake_vibeguard_environment

import agent_work_cards as cards  # noqa: E402
from test_work_continuity_lifecycle_e2e import (  # noqa: E402
    PlainCheckout,
    detail,
    hook,
    run_id,
    start,
    turn_boundary,
)

# Work cards are the subject here, not audit findings.
_FAKE_VIBEGUARD = fake_vibeguard_environment()


def setUpModule() -> None:
    _FAKE_VIBEGUARD.start()


def tearDownModule() -> None:
    _FAKE_VIBEGUARD.stop()


def _agent_hook():
    spec = importlib.util.spec_from_file_location("agent_hook_for_cards", ROOT / "scripts" / "agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkCardLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # The hook subprocesses inherit this, so no card reaches the real ~/.tao.
        state_home = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(Path(temp.name) / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.checkout = PlainCheckout(temp.name)
        self.project = self.checkout.project

    def evidence(self, started) -> Path:
        return Path(detail(started, "evidence: ").split(": ", 1)[1])

    def test_start_opens_one_card_that_a_continued_run_keeps_and_finish_settles(self) -> None:
        # Another session's paused work: this session's own paused run would be
        # settled as superseded by the new request below.
        other = start(self.project, ROOT, "다른 작업부터 해줘", session="other-session")
        self.assertEqual(0, other.returncode, other.stdout)
        self.assertEqual(0, turn_boundary(self.project, session="other-session").returncode)
        first = start(self.project, ROOT, "src/module.py 의 가드를 고쳐줘")
        self.assertEqual(0, first.returncode, first.stdout)
        self.assertIn("Open work cards in this repository", first.stdout)
        self.assertIn(run_id(other), first.stdout)

        _agent_hook()._transition_finished_run(
            argparse.Namespace(evidence=self.evidence(first), project=self.project), True
        )
        follow = start(self.project, ROOT, "이어서 해줘", "--continue-from", run_id(first))
        self.assertEqual(0, follow.returncode, follow.stdout)

        by_work = {card["work_id"]: card["state"] for card in cards.list_cards(self.project, include_settled=True)}
        self.assertEqual({run_id(other): "active", run_id(first): "active"}, by_work,
                         "the continued run reopens the first run's card instead of adding one")
        _agent_hook()._transition_finished_run(
            argparse.Namespace(evidence=self.evidence(follow), project=self.project), True
        )
        self.assertEqual([run_id(other)], [card["work_id"] for card in cards.list_cards(self.project)])

    def test_a_no_change_cancel_settles_the_card_as_cancelled(self) -> None:
        started = start(self.project, ROOT, "아무 변경도 필요없었어")
        self.assertEqual(0, started.returncode, started.stdout)
        self.assertEqual(0, turn_boundary(self.project).returncode)
        [card] = cards.list_cards(self.project)
        self.assertEqual(("the sample module and its check", "active"), (card["summary"], card["state"]))

        settled = hook(self.project, ROOT, "cancel", "--no-change-evidence",
                       "the reported defect was a deliberate guard")

        self.assertEqual(0, settled.returncode, settled.stdout + settled.stderr)
        [card] = cards.list_cards(self.project, include_settled=True)
        self.assertEqual("cancelled", card["state"])

    def test_a_run_superseded_by_separate_completed_work_settles_as_done(self) -> None:
        worktree = self.project.parent / "slice"
        subprocess.run(["git", "-C", str(self.project), "worktree", "add", "-q", str(worktree),
                        "-b", "slice"], check=True)
        superseded = start(worktree, ROOT, "같은 작업을 메인에서 끝냈어")
        replacement = start(self.project, ROOT, "같은 작업을 메인에서 끝냈어")
        self.assertEqual(0, superseded.returncode, superseded.stdout)
        self.assertEqual(0, replacement.returncode, replacement.stdout)
        _agent_hook()._transition_finished_run(
            argparse.Namespace(evidence=self.evidence(replacement), project=self.project), True
        )

        settled = hook(worktree, ROOT, "cancel", "--evidence", str(self.evidence(superseded)),
                       "--replacement-evidence", str(self.evidence(replacement)))

        self.assertEqual(0, settled.returncode, settled.stdout + settled.stderr)
        self.assertEqual({run_id(superseded): "done", run_id(replacement): "done"},
                         {c["work_id"]: c["state"] for c in cards.list_cards(self.project, include_settled=True)})


class ProjectMemoryAtStartTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state_home = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(Path(temp.name) / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.project = PlainCheckout(temp.name).project

    def capture(self, body: str, source: str = "design note", *, source_paths: tuple[str, ...] = (),
                scope: str = "all") -> None:
        captured = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent_project_memory.py"),
             "--project", str(self.project), "capture", "--source", source, "--scope", scope,
             "--review-on", "2999-01-01",
             *(arg for path in source_paths for arg in ("--source-path", path))],
            input=body, capture_output=True, text=True,
        )
        self.assertEqual(0, captured.returncode, captured.stderr)

    def test_the_next_start_recalls_a_capture_without_approval(self) -> None:
        self.capture("Run the adapter contract check first.")

        started = start(self.project, ROOT, "가드를 고쳐줘")

        self.assertEqual(0, started.returncode, started.stdout)
        self.assertIn("Project memory (agent-written reference", started.stdout)
        self.assertIn("Run the adapter contract check first.", started.stdout)
        self.assertNotIn("Project memory upkeep", started.stdout)

    def test_start_names_upkeep_counts_without_record_content(self) -> None:
        self.capture("Prefer the queue for retries.")
        self.capture("Avoid the queue for retries.")

        started = start(self.project, ROOT, "가드를 고쳐줘")

        self.assertEqual(0, started.returncode, started.stdout)
        [notice] = [line for line in started.stdout.splitlines() if "Project memory upkeep" in line]
        self.assertIn("expired=0 expiring=0 duplicates=0 shared_source=1 unfinished=0", notice)
        self.assertIn("project-memory --project", notice)
        self.assertTrue(notice.rstrip().endswith("consolidate"), notice)
        self.assertNotIn("queue", notice)
        self.assertNotIn("design note", notice)

    def ranked_start(self, request: str, *extra: str, source_paths: tuple[str, ...] = ()) -> None:
        for number in range(4):
            self.capture(f"Unrelated billing advice {number}.", scope="bugfix")
        self.capture("Uniquequeue contract.", source="queue design", source_paths=source_paths)
        started = start(self.project, ROOT, request, *extra)
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        header = started.stdout.index("Project memory (agent-written reference")
        first_record = started.stdout[header:].splitlines()[1]
        self.assertIn("Uniquequeue contract.", first_record)

    def test_start_request_selects_relevant_memory_before_the_three_item_cutoff(self) -> None:
        self.ranked_start("Uniquequeue 가드를 고쳐줘")

    def test_start_target_summary_affects_memory_ranking(self) -> None:
        self.ranked_start("가드를 고쳐줘", "--target-summary", "Uniquequeue")

    def test_start_verified_surface_path_affects_memory_ranking(self) -> None:
        self.ranked_start("가드를 고쳐줘", "--target-summary", "bounded repair",
                          "--surface-path", "src/module.py",
                          source_paths=("src/module.py",))

    def test_start_shows_a_warning_when_source_worktree_bytes_changed(self) -> None:
        self.capture("Check the module contract.", source_paths=("src/module.py",))
        source = self.project / "src/module.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n# changed evidence\n", encoding="utf-8")
        started = start(self.project, ROOT, "가드를 고쳐줘")
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        self.assertIn('"source_status": "changed"', started.stdout)
        self.assertIn("Source evidence changed — verify before use", started.stdout)


class TestRunsNeverReachTheUsersStoreTests(unittest.TestCase):
    """A test that forgets TAO_STATE_HOME still cannot write the real ~/.tao.

    HOME stands in for the developer's home: with no state-home override, the
    stores would resolve to `<HOME>/.tao`, which is exactly where a forgotten
    override used to leave cards for throwaway checkouts.
    """

    def test_a_real_start_without_a_state_home_writes_no_card_or_memory(self) -> None:
        from support.global_state import STATE_HOME_ENV, UNDER_TEST_ENV

        if UNDER_TEST_ENV not in os.environ:
            self.skipTest("the marker is set by `python -m unittest`, the suite's runner")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name) / "home"
        home.mkdir()
        checkout = PlainCheckout(temp.name)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            os.environ.pop(STATE_HOME_ENV, None)
            started = start(checkout.project, ROOT, "가드를 고쳐줘")
            memory = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "agent_project_memory.py"),
                 "--project", str(checkout.project), "capture", "--source", "test",
                 "--review-on", "2999-01-01"],
                input="a reviewed rule", capture_output=True, text=True,
            )

        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        self.assertEqual(2, memory.returncode)
        self.assertIn(STATE_HOME_ENV, memory.stderr)
        self.assertFalse((home / ".tao" / cards.STORE_NAME).exists())
        self.assertFalse((home / ".tao" / "project-memory").exists())


if __name__ == "__main__":
    unittest.main()
