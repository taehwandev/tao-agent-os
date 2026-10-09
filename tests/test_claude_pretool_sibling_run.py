from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claude_pretool_sibling_run import (  # noqa: E402
    linked_worktrees,
    sibling_open_run,
    sibling_run_sentence,
)

SESSION = "sibling-session"


class SiblingOpenRunTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.main = base / "repo"
        self.task = base / "repo" / ".tao" / "worktrees" / "task"
        self.other_repo = base / "other"
        for directory in (self.main / ".git" / "worktrees" / "task", self.task, self.other_repo):
            directory.mkdir(parents=True, exist_ok=True)
        (self.main / ".git" / "worktrees" / "task" / "gitdir").write_text(
            f"{self.task}/.git\n", encoding="utf-8"
        )
        self.open: set[Path] = set()

    def _main_of(self, path: Path) -> Path | None:
        if path in {self.main, self.task}:
            return self.main
        return path

    def _evidence(self, path: Path, session_id: str) -> Path | None:
        return path / "preflight.json" if path in self.open and session_id == SESSION else None

    def _find(self, root: Path, recorded: list[Path] | None = None) -> Path | None:
        return sibling_open_run(
            root, SESSION, recorded or [],
            main_checkout_for=self._main_of, session_evidence=self._evidence,
        )

    def test_linked_worktrees_are_read_from_the_admin_directory(self) -> None:
        self.assertEqual([self.task], linked_worktrees(self.main))
        self.assertEqual([], linked_worktrees(self.other_repo))

    def test_an_edit_in_main_names_the_worktree_run(self) -> None:
        self.open.add(self.task)
        self.assertEqual(self.task, self._find(self.main))

    def test_an_edit_in_the_worktree_names_the_main_run(self) -> None:
        self.open.add(self.main)
        self.assertEqual(self.main, self._find(self.task))

    def test_runs_in_another_repository_or_the_same_root_are_not_siblings(self) -> None:
        self.open.update({self.other_repo, self.main})
        self.assertIsNone(self._find(self.main, recorded=[self.other_repo]))

    def test_no_session_or_no_open_run_says_nothing(self) -> None:
        self.assertIsNone(self._find(self.main))
        self.open.add(self.task)
        self.assertIsNone(
            sibling_open_run(
                self.main, "", [],
                main_checkout_for=self._main_of, session_evidence=self._evidence,
            )
        )

    def test_the_sentence_names_both_checkouts(self) -> None:
        sentence = sibling_run_sentence(self.main, self.task)
        self.assertIn(str(self.task), sentence)
        self.assertIn(str(self.main), sentence)
        self.assertIn("rather than starting a second run here", sentence)


if __name__ == "__main__":
    unittest.main()
