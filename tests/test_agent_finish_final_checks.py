from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_final_checks import reusable_review_workflow_validation, run_final_checks


class AgentFinishFinalChecksTests(unittest.TestCase):
    def test_reusable_review_path_escape_is_rejected_without_raising(self) -> None:
        digest = "0" * 64
        state = {
            "head": "head",
            "worktree_fingerprint": digest,
            "worktree_signature": digest,
        }
        record = {
            "schema_version": 3,
            "preflight_evidence": {
                "path": "../outside.json",
                "sha256": digest,
            },
            "project_git": state,
            "rules_git": state,
            "workflow_validate": {"returncode": 0},
            "diff_check": {
                "returncode": 0,
                "review_scope": "working-tree",
            },
        }

        with patch(
            "agent_finish_final_checks.read_json_object",
            return_value=record,
        ):
            result = reusable_review_workflow_validation(ROOT, ROOT)

        self.assertIsNone(result)

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

    def test_intrinsically_read_only_git_workspace_skips_preexisting_diff_check(self) -> None:
        failures: list[str] = []
        with patch(
            "agent_finish_final_checks.run_workflow_validate",
            return_value={"returncode": 0, "stdout": "", "stderr": ""},
        ), patch(
            "agent_finish_final_checks.is_writing_workspace",
            return_value=False,
        ), patch(
            "agent_finish_final_checks.is_non_git_workspace",
            return_value=False,
        ), patch(
            "agent_finish_final_checks.run_command",
            side_effect=AssertionError("intrinsically read-only analysis must not run git diff"),
        ):
            _, diff_check, _, _ = run_final_checks(
                ROOT,
                ROOT,
                ROOT,
                None,
                [],
                failures,
                read_only=True,
                intrinsically_read_only=True,
            )

        self.assertTrue(diff_check["skipped"])
        self.assertIn("intrinsically read-only analysis", diff_check["review_note"])
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
