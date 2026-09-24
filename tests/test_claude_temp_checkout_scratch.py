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


class OnlyProvenTempWritesAreScratchTests(_Fixture):
    """Observed: a Python command run in the temp worktree rewrote a file of
    the original project through TAO_HOME, and the gate allowed it.

    Only a file utility whose every operand lands in temp is scratch; any other
    program can write anywhere, so its verdict is the one the checkout had
    before it was exempted.
    """

    def _governed_verdict(self, command: str, cwd: Path) -> str:
        with patch.object(pretool, "throwaway_checkout", lambda root: False):
            return self._bash(command, cwd=cwd)

    def _assert_governed(self, command: str, cwd: "Path | None" = None) -> None:
        cwd = cwd or self.bench
        with self.subTest(command=command):
            verdict = self._bash(command, cwd=cwd)
            self.assertNotEqual(verdict, "allow")
            self.assertEqual(verdict, self._governed_verdict(command, cwd))

    def test_programs_that_can_write_anywhere_stay_governed(self) -> None:
        (self.bench / "script.py").write_text("print(1)\n")
        (self.bench / "tool").write_text("#!/bin/sh\n")
        real = self.project / "notes.txt"
        for command in (
            f"python3 -c \"open('{real}','w').write('x')\"",
            "python3 -c \"import os; open(os.environ['TAO_HOME'] + '/notes.txt', 'w')\"",
            "python3 script.py",
            "node x.js",
            "npm run x",
            "npx something",
            "make",
            "./tool",
            f"{self.bench / 'tool'}",
            "FOO=1 rm docs/probe.txt",
            f"find {self.project} -delete",
            f"echo x | tee {real}",
            "echo docs/probe.txt | xargs rm",
        ):
            self._assert_governed(command)

    def test_a_file_utility_with_an_operand_outside_temp_stays_governed(self) -> None:
        inside = self.bench / "docs" / "probe.txt"
        real = self.project / "notes.txt"
        for command in (
            f"cp {inside} {real}",
            f"mv {inside} {real}",
            f"mv {real} {inside}",
            f"ln -s {inside} {real}",
            f"touch {real}",
            f"echo x > {real}",
        ):
            self._assert_governed(command)

    def test_file_writes_proven_inside_temp_need_no_run(self) -> None:
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
