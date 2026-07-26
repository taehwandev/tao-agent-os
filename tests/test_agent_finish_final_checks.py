from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_final_checks import run_final_checks


class AgentFinishFinalChecksTests(unittest.TestCase):
    def test_read_only_non_git_workspace_skips_unavailable_diff_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            failures: list[str] = []
            with patch(
                "agent_finish_final_checks.run_workflow_validate",
                return_value={"returncode": 0, "stdout": "", "stderr": ""},
            ), patch(
                "agent_finish_final_checks.run_command",
                side_effect=AssertionError("read-only non-git work must not run git diff"),
            ):
                _, diff_check, _, _ = run_final_checks(
                    ROOT,
                    Path(temporary_directory),
                    ROOT,
                    None,
                    [],
                    failures,
                    read_only=True,
                )

        self.assertTrue(diff_check["skipped"])
        self.assertIn("not inside a Git repository", diff_check["review_note"])
        self.assertEqual([], failures)

    def test_writing_non_git_workspace_keeps_diff_check_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            failures: list[str] = []
            with patch(
                "agent_finish_final_checks.run_workflow_validate",
                return_value={"returncode": 0, "stdout": "", "stderr": ""},
            ), patch(
                "agent_finish_final_checks.run_command",
                return_value={
                    "returncode": 129,
                    "stdout": "",
                    "stderr": "not a git repository",
                },
            ), patch(
                "agent_finish_final_checks.cached_vibeguard",
                return_value={"returncode": 0, "overall": {"status": "Ready"}},
            ):
                _, diff_check, _, _ = run_final_checks(
                    ROOT,
                    Path(temporary_directory),
                    ROOT,
                    None,
                    [],
                    failures,
                )

        self.assertEqual(129, diff_check["returncode"])
        self.assertEqual(["git diff --check failed"], failures)


if __name__ == "__main__":
    unittest.main()
