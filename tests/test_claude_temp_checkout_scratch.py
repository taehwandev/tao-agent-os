"""Throwaway checkouts under the OS temp directory, as the Claude gate reads them.

Observed: a measurement worktree made with `git worktree add --detach
<scratchpad>/bench` was governed like the project it came from. Deleting a
probe file in it and `git worktree remove --force <bench>` from the parent
were both refused until a full cleanup lifecycle was opened in the throwaway
checkout. Its files are scratch; publishing from it, and writing the parent
repository's refs, are not.

The OS temp directory is patched to `<base>/tmp`, so `<base>/home` plays a
project outside it. Every call goes through the real `decide()`.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import claude_bash_syntax as syntax
import claude_pretool_gate as pretool
from claude_scratch_checkout import scratch_command

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.temp = self.base / "tmp"
        self.temp.mkdir()
        self.project = self.base / "home" / "proj"
        self._governed_repository(self.project)
        self.bench = self.temp / "claude-501" / "session" / "scratchpad" / "bench"
        self.bench.parent.mkdir(parents=True)
        _git("worktree", "add", "--detach", str(self.bench), cwd=self.project)
        (self.bench / "docs").mkdir()
        (self.bench / "docs" / "probe.txt").write_text("x\n")
        roots = patch.object(syntax, "scratch_roots", lambda: [self.temp])
        roots.start()
        self.addCleanup(roots.stop)
        environment = patch.dict(
            os.environ,
            {
                "TAO_HOME": str(self.project),
                "TAO_STATE_HOME": str(self.base / "state"),
                "CLAUDE_PROJECT_DIR": str(self.project),
                "PATH": os.environ.get("PATH", ""),
            },
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)

    @staticmethod
    def _governed_repository(root: Path) -> None:
        root.mkdir(parents=True)
        (root / "AGENTS.md").write_text("Uses tao-hook.\n")
        (root / "notes.txt").write_text("n\n")
        (root / ".gitignore").write_text(".tao/\n")
        shared = root / ".agents" / "shared"
        shared.mkdir(parents=True)
        (shared / "worktree-policy.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "require_linked_worktree": True,
                    "protected_branches": ["main"],
                    "require_workflow_entry": True,
                }
            )
        )
        _git("init", "-q", "-b", "main", cwd=root)
        _git("add", ".", cwd=root)
        _git("commit", "-q", "-m", "init", cwd=root)

    def _decision(self, payload: dict) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            pretool.decide({"session_id": "temp-checkout-scratch", **payload})
        printed = output.getvalue().strip()
        if not printed:
            return "allow"
        return json.loads(printed)["hookSpecificOutput"]["permissionDecision"]

    def _bash(self, command: str, cwd: Path | None = None) -> str:
        return self._decision(
            {
                "tool_name": "Bash",
                "cwd": str(cwd or self.project),
                "tool_input": {"command": command},
            }
        )

    def _edit(self, target: Path, cwd: Path | None = None) -> str:
        return self._decision(
            {
                "tool_name": "Write",
                "cwd": str(cwd or self.project),
                "tool_input": {"file_path": str(target), "content": "y\n"},
            }
        )


class ThrowawayFilesAreScratchTests(_Fixture):
    def test_editing_a_file_in_the_temp_worktree_needs_no_run(self) -> None:
        self.assertEqual(self._edit(self.bench / "docs" / "probe.txt"), "allow")
        self.assertEqual(self._edit(self.bench / "new.txt", cwd=self.bench), "allow")

    def test_removing_a_file_in_the_temp_worktree_needs_no_run(self) -> None:
        """Observed: `rm <bench>/docs/git-count-probe.txt` was refused."""

        probe = self.bench / "docs" / "probe.txt"
        self.assertEqual(self._bash(f"rm {probe}"), "allow")
        self.assertEqual(self._bash("rm docs/probe.txt", cwd=self.bench), "allow")
        self.assertEqual(self._bash(f"echo x > {probe}"), "allow")

    def test_a_temp_clone_of_a_project_kept_elsewhere_is_scratch(self) -> None:
        clone = self.temp / "clone"
        subprocess.run(
            [*GIT, "clone", "-q", str(self.project), str(clone)],
            check=True,
            capture_output=True,
        )
        self.assertEqual(self._edit(clone / "notes.txt"), "allow")
        self.assertEqual(self._bash(f"mv {clone / 'notes.txt'} {clone / 'n2.txt'}"), "allow")
        # A push from the clone's own main checkout keeps the clone governed;
        # what that checkout's policy then answers is unchanged here.
        push = {"tool_name": "Bash", "cwd": str(clone),
                "tool_input": {"command": "git push origin HEAD:main"}}
        self.assertIn(clone, pretool._call_scope(push, "Bash", clone).roots)

    def test_removing_the_temp_worktree_from_its_parent_needs_no_run(self) -> None:
        """Observed: `git -C <parent> worktree remove --force <bench>` was refused."""

        for command in (
            f"git -C {self.project} worktree remove --force {self.bench}",
            f"git -C {self.project} worktree remove {self.bench}",
            f"git -C {self.project} worktree prune",
        ):
            with self.subTest(command=command):
                self.assertNotEqual(self._bash(command), "deny")


class PublicationStaysGovernedTests(_Fixture):
    def test_commit_and_push_from_the_temp_worktree_stay_governed(self) -> None:
        for command in (
            f"git -C {self.bench} commit -m probe",
            f"git -C {self.bench} push origin HEAD:main",
            f"git -C {self.bench} tag v1",
            f"git -C {self.bench} branch -D main",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "deny")

    def test_a_file_write_chained_to_a_commit_stays_governed(self) -> None:
        probe = self.bench / "docs" / "probe.txt"
        self.assertEqual(
            self._bash(f"rm {probe} && git -C {self.bench} commit -am probe", cwd=self.bench),
            "deny",
        )


class OpaqueCodeInTheTempCheckoutTests(_Fixture):
    """A disposable checkout does not confine programs that run from it."""

    def test_program_execution_uses_the_ordinary_workflow(self) -> None:
        (self.bench / "script.py").write_text("print(1)\n")
        (self.bench / "tool").write_text("#!/bin/sh\n")
        (self.bench / "build").mkdir()
        (self.bench / "a").write_text("a\n")
        for command in (
            "python3 script.py",
            "python3 -m unittest discover -s tests",
            "npm test",
            "npm run build",
            "npx tsc --noEmit",
            "make",
            "make -C build",
            "./tool",
            f"{self.bench / 'tool'}",
            "node x.js",
            "FOO=1 npm test",
            "env FOO=1 python3 script.py",
            "bash ./tool",
            "python3 script.py > out.log 2>&1",
            "npm test && python3 script.py",
            f"cd {self.bench} && make",
            "python3 -c \"import os; print(os.environ['TAO_HOME'])\"",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "deny")

    def test_hidden_original_and_shared_git_writes_are_not_scratch(self) -> None:
        (self.bench / "script.py").write_text(
            "import os, subprocess\n"
            "open(os.path.join(os.environ['TAO_HOME'], 'notes.txt'), 'w').write('changed')\n"
            "subprocess.run(['git', 'tag', 'unexpected'], check=True)\n"
        )
        for command in ("python3 script.py", "python3 -m unittest discover -s tests"):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "deny")
        self.assertEqual((self.project / "notes.txt").read_text(), "n\n")

    def test_bounded_scratch_work_and_git_status_need_no_run(self) -> None:
        (self.bench / "build").mkdir()
        (self.bench / "a").write_text("a\n")
        for command in (
            "rm -rf build", "cp a b", "rm docs/probe.txt",
            "echo x > out.log", "cat a > copied.log", "git status",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "allow")

    def test_parent_removal_and_directory_change_fallback_keep_admission(self) -> None:
        (self.bench / "escape").symlink_to(self.project, target_is_directory=True)
        for command in (
            "rm -rf ..", "rmdir -p docs", "rm -rf escape/",
            "rm {docs,../../home/proj}/probe.txt",
            "PATH=/tmp/fake rm docs/probe.txt",
            "env LD_PRELOAD=/tmp/fake rm docs/probe.txt",
            f"./git worktree remove {self.bench}",
            f"PATH=/tmp/fake git worktree remove {self.bench}",
            "cd missing; echo changed > notes.txt",
            "cd missing || echo changed > notes.txt",
            "cd docs | echo changed > notes.txt",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "deny")
        self.assertEqual(
            self._bash("cd docs && echo changed > probe.txt", cwd=self.bench),
            "allow",
        )

    def test_file_writes_inside_temp_need_no_run(self) -> None:
        probe = self.bench / "docs" / "probe.txt"
        other = self.temp / "elsewhere"
        for command in (
            f"rm {self.bench / 'x'}",
            f"rm -rf {self.bench / 'docs'}",
            f"cp {probe} {other}",
            f"mkdir -p {self.bench / 'out'} && touch {self.bench / 'out' / 'a'}",
            f"chmod 644 {probe}",
            f"cat {probe} > {other}",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._bash(command, cwd=self.bench), "allow")
        self.assertNotEqual(
            self._bash(f"git -C {self.project} worktree remove --force {self.bench}"),
            "deny",
        )


class CommandsNamingARealProjectKeepTheirVerdictTests(_Fixture):
    """Observed: `TAO_HOME=<project> python3 ...` run in the temp worktree
    rewrote a file of the original project, and the gate allowed it.

    A line that visibly reaches a real project -- a word, an option value, an
    assignment value or a redirect resolving into it, or into the repository
    the checkout shares -- is not scratch. The exemption then simply does not
    apply: the verdict is exactly the one the gate gives with the exemption
    disabled, never an extra denial, and a run in that project admits it.
    """

    def _governed_verdict(self, command: str, cwd: Path) -> str:
        with patch.object(pretool, "throwaway_checkout", lambda root: False):
            return self._bash(command, cwd=cwd)

    def _assert_unexempted(self, command: str, cwd: "Path | None" = None) -> None:
        cwd = cwd or self.bench
        with self.subTest(command=command):
            self.assertFalse(
                scratch_command(command, self.bench, cwd, pretool.find_project_root)
            )
            self.assertEqual(
                self._bash(command, cwd=cwd), self._governed_verdict(command, cwd)
            )

    def _real_project_commands(self) -> "list[str]":
        real = self.project / "notes.txt"
        inside = self.bench / "docs" / "probe.txt"
        escape = "../" * 5 + "home/proj"
        common = self.project / ".git"
        return [
            f"TAO_HOME={self.project} python3 x.py",
            f"TAO_STATE_HOME={self.project}/.tao python3 x.py",
            f"PWD={self.project} npm test",
            f"env GIT_DIR={common} python3 x.py",
            f"export TAO_HOME={self.project} && python3 x.py",
            f"python3 tool.py --project {self.project}",
            f"python3 tool.py --output={real}",
            f"python3 tool.py -o{real}",
            f"make -C {self.project}",
            f"python3 tool.py {escape}",
            f"python3 -c \"open('{real}','w').write('x')\"",
            f"cd {self.project} && make",
            f"cp a {real}",
            f"cp {inside} {real}",
            f"mv {real} {inside}",
            f"ln -s {inside} {real}",
            f"touch {real}",
            f"find {self.project} -delete",
            f"echo x | tee {real}",
            f"echo x > {real}",
            f"npm test > {real}",
        ]

    def test_a_command_naming_a_real_project_is_not_scratch(self) -> None:
        for command in self._real_project_commands():
            self._assert_unexempted(command)

    def test_a_home_rooted_path_into_a_real_project_is_not_scratch(self) -> None:
        home = self.base / "home"
        with patch.dict(os.environ, {"HOME": str(home)}):
            for command in (
                "python3 x.py --project ~/proj",
                "TAO_HOME=$HOME/proj python3 x.py",
                "python3 x.py ${HOME}/proj/notes.txt",
            ):
                self._assert_unexempted(command)
            self.assertEqual(self._bash("cat ~/elsewhere", cwd=self.bench), "allow")

    def test_a_temp_symlink_into_a_real_project_is_not_scratch(self) -> None:
        (self.bench / "real").symlink_to(self.project, target_is_directory=True)
        self._assert_unexempted("python3 x.py real/notes.txt")
        self._assert_unexempted("python3 x.py --out=real")

    def test_the_observed_tao_home_write_stays_denied(self) -> None:
        command = (
            f"TAO_HOME={self.project} python3 -c \"import os; "
            "open(os.environ['TAO_HOME'] + '/notes.txt', 'w')\""
        )
        self._assert_unexempted(command)
        self.assertEqual(self._bash(command, cwd=self.bench), "deny")

    def test_open_runs_admit_it_as_they_would_without_the_exemption(self) -> None:
        """Not being scratch adds no denial: the gate's ordinary rules decide.

        `other` is a governed project on an unprotected branch, so a workflow
        start is all that stands between these commands and running. At every
        step -- no run, a run in the named project, a run where the command
        runs too -- the verdict is the one the exemption-free gate gives, and
        once those runs are open the commands run.
        """

        from test_claude_pretool_gate import _write_preflight

        other = self.base / "home" / "other"
        other.mkdir(parents=True)
        (other / "AGENTS.md").write_text("Uses tao-hook.\n")
        (other / ".gitignore").write_text(".tao/\n")
        _git("init", "-q", "-b", "work", cwd=other)
        _git("add", ".", cwd=other)
        _git("commit", "-q", "-m", "init", cwd=other)
        commands = [
            f"TAO_HOME={other} python3 x.py",
            f"python3 tool.py --project {other}",
            f"cp a {other / 'b'}",
        ]
        for command in commands:
            self._assert_unexempted(command)
            self.assertEqual(self._bash(command, cwd=self.bench), "deny")
        _write_preflight(other, "temp-checkout-scratch")
        for command in commands:
            self._assert_unexempted(command)
        _write_preflight(self.bench, "temp-checkout-scratch")
        for command in commands:
            self._assert_unexempted(command)
            self.assertEqual(self._bash(command, cwd=self.bench), "allow")

    def test_unreadable_lines_and_publication_stay_governed(self) -> None:
        for command in (
            f"git -C {self.bench} commit -m probe",
            "gh pr create --fill",
            'eval "$x"',
            'bash -c "$x"',
            "$TOOL build",
            "python3 x.py $TARGET",
        ):
            self._assert_unexempted(command)


class OnlyRealTempIsScratchTests(_Fixture):
    def test_a_temp_path_that_links_into_a_project_stays_governed(self) -> None:
        link = self.temp / "link"
        link.symlink_to(self.project, target_is_directory=True)
        self.assertEqual(self._edit(link / "notes.txt", cwd=self.bench), "deny")
        self.assertEqual(self._bash(f"rm {link / 'notes.txt'}", cwd=self.bench), "deny")
        escape = self.bench / ".." / ".." / ".." / ".." / ".." / "home" / "proj" / "notes.txt"
        self.assertEqual(self._bash(f"rm {escape}", cwd=self.bench), "deny")

    def test_a_project_outside_temp_is_unchanged(self) -> None:
        self.assertEqual(self._edit(self.project / "notes.txt"), "deny")
        self.assertEqual(self._bash(f"rm {self.project / 'notes.txt'}", cwd=self.bench), "deny")

    def test_a_temp_repository_with_no_home_outside_temp_stays_governed(self) -> None:
        """Test fixtures are repositories created in temp; they remain projects."""

        fixture = self.temp / "fixture"
        self._governed_repository(fixture)
        self.assertEqual(self._edit(fixture / "notes.txt"), "deny")


if __name__ == "__main__":
    unittest.main()
