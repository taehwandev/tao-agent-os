from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_structure import changed_source_paths
from agent_workspace_policy import (
    is_git_status_review_only,
    is_non_git_workspace,
    is_writing_workspace,
)


def load_collect_failures():
    spec = importlib.util.spec_from_file_location("agent_preflight_script", ROOT / "scripts" / "agent-preflight.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("agent-preflight.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.collect_failures


class AgentWorkspacePolicyTests(unittest.TestCase):
    def test_writing_workspace_is_detected_from_local_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "drafts").mkdir()
            (project / "AGENTS.md").write_text(
                "# Writing Workspace Instructions\n"
                "Use this folder as the primary workspace for blog posts.\n",
                encoding="utf-8",
            )

            self.assertTrue(is_writing_workspace(project))

    def test_preflight_allows_review_only_git_status_for_writing_workspace(self) -> None:
        collect_failures = load_collect_failures()
        failures = collect_failures(
            {"returncode": 0},
            {"missing": []},
            "",
            {"returncode": 128, "review_only": True},
            {"returncode": 0},
            [],
        )

        self.assertEqual([], failures)

    def test_structure_review_skips_git_discovery_for_non_git_writing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "drafts").mkdir()
            (project / "AGENTS.md").write_text(
                "---\nkeyflow_id: local_writing_workspace\n---\n"
                "# Writing Workspace Instructions\n",
                encoding="utf-8",
            )

            def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 128,
                    "stdout": "",
                    "stderr": "fatal: not a git repository",
                }

            discovery, paths = changed_source_paths(project, run_command)

            self.assertEqual([], paths)
            self.assertEqual([], discovery["command_errors"])
            self.assertEqual("non_git_workspace", discovery["review_only"])


    def test_workspace_root_holding_repos_is_not_itself_a_git_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            (workspace_root / "some-repo" / ".git").mkdir(parents=True)

            self.assertTrue(is_non_git_workspace(workspace_root))
            self.assertFalse(is_non_git_workspace(workspace_root / "some-repo"))

    def test_git_status_failure_is_review_only_outside_any_repository(self) -> None:
        # A path with no repository above it cannot produce git evidence, so the
        # gate must not demand it. This is what made the gate unsatisfiable for
        # $HOME and for the ~/git workspace root.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)

            self.assertTrue(is_git_status_review_only(project, {"returncode": 128}))

    def test_git_status_failure_inside_a_repository_stays_a_real_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".git").mkdir()

            self.assertFalse(is_git_status_review_only(project, {"returncode": 128}))

    def test_successful_git_status_is_never_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(is_git_status_review_only(Path(temp_dir), {"returncode": 0}))


if __name__ == "__main__":
    unittest.main()
