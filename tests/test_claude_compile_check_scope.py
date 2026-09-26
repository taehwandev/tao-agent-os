"""`python -m compileall|py_compile` is read-only only inside its own project.

Observed: from a throwaway temp worktree, `python3 -m compileall
<real project>/scripts` ran with no workflow and wrote `__pycache__/*.pyc` into
the real project. Both modules write bytecode beside every source they compile,
so the line is read-only only while every path it names resolves into the
project the command runs in, or into the OS temp directory. Anything else is
`mutating`, and the target project's ordinary rules decide.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_bash_readonly as bash_readonly
from test_claude_temp_checkout_scratch import _Fixture, _git


class _Projects(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        (self.project / "scripts").mkdir()
        (self.project / "scripts" / "x.py").write_text("x = 1\n")
        (self.project / "sub").mkdir()
        (self.project / "sub" / "AGENTS.md").write_text("nested guidance\n")
        (self.project / "sub" / "y.py").write_text("y = 1\n")
        self.other = self.base / "home" / "other"
        self.other.mkdir(parents=True)
        (self.other / "AGENTS.md").write_text("Uses tao-hook.\n")
        (self.other / "z.py").write_text("z = 1\n")
        _git("init", "-q", "-b", "main", cwd=self.other)
        self.scratch = self.temp / "loose"
        self.scratch.mkdir()
        (self.scratch / "t.py").write_text("t = 1\n")

    def _kind(self, command: str, cwd: Path) -> str:
        payload = {"tool_input": {"command": command}}
        effective, tokens, simple = bash_readonly.bash_invocation(payload, cwd)
        return bash_readonly.bash_command_kind(tokens, simple, effective)


class OwnProjectAndTempStayReadOnlyTests(_Projects):
    def test_compiling_the_project_you_are_in_is_read_only(self) -> None:
        for command in (
            "python3 -m compileall scripts",
            "python3 -m compileall -q scripts",
            "python3 -m compileall -qf -j0 scripts sub",
            f"python3 -m compileall {self.project / 'scripts'}",
            "python3 -m py_compile scripts/x.py",
            "python3 -m py_compile -q scripts/x.py sub/y.py",
            f"python3 -m compileall -d {self.project} scripts",
            "python3 -m compileall -q scripts | tail -3",
            "python3 -W ignore -m py_compile scripts/x.py",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command, self.project))
        self.assertEqual(
            "read_only", self._kind("python3 -m compileall ../scripts", self.project / "sub")
        )

    def test_temp_targets_are_read_only(self) -> None:
        for command in (
            f"python3 -m compileall {self.scratch}",
            f"python3 -m py_compile {self.scratch / 't.py'}",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command, self.project))
                self.assertEqual("read_only", self._kind(command, self.other))

    def test_no_operand_keeps_its_verdict(self) -> None:
        """compileall then compiles sys.path, which names no project."""

        self.assertEqual("read_only", self._kind("python3 -m compileall", self.project))
        self.assertEqual("read_only", self._kind("python3 -m compileall -q", self.project))

    def test_test_runners_are_unchanged(self) -> None:
        for command in (
            f"python3 -m unittest discover -s {self.other}",
            f"python3 -m pytest {self.other}",
            "python3 -m unittest",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command, self.project))


class AnotherProjectIsMutatingTests(_Projects):
    def test_an_operand_in_another_project_is_mutating(self) -> None:
        for command in (
            f"python3 -m compileall {self.other}",
            f"python3 -m py_compile {self.other / 'z.py'}",
            f"python3 -m compileall scripts {self.other}",
            f"python3 -m compileall -d {self.other} scripts",
            f"python3 -m compileall -s{self.other} scripts",
            f"python3 -m compileall -- {self.other}",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command, self.project))

    def test_a_dotdot_escape_into_another_project_is_mutating(self) -> None:
        self.assertEqual("mutating", self._kind("python3 -m compileall ../other", self.project))
        self.assertEqual(
            "mutating", self._kind("python3 -m py_compile scripts/../../other/z.py", self.project)
        )

    def test_a_symlink_into_another_project_is_mutating(self) -> None:
        (self.project / "link").symlink_to(self.other, target_is_directory=True)
        (self.scratch / "link").symlink_to(self.other, target_is_directory=True)
        for command in (
            "python3 -m compileall link",
            "python3 -m py_compile link/z.py",
            f"python3 -m compileall {self.scratch / 'link'}",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command, self.project))

    def test_what_the_line_does_not_show_is_mutating(self) -> None:
        for command in (
            "python3 -m py_compile -",
            "python3 -m compileall -i list.txt",
            "python3 -m compileall -i -",
            "python3 -m compileall --unknown scripts",
            "python3 -m compileall $TARGET",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command, self.project))

    def test_a_relative_operand_with_no_known_cwd_is_mutating(self) -> None:
        payload = {"tool_input": {"command": "python3 -m compileall scripts"}}
        _, tokens, simple = bash_readonly.bash_invocation(payload, self.project)
        self.assertEqual("mutating", bash_readonly.bash_command_kind(tokens, simple, None))

    def test_a_nested_git_repository_is_another_project(self) -> None:
        nested = self.project / "vendor"
        nested.mkdir()
        _git("init", "-q", cwd=nested)
        self.assertEqual("mutating", self._kind("python3 -m compileall vendor", self.project))


class ObservedReproductionTests(_Projects):
    def test_compiling_the_real_project_from_a_temp_worktree_needs_its_run(self) -> None:
        """The Codex reproduction, through the real `decide()`."""

        command = f"python3 -m compileall {self.project / 'scripts'}"
        self.assertEqual("mutating", self._kind(command, self.bench))
        self.assertEqual("deny", self._bash(command, cwd=self.bench))

    def test_compiling_the_temp_worktree_itself_needs_no_run(self) -> None:
        (self.bench / "w.py").write_text("w = 1\n")
        for command in ("python3 -m compileall .", "python3 -m py_compile w.py"):
            with self.subTest(command=command):
                self.assertEqual("allow", self._bash(command, cwd=self.bench))


if __name__ == "__main__":
    unittest.main()
