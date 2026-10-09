"""Scratch writes and quoted text, as the Claude Bash gate reads them.

Two families of refusal from one KeyFlow session. Output sent to the session
scratchpad or the OS temp directory was read as a write into the project the
shell stood in, so `grep ... > <scratch>/x` and `curl -o <scratch>/page` needed
a workflow start that governs nothing they touch. And text the shell hands on
unchanged -- a commit message, a start `--request`, an escaped backquote --
was read for paths, so a refusal named the Tao checkout for a commit into
another repository.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import claude_bash_readonly as bash_readonly
import claude_pretool_gate as pretool
import claude_worktree_gate as gate
from claude_bash_syntax import bash_invocation, scratch_write_target


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.tao = self._project("tao", policy=True)
        self.cli = self._project("cli", policy=True)
        self.app = self._project("app", policy=False)
        (self.app / "f.txt").write_text("x\n")
        self.scratch = self.base / "claude-501" / "-app" / "session" / "scratchpad"
        self.scratch.mkdir(parents=True)
        environment = patch.dict(
            os.environ,
            {"TAO_HOME": str(self.tao), "CLAUDE_PROJECT_DIR": str(self.app)},
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.launcher = str(gate.stable_launcher_path())

    def _project(self, name: str, *, policy: bool) -> Path:
        root = self.base / name
        (root / ".git").mkdir(parents=True)
        (root / "AGENTS.md").write_text("Uses tao-hook.\n")
        if policy:
            shared = root / ".agents" / "shared"
            shared.mkdir(parents=True)
            (shared / "worktree-policy.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "require_linked_worktree": True,
                        "protected_branches": ["main"],
                    }
                )
            )
        return root

    def _verdict(self, command: str, cwd: Path | None = None) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            pretool.decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(cwd or self.app),
                    "session_id": "scratch-and-quoted-text",
                    "tool_input": {"command": command},
                }
            )
        printed = output.getvalue().strip()
        if not printed:
            return ""
        output = json.loads(printed)["hookSpecificOutput"]
        return output.get("permissionDecisionReason") or output.get("additionalContext", "")


class ScratchWriteTests(_Fixture):
    def test_a_read_redirected_into_the_scratchpad_is_still_a_read(self) -> None:
        """Observed: `... > <scratchpad>/unit.log 2>&1` asked for a start."""

        for redirect in (">", ">>", "2>", "&>"):
            command = f"grep -n x {self.app}/f.txt {redirect} {self.scratch}/out.log"
            with self.subTest(redirect=redirect):
                self.assertEqual("", self._verdict(command))
        self.assertEqual(
            "", self._verdict(f"grep -n x f.txt > {self.scratch}/out.log 2>&1")
        )

    def test_a_pipeline_inside_the_scratchpad_needs_no_project_start(self) -> None:
        command = (
            f"cd {self.scratch} && grep -o 'chunks/[^\"]*' home.html | sort -u "
            "> chunks.txt; wc -l < chunks.txt"
        )

        self.assertEqual("", self._verdict(command))

    def test_curl_output_into_the_scratchpad_is_a_read(self) -> None:
        for command in (
            f"curl -q -s -o {self.scratch}/home.html https://example.com/",
            f"curl -q -so {self.scratch}/home.html https://example.com/",
            f"curl -q -s --output={self.scratch}/home.html https://example.com/",
            f'curl -q -s -A "agent/1.0" -o {self.scratch}/post.html '
            '-w "code=%{http_code} size=%{size_download}\\n" https://example.com/p',
            'curl -q -s -o /dev/null -w "%{http_code}\\n" https://example.com/',
        ):
            with self.subTest(command=command):
                self.assertEqual("", self._verdict(command))

    def test_curl_write_out_into_a_file_stays_a_write(self) -> None:
        command = (
            'curl -q -s -o /dev/null -w "%output{' f"{self.app}/x" '}%{http_code}" '
            "https://example.com/"
        )

        self.assertNotEqual("", self._verdict(command))

    def test_a_project_command_keeps_its_own_verdict(self) -> None:
        """`npm run build > <scratch>` is judged as `npm run build`, which runs project code."""

        scratch = self._verdict(f"npm run build > {self.scratch}/unit.log 2>&1")

        self.assertNotEqual("", scratch)
        self.assertEqual(self._verdict("npm run build > /dev/null 2>&1"), scratch)

    def test_writes_that_land_in_a_project_stay_writes(self) -> None:
        link = self.scratch / "link"
        link.symlink_to(self.app)
        for command in (
            f"grep -n x f.txt > {self.app}/out.txt",
            "grep -n x f.txt > out.txt",
            f"grep -n x f.txt > {self.scratch}/../../../../app/out.txt",
            f"grep -n x f.txt > {link}/out.txt",
            f"grep -n x f.txt > {self.scratch}/$NAME",
            f"curl -q -s -o {self.app}/page.html https://example.com/",
        ):
            with self.subTest(command=command):
                self.assertNotEqual("", self._verdict(command))

    def test_only_unmarked_temp_directories_are_scratch(self) -> None:
        self.assertTrue(scratch_write_target(str(self.scratch / "a.log"), self.app))
        self.assertTrue(scratch_write_target("a.log", self.scratch))
        # A project that happens to live under the temp directory is a project.
        self.assertFalse(scratch_write_target(str(self.app / "a.log"), self.base))
        self.assertFalse(scratch_write_target("a.log", self.app))
        self.assertFalse(scratch_write_target("/etc/hosts", self.app))
        self.assertFalse(scratch_write_target(str(Path.home() / "a.log"), self.app))
        self.assertFalse(scratch_write_target("/tmp", self.app))
        self.assertFalse(scratch_write_target("/private/tmp/../etc/hosts", self.app))

    def test_custom_temp_root_cannot_hide_its_project_or_ancestor(self) -> None:
        nested = self.app / "build" / "tmp"
        nested.mkdir(parents=True)
        for root in (self.app, nested):
            target = root / "kept.txt"
            target.write_text("project content\n")
            with self.subTest(root=root), patch.dict(os.environ, {"TMPDIR": str(root)}), \
                    patch("claude_bash_syntax.SCRATCH_ROOTS", ()), \
                    patch("claude_bash_syntax.tempfile.gettempdir", return_value=str(root)):
                self.assertFalse(scratch_write_target(str(target), None))
                self.assertNotEqual("", self._verdict(f"cat /dev/null > {target}"))
                self.assertEqual("project content\n", target.read_text())

    def test_unmarked_custom_temp_root_still_allows_scratch(self) -> None:
        with patch.dict(os.environ, {"TMPDIR": str(self.scratch)}), \
                patch("claude_bash_syntax.SCRATCH_ROOTS", ()), \
                patch("claude_bash_syntax.tempfile.gettempdir", return_value=str(self.scratch)):
            target = self.scratch / "log.txt"
            self.assertTrue(scratch_write_target(str(target), None))
            self.assertEqual("", self._verdict(f"cat /dev/null > {target}"))


class QuotedTextTests(_Fixture):
    def test_a_newline_inside_quotes_is_part_of_one_argument(self) -> None:
        command = f'git -C {self.cli} commit -q -m "subject\n\nbody line"'

        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, self.app)

        self.assertTrue(simple)
        self.assertEqual("subject\n\nbody line", tokens[-1])

    def test_an_unquoted_newline_is_still_two_commands(self) -> None:
        command = f"git status\ntouch {self.tao}/note"

        _, _, simple = bash_invocation({"tool_input": {"command": command}}, self.app)
        reason = self._verdict(command, cwd=self.tao)

        self.assertFalse(simple)
        self.assertIn("use one literal command", reason)
        self.assertIn(str(self.tao), reason)

    def test_a_commit_message_names_no_checkout(self) -> None:
        """Observed: a keyflow-cli commit refused as a write into tao-agent-os,
        because its message mentioned `$TAO_HOME`."""

        def command(checkout: Path) -> str:
            return (
                f'cd {checkout} && git commit -q -m "chore: move assets\n\n'
                "Update checks to use\n\\$TAO_HOME paths.\n\nCo-Authored-By: A <a@b.c>\" "
                '2>&1 | grep -E "rror"; git log --oneline -1'
            )

        # A checkout with its own isolation policy is judged under its name.
        # The compound line is now deferred as unresolved rather than denied
        # (e35caf14); the attribution is what this test pins.
        protected = self._verdict(command(self.cli))
        self.assertIn(f"main checkout: {self.cli}.", protected)
        self.assertNotIn(str(self.tao), protected)
        # One without a policy is judged by the ordinary rules, never under the
        # name of the checkout its message happened to mention.
        unprotected = self._project("cli-open", policy=False)
        _, tokens, _ = bash_invocation(
            {"tool_input": {"command": command(unprotected)}}, self.app
        )
        self.assertNotIn(
            self.tao, pretool.bash_governed_roots(tokens, unprotected, command="")
        )
        self.assertNotIn(str(self.tao), self._verdict(command(unprotected)))

    def test_an_escaped_backquote_is_not_computed_text(self) -> None:
        """Observed: a chained start refused as a write into its `--rules` root,
        because `\\`` inside double quotes read as a command substitution."""

        command = (
            f"{self.launcher} start --project {self.app} --rules {self.tao} "
            '--command task --request "two\nlines" --intent x --target-summary y '
            '2>&1 | grep -E "^SUCCESS"; '
            f'cd {self.app} && grep -n "a\\|^5\\. \\`keyflow\\`" f.txt'
        )

        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.app)
        reason = self._verdict(command)

        self.assertTrue(tokens)
        self.assertNotIn(str(self.tao), reason)

    def test_start_prose_options_name_no_target(self) -> None:
        command = (
            f"{self.launcher} start --project {self.app} --rules {self.tao} "
            f'--command bugfix --request "compare with {self.tao}/scripts" '
            f'--target-summary "{self.cli}/x.py" --intent x'
        )

        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.base)
        roots = pretool.bash_target_project_roots(tokens, self.base)

        self.assertIn(self.app, roots)
        self.assertNotIn(self.tao, roots)
        self.assertNotIn(self.cli, roots)

    def test_a_real_substitution_is_still_unreadable(self) -> None:
        for command in (
            'git commit -m "$(touch x)"',
            'git commit -m "`touch x`"',
            'git commit -m "\\\\`touch x`"',
        ):
            with self.subTest(command=command):
                _, tokens, simple = bash_invocation(
                    {"tool_input": {"command": command}}, self.app
                )
                self.assertEqual([], tokens)
                self.assertFalse(simple)

    def test_commit_message_exemption_covers_only_the_message(self) -> None:
        command = f'git -C {self.app} commit -m "see {self.tao}" {self.cli}/f'

        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.base)
        indices = bash_readonly.read_only_path_token_indices(tokens)

        self.assertIn(tokens.index(f"see {self.tao}"), indices)
        self.assertNotIn(tokens.index(f"{self.cli}/f"), indices)


class LongCommitMessageTests(_Fixture):
    """Observed: a linked-worktree commit refused as a write into the main
    checkout the session was declared in, because its 451-byte message held
    no `/`, so `lstat` called the whole message one over-long file name."""

    MESSAGE = "fix(gate): keep messages out of paths\n\n" + "body words " * 40

    def setUp(self) -> None:
        super().setUp()
        self.worktree = self._project("wt", policy=False)
        self.assertNotIn("/", self.MESSAGE)
        self.assertGreater(len(self.MESSAGE.encode()), 300)

    def _roots(self, command: str) -> list[Path]:
        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.worktree)
        self.assertTrue(tokens)
        return pretool.bash_target_project_roots(tokens, self.worktree)

    def test_a_long_message_does_not_pull_in_the_declared_project(self) -> None:
        sha = "a" * 40
        for command in (
            f'git -C {self.worktree} commit -qam "{self.MESSAGE}"',
            f'git -C {self.worktree} commit -am "{self.MESSAGE}"',
            f'git -C {self.worktree} commit -q -m "{self.MESSAGE}"',
            f'git -C {self.worktree} commit --message "{self.MESSAGE}"',
            f'git -C {self.worktree} commit-tree {sha} -p {sha} -m "{self.MESSAGE}"',
            f'git -C {self.worktree} tag -am "{self.MESSAGE}" v1',
            f'git -C {self.worktree} merge --no-ff -m "{self.MESSAGE}" topic',
            f'git -C {self.worktree} stash push -m "{self.MESSAGE}"',
            f'git -C {self.worktree} notes add -m "{self.MESSAGE}" HEAD',
        ):
            with self.subTest(command=command[:60]):
                self.assertEqual([self.worktree], self._roots(command))

    def test_an_overlong_path_outside_the_message_stays_unclaimable(self) -> None:
        overlong = "x" * 300
        for command in (
            f'git -C {self.worktree} commit -qam "short" {overlong}',
            f'git -C {self.worktree} commit -m "short" -- -m {overlong}',
            f'git -C {self.worktree} commit -m -m {overlong}',
            f'git -C {self.worktree} commit -Fm {overlong}',
        ):
            with self.subTest(command=command[:60]):
                self.assertIn(self.app, self._roots(command))

    def test_a_dash_m_taken_as_an_option_value_is_no_message(self) -> None:
        """`-p -m <path>` hands `-m` to `-p` as its parent, so Git reads no
        message there and `<path>` is an operand to judge."""

        overlong = "x" * 300
        sha = "a" * 40
        for command in (
            f"git -C {self.worktree} commit-tree {sha} -p -m {overlong}",
            f"git -C {self.worktree} commit -F -m {overlong}",
            f"git -C {self.worktree} commit -C -m {overlong}",
            f"git -C {self.worktree} commit -qF -m {overlong}",
            f"git -C {self.worktree} commit --author -m {overlong}",
            f"git -C {self.worktree} commit --auth -m {overlong}",
            f"git -C {self.worktree} tag -u -m {overlong}",
            f"git -C {self.worktree} merge -s -m {overlong}",
            f"git -C {self.worktree} notes --ref -m add {overlong}",
            f"git -C {self.worktree} notes add -C -m {overlong}",
            f"git -C {self.worktree} stash push --pathspec-from-file -m {overlong}",
        ):
            with self.subTest(command=command[:70]):
                self.assertIn(self.app, self._roots(command))

    def test_a_message_after_a_consumed_value_is_still_a_message(self) -> None:
        sha = "a" * 40
        for command in (
            f'git -C {self.worktree} commit -F msg.txt -m "{self.MESSAGE}"',
            f'git -C {self.worktree} commit-tree {sha} -p {sha} -m "{self.MESSAGE}"',
            f'git -C {self.worktree} commit --author=a -S -m "{self.MESSAGE}"',
            f'git -C {self.worktree} tag -u key -am "{self.MESSAGE}" v1',
            f'git -C {self.worktree} merge -s ort -X ours -m "{self.MESSAGE}" topic',
        ):
            with self.subTest(command=command[:70]):
                self.assertEqual([self.worktree], self._roots(command))

    def test_the_main_checkout_named_by_C_is_still_the_target(self) -> None:
        self.assertIn(
            self.cli, self._roots(f'git -C {self.cli} commit -qam "{self.MESSAGE}"')
        )


if __name__ == "__main__":
    unittest.main()
