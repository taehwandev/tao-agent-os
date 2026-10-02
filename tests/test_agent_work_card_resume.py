"""Resume selects recorded task identity without renaming or guessing a session."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_work_card_resume as resume
import agent_work_cards as cards
import test_agent_work_cards as fixtures

WORK_A, WORK_B = fixtures.WORK_A, fixtures.WORK_B

SESSION = "01a0f571-0366-7863-ba96-0a9aa4ddf9fc"
OTHER_SESSION = "01a0f571-0366-7863-ba96-0a9aa4ddf9fd"


class WorkCardResumeTests(unittest.TestCase):
    setUp = fixtures.WorkCardTests.setUp
    _git = fixtures.WorkCardTests._git
    def test_selection_uses_displayed_snapshot_and_returns_native_exit_status(self) -> None:
        cards.open_card(self.project, WORK_A, summary="portfolio image", command="bugfix",
                        runtime="codex", session_id=SESSION)
        cards.settle_card(self.project, WORK_A, "done")
        cards.open_card(self.project, WORK_B, summary="top bar", command="feature",
                        runtime="codex", session_id=OTHER_SESSION)
        output = io.StringIO()
        with mock.patch("sys.stdout", output), mock.patch("builtins.input", return_value="2"), \
                mock.patch.object(resume, "_run") as launch:
            launch.return_value.returncode = 7
            self.assertEqual(7, cards._main(["--project", str(self.project), "resume"]))
        self.assertIn("1. top bar", output.getvalue())
        self.assertIn("2. portfolio image [done", output.getvalue())
        launch.assert_called_once_with(["codex", "resume", SESSION], cwd=self.project.resolve(), check=False)

    def test_cancel_invalid_and_eof_never_launch_a_session(self) -> None:
        cards.open_card(self.project, WORK_A, summary="work", command="task", runtime="codex", session_id=SESSION)
        with mock.patch("sys.stdout"), mock.patch.object(resume, "_run") as launch:
            for answer in ("0", "2", "-1", "latest", "١"):
                with mock.patch("builtins.input", return_value=answer), self.assertRaises(ValueError):
                    resume.resume_task(self.project)
            with mock.patch("builtins.input", return_value=""):
                self.assertEqual(0, resume.resume_task(self.project))
            for interrupt in (EOFError, KeyboardInterrupt):
                with mock.patch("builtins.input", side_effect=interrupt):
                    self.assertEqual(0, resume.resume_task(self.project))
            launch.assert_not_called()

    def test_removed_worktree_still_resumes_in_the_selected_repository(self) -> None:
        worktree = self.root / "linked"
        self._git("worktree", "add", "-q", str(worktree), "-b", "resume")
        cards.open_card(worktree, WORK_A, summary="work", command="task", runtime="codex", session_id=SESSION)
        self._git("worktree", "remove", str(worktree))
        with mock.patch("sys.stdout"), mock.patch("builtins.input", return_value="1"), \
                mock.patch.object(resume, "_run") as launch:
            resume.resume_task(self.project)
        launch.assert_called_once_with(["codex", "resume", SESSION], cwd=self.project, check=False)

    def test_legacy_binding_requires_evidence_for_that_exact_work(self) -> None:
        cards.open_card(self.project, WORK_A, summary="old", command="task")
        [card] = cards.list_cards(self.project)
        path = self.project / ".tao" / "runs" / WORK_A / "preflight.json"
        path.parent.mkdir(parents=True)
        for work, runtime, expected in ((WORK_B, "codex", ""), (WORK_A, "claude", ""),
                                         (WORK_A, "codex", SESSION)):
            path.write_text(json.dumps({"work": {"id": work},
                                        "runtime_session": {"runtime": runtime, "session_id": SESSION}}))
            self.assertEqual(expected, resume._session_id(card))
        for runtime, session in (("codex", "--last"), ("claude", SESSION), ("codex", "")):
            self.assertEqual("", resume._session_id({**card, "runtime": runtime, "session_id": session}))

    def test_empty_or_unbound_board_never_opens_a_picker_or_creates_state(self) -> None:
        with mock.patch("builtins.input") as question, self.assertRaises(ValueError):
            resume.resume_task(self.project)
        question.assert_not_called()
        self.assertFalse((self.root / "state-home").exists())
        cards.open_card(self.project, WORK_A, summary="unbound", command="task")
        with self.assertRaises(ValueError):
            resume.resume_task(self.project)

    def test_default_project_is_the_current_directory(self) -> None:
        with mock.patch.object(cards.Path, "cwd", return_value=self.project), \
                mock.patch.object(resume, "resume_task", return_value=0) as picker:
            self.assertEqual(0, cards._main(["resume"]))
        picker.assert_called_once_with(self.project.resolve())

    def test_real_cli_selects_the_recorded_session_without_changing_work_state(self) -> None:
        cards.open_card(self.project, WORK_A, summary="portfolio image", command="bugfix",
                        runtime="codex", session_id=SESSION)
        executable = self.root / "bin" / "codex"
        executable.parent.mkdir()
        executable.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                              "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}))\n")
        executable.chmod(0o700)
        environment = {**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"]}
        result = subprocess.run([sys.executable, str(Path(cards.__file__)), "resume"],
                                cwd=self.project, env=environment, input="1\n", text=True,
                                capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("1. portfolio image", result.stdout)
        self.assertIn(json.dumps({"args": ["resume", SESSION], "cwd": str(self.project.resolve())}),
                      result.stdout)
        self.assertEqual("active", cards.list_cards(self.project)[0]["state"])
