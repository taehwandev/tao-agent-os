"""Tests running a named second project need that project's admission."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_claude_temp_checkout_scratch import _Fixture, _git
import claude_bash_readonly as readonly
import claude_pretool_finished_admission as finished
import claude_pretool_gate as gate


class NamedProjectTestRuns(_Fixture):
    def _kind(self, command: str, cwd: Path) -> str:
        payload = {"tool_input": {"command": command}}
        effective, tokens, simple = readonly.bash_invocation(payload, cwd)
        return readonly.bash_command_kind(tokens, simple, effective)

    def test_unittest_discovery_of_real_project_is_not_scratch(self) -> None:
        command = f"python3 -m unittest discover -s {self.project}"
        self.assertEqual("mutating", self._kind(command, self.bench))
        self.assertIn(self.project, gate._call_scope(
            {"tool_name": "Bash", "tool_input": {"command": command}},
            "Bash", self.bench,
        ).roots)
        self.assertEqual("deny", self._bash(command, cwd=self.bench))

    def test_a_compound_test_run_cannot_hide_its_target(self) -> None:
        for command in (
            f"echo $(python3 -m unittest discover -s {self.project})",
            f"python3 -m unittest discover -s {self.project} | tail -1",
            f"pytest {self.project} && echo done",
        ):
            with self.subTest(command=command):
                self.assertEqual("deny", self._bash(command, cwd=self.bench))

    def test_pytest_and_option_paths_into_real_project_are_governed(self) -> None:
        (self.bench / "real").symlink_to(self.project, target_is_directory=True)
        for command in (
            f"pytest {self.project}",
            f"python3 -m pytest --rootdir={self.project}",
            f"pytest --override-ini=cache_dir={self.project}",
            f"pytest -c {self.project / 'pytest.ini'}",
            f"pytest {self.project / 'test_x.py'}::TestX",
            "python3 -m unittest discover -s real",
            f"python3 -m unittest discover -s {self.bench / 'real'}",
            f"python3 -m unittest discover -s {os.path.relpath(self.project, self.bench)}",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command, self.bench))
                self.assertEqual("deny", self._bash(command, cwd=self.bench))

    def test_own_and_temp_test_targets_stay_run_free(self) -> None:
        for command in (
            "python3 -m unittest discover -s docs",
            "python3 -m unittest tests.test_x",
            "pytest docs -q",
            "python3 -m pytest docs",
            "pytest",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command, self.bench))
                self.assertEqual("allow", self._bash(command, cwd=self.bench))
        self.assertEqual("read_only", self._kind(
            "python3 -m unittest discover -s .", self.project,
        ))

    def test_a_named_projects_existing_run_admits_its_tests(self) -> None:
        from test_claude_pretool_gate import _write_preflight

        other = self.base / "home" / "other"
        other.mkdir(parents=True)
        (other / "AGENTS.md").write_text("Uses tao-hook.\n")
        (other / ".gitignore").write_text(".tao/\n")
        _git("init", "-q", "-b", "work", cwd=other)
        _git("add", ".", cwd=other)
        _git("commit", "-q", "-m", "init", cwd=other)
        command = f"python3 -m unittest discover -s {other}"
        self.assertEqual("deny", self._bash(command, cwd=self.bench))
        _write_preflight(other, "temp-checkout-scratch")
        _write_preflight(self.bench, "temp-checkout-scratch")
        self.assertEqual("allow", self._bash(command, cwd=self.bench))

    def test_finish_does_not_admit_a_chained_external_test_run(self) -> None:
        def published(_root, _session, segment, _runs, _cwd):
            return segment[:2] == ["git", "push"]

        with patch.object(finished, "publishes_finished_work", side_effect=published):
            self.assertFalse(finished.publishes_finished_command(
                self.bench, "temp-checkout-scratch",
                f"git push && python3 -m unittest discover -s {self.project}",
                self.bench, None,
            ))
            self.assertTrue(finished.publishes_finished_command(
                self.bench, "temp-checkout-scratch",
                "git push && python3 -m unittest discover -s docs",
                self.bench, None,
            ))


if __name__ == "__main__":
    unittest.main()
