"""Scratchpad helper scripts need no run in any governed project."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_claude_temp_checkout_scratch import _Fixture, _git
import claude_scratch_checkout as scratch


class ScratchHelperScripts(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        # `self.project` is the Tao-like checkout (TAO_HOME, linked-worktree
        # policy); `self.spill` is an ordinary governed project with no policy
        # file, whose default requires a workflow run before unverified commands.
        self.spill = self.base / "home" / "spill"
        self.spill.mkdir(parents=True)
        (self.spill / "AGENTS.md").write_text("Uses tao-hook.\n")
        _git("init", "-q", "-b", "main", cwd=self.spill)
        _git("add", ".", cwd=self.spill)
        _git("commit", "-q", "-m", "init", cwd=self.spill)
        self.pad = self.temp / "claude-501" / "session" / "scratchpad" / "probe_scripts"
        self.pad.mkdir(parents=True)
        for name, text in (("hello.py", "print(1)\n"), ("hello.sh", "echo hi\n"),
                           ("hello.mjs", "console.log(1)\n")):
            (self.pad / name).write_text(text)

    def _runs(self) -> list[str]:
        pad = self.pad
        return [
            f"python3 {pad}/hello.py",
            f"/usr/bin/python3 {pad}/hello.py",
            f"python3 -B {pad}/hello.py --flag value",
            f"zsh {pad}/hello.sh",
            f"sh {pad}/hello.sh",
            f"node {pad}/hello.mjs",
            f"python3 {pad}/hello.py > {pad}/out.txt",
            f"python3 {pad}/hello.py >> {pad}/out.txt",
            f"python3 {pad}/hello.py 2> {pad}/err.txt",
            f"python3 {pad}/hello.py > {pad}/out.txt 2>&1",
        ]

    def test_scratch_scripts_need_no_run_in_either_project(self) -> None:
        for cwd in (self.spill, self.project):
            for command in self._runs():
                with self.subTest(cwd=cwd.name, command=command):
                    self.assertEqual("allow", self._bash(command, cwd=cwd))

    def test_lines_that_visibly_reach_a_project_keep_their_verdict(self) -> None:
        inside = self.spill / "tool.py"
        inside.write_text("print(1)\n")
        fixture = self.temp / "fixture-repo"
        fixture.mkdir()
        _git("init", "-q", cwd=fixture)
        (fixture / "x.py").write_text("print(1)\n")
        pad = self.pad
        for command in (
            f"TAO_HOME={self.spill} python3 {pad}/hello.py",
            f"python3 {pad}/hello.py > {self.spill}/x",
            f"python3 {pad}/hello.py {self.spill}",
            f"python3 {inside}",
            "python3 tool.py",
            f"python3 {fixture}/x.py",
            f"python3 -c 'print(1)'",
            f"node -e 1 {pad}/hello.mjs",
            f"sh -c 'echo' {pad}/hello.sh",
            f"python3 {pad}/hello.py | tee {self.spill}/x",
        ):
            with self.subTest(command=command):
                self.assertEqual("deny", self._bash(command, cwd=self.spill))

    def test_predicate_needs_an_existing_scratch_file(self) -> None:
        def admitted(command: str) -> bool:
            return scratch.scratch_script_command(command, self.spill, self.spill, lambda p: None)

        self.assertTrue(admitted(f"python3 {self.pad}/hello.py"))
        self.assertFalse(admitted(f"python3 {self.pad}/missing.py"))
        self.assertFalse(admitted(f"python3 {self.pad}"))
        self.assertFalse(admitted(f"./python3 {self.pad}/hello.py"))
        self.assertFalse(admitted(f"ruby {self.pad}/hello.py"))
        self.assertFalse(admitted(f"python3 {self.pad}/hello.py && python3 {self.pad}/hello.py"))


if __name__ == "__main__":
    unittest.main()
