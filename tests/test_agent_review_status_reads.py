"""Keep whole-tree review status snapshots to one read per boundary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_hook import _review_working_tree, record_review_worktree_stability


class ReviewStatusReadsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.args = SimpleNamespace(project=ROOT, max_changed_paths=25, review_scope="working-tree")
        self.status = {"returncode": 0, "stdout": " M scripts/agent_review_hook.py\n"}
        self.paths = [" M scripts/agent_review_hook.py"]
        self.git_status = Mock(return_value=(self.status, self.paths))

    def test_whole_tree_review_reads_one_initial_snapshot(self) -> None:
        checks: dict = {}

        result = _review_working_tree(
            self.args, checks, Mock(), self.git_status, {"kind": "working-tree"}, []
        )

        self.git_status.assert_called_once_with(ROOT)
        self.assertEqual(self.paths, result["status_before_lines"])
        self.assertEqual(self.paths, result["full_status_before_lines"])

    def test_whole_tree_review_reads_one_final_snapshot(self) -> None:
        checks: dict = {}
        failures: list[str] = []

        record_review_worktree_stability(
            self.args, Mock(), self.git_status, [], self.paths, self.paths,
            checks, failures, review_subject={"kind": "working-tree"},
        )

        self.git_status.assert_called_once_with(ROOT)
        self.assertEqual([], failures)
        self.assertIs(checks["git_status_after"], checks["full_git_status_after"])


if __name__ == "__main__":
    unittest.main()
