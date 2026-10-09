from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_runtime_session  # noqa: E402
from workflow_followup_hint import PAUSED, followup_hint  # noqa: E402

SESSION = "followup-hint-session"


class FollowupHintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.state = base / "state"
        self.project = base / "project"
        self.other = base / "other"
        for directory in (self.state / "claude-session-projects", self.project, self.other):
            directory.mkdir(parents=True)
        (self.state / "claude-session-projects" / SESSION).write_text(
            f"{self.project}\n{base / 'removed-worktree'}\n", encoding="utf-8"
        )
        environment = patch.dict(os.environ, {"TAO_STATE_HOME": str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.runs: dict[tuple[Path, str], Path] = {}

    def _evidence(self, root: Path, run_id: str) -> Path:
        path = root / ".tao" / "runs" / run_id / "preflight.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def _resolve(self, project, session=None, states=None, *, latest_of_several=False):
        key = "active" if states is None else "paused" if states == PAUSED else "completed"
        return self.runs.get((Path(project).resolve(), key))

    def _hint(self, cwd_root: Path | None = None) -> str:
        with patch.object(agent_runtime_session, "resolve_runtime_evidence", self._resolve):
            return followup_hint(SESSION, cwd_root)

    def test_a_finished_run_with_nothing_open_names_its_id(self) -> None:
        self.runs[(self.project.resolve(), "completed")] = self._evidence(self.project, "a" * 32)

        hint = self._hint()

        self.assertIn(f"--continue-from {'a' * 32}", hint)
        self.assertIn(str(self.project), hint)
        self.assertIn("read-only answer needs no start", hint)

    def test_an_open_or_paused_run_anywhere_silences_it(self) -> None:
        self.runs[(self.project.resolve(), "completed")] = self._evidence(self.project, "a" * 32)
        for state in ("active", "paused"):
            with self.subTest(state=state):
                self.runs[(self.other.resolve(), state)] = self.other / "x"
                self.assertEqual("", self._hint(cwd_root=self.other))
                del self.runs[(self.other.resolve(), state)]

    def test_the_latest_finish_across_projects_wins(self) -> None:
        old = self._evidence(self.project, "b" * 32)
        new = self._evidence(self.other, "c" * 32)
        os.utime(old, (1, 1))
        self.runs[(self.project.resolve(), "completed")] = old
        self.runs[(self.other.resolve(), "completed")] = new

        self.assertIn("c" * 32, self._hint(cwd_root=self.other))

    def test_no_session_index_or_no_finish_says_nothing(self) -> None:
        self.assertEqual("", self._hint())
        self.assertEqual("", followup_hint("", None))
        with patch.object(agent_runtime_session, "resolve_runtime_evidence", self._resolve):
            self.assertEqual("", followup_hint("unknown-session", None))


if __name__ == "__main__":
    unittest.main()
