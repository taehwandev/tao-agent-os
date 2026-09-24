"""What the worktree gate does with the workflow start hook itself.

Three shapes of `start` were refused in one afternoon, and each refusal sent
the reader somewhere the fix was not. A start whose `--request` merely quoted
a command was called unreadable syntax; a start bound to the protected
checkout was refused with no cause at all and advice to move the shell, which
changes nothing about where a run is bound; and a start chained behind another
command was told to go to a worktree rather than to unchain itself. The
`--rules` root a start must name to find its guidance was read as somewhere it
would write, so naming the shared library put that checkout in the verdict.
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
from claude_bash_syntax import bash_invocation


class WorkflowStartDenialTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.launcher = str(gate.stable_launcher_path())
        self.main = self._project("main", linked_worktree=False)
        self.worktree = self._project("task", linked_worktree=True)
        self.other = self._project("other", linked_worktree=True)

    def _project(self, name: str, *, linked_worktree: bool) -> Path:
        root = self.base / name
        root.mkdir(parents=True)
        if linked_worktree:
            (root / ".git").write_text("gitdir: /unused/test-metadata\n")
        else:
            (root / ".git").mkdir()
        (root / "AGENTS.md").write_text("Uses tao-hook.\n")
        policy = root / ".agents" / "shared"
        policy.mkdir(parents=True)
        (policy / "worktree-policy.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "require_linked_worktree": True,
                    "protected_branches": ["main"],
                }
            )
        )
        return root

    def _verdict(self, command: str) -> str:
        """The refusal text for this command, or an empty string when allowed."""

        output = io.StringIO()
        with redirect_stdout(output):
            pretool.decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(self.main),
                    "session_id": "start-denial",
                    "tool_input": {"command": command},
                }
            )
        printed = output.getvalue().strip()
        if not printed:
            return ""
        return json.loads(printed)["hookSpecificOutput"]["permissionDecisionReason"]

    def _start(self, project: Path, request: str = "REQUEST") -> str:
        return (
            f"{self.launcher} start --project {project} --rules {self.main} "
            f"--command docs --request '{request}' --intent documentation "
            "--target-summary 'TARGET'"
        )

    def test_a_backquote_inside_a_quoted_argument_is_not_unsafe_syntax(self) -> None:
        """Observed as `Cause: use one literal command; chains, pipes, and
        multiline input are not accepted` on a start that was one command."""

        command = self._start(self.worktree, "run `git status` first")

        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, self.base)

        self.assertTrue(simple)
        self.assertEqual("workflow_start", bash_readonly.bash_command_kind(tokens, simple))
        self.assertEqual("", self._verdict(command))

    def test_a_substitution_outside_single_quotes_is_still_unreadable(self) -> None:
        for request in ('run "$(git status)" first', "run $(git status) first"):
            with self.subTest(request=request):
                command = (
                    f'{self.launcher} start --project {self.worktree} '
                    f'--rules {self.main} --request "{request}"'
                )
                _, tokens, simple = bash_invocation(
                    {"tool_input": {"command": command}}, self.base
                )
                self.assertEqual([], tokens)
                self.assertFalse(simple)

    def test_an_apostrophe_in_a_double_quoted_argument_hides_nothing(self) -> None:
        """A literal `'` must not open a masked region and swallow the
        substitution that follows it."""

        command = f'{self.launcher} start --request "it\'s $(touch result)"'

        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, self.base)

        self.assertEqual([], tokens)
        self.assertFalse(simple)

    def test_a_start_bound_to_the_protected_checkout_says_which_flag_binds_it(self) -> None:
        """Observed with no `Cause:` clause at all, and a remedy that told the
        reader to move the shell."""

        reason = self._verdict(self._start(self.main))

        self.assertIn("would bind its run to the protected checkout", reason)
        self.assertIn("`--project <worktree>`", reason)
        self.assertNotIn('git -C "<worktree>"', reason)

    def test_a_start_bound_to_a_linked_worktree_is_allowed(self) -> None:
        self.assertEqual("", self._verdict(self._start(self.worktree)))

    def _main_start(self, route: str, *extra: str) -> str:
        return (
            f"{self.launcher} start --project {self.main} --rules {self.main} "
            f"--command {route} --request 'REQUEST' --intent review_only "
            f"--target-summary 'TARGET' {' '.join(extra)}"
        ).strip()

    def test_a_read_only_review_lifecycle_runs_in_the_protected_checkout(self) -> None:
        """A read-only review writes only its own run evidence, so sending it
        to a throwaway worktree was procedure without a boundary."""

        for command in (
            self._main_start("review"),
            self._main_start("analysis"),
            self._main_start("review", "--read-only"),
            self._main_start("docs", "--read-only"),
            self._main_start("review", "--requested-effect", "read"),
            f"{self.launcher} review --project {self.main} --rules {self.main} "
            "--review-outcome findings",
            f"{self.launcher} finish --project {self.main} --rules {self.main}",
        ):
            with self.subTest(command=command):
                self.assertEqual("", self._verdict(command))

    def test_a_writable_start_in_the_protected_checkout_stays_refused(self) -> None:
        for command in (
            self._main_start("bugfix"),
            self._main_start("review", "--approved-effect", "git_write"),
            self._main_start("review", "--requested-effect", "local_write"),
            self._main_start("review", "--command", "bugfix"),
        ):
            with self.subTest(command=command):
                self.assertIn(
                    "would bind its run to the protected checkout", self._verdict(command)
                )

    def test_a_chained_start_is_told_to_unchain_it(self) -> None:
        """Observed as the worktree remedy, which is advice about a different
        problem than the semicolon that caused the refusal."""

        reason = self._verdict(f"touch {self.main}/note ; {self._start(self.other)}")

        self.assertIn("use one literal command", reason)
        self.assertIn("alone, as the only command on the line", reason)
        self.assertNotIn("use the task worktree", reason)

    def test_heredoc_denial_explains_input_recovery_without_new_authority(self) -> None:
        reason = self._verdict(f"{self.launcher} checkpoint --project {self.worktree} --work-stdin <<'EOF'\n{{}}\nEOF")
        self.assertIn('heredoc input is unsupported', reason)
        self.assertIn('< input-file', reason)
        self.assertIn('Keep the existing run', reason)
        self.assertNotIn('write blocked in main checkout', reason)

    def test_a_chained_command_without_a_start_keeps_the_worktree_remedy(self) -> None:
        reason = self._verdict(f"touch {self.main}/one ; touch {self.main}/two")

        self.assertIn("use one literal command", reason)
        self.assertNotIn("alone, as the only command on the line", reason)

    def test_the_rules_root_is_a_place_a_hook_reads(self) -> None:
        """The Notmid refusal named the Tao checkout, which `--rules` is the
        only reason the command mentioned."""

        _, tokens, _ = bash_invocation(
            {"tool_input": {"command": self._start(self.other)}}, self.base
        )

        roots = pretool.bash_target_project_roots(tokens, self.base)

        self.assertIn(self.other, roots)
        self.assertNotIn(self.main, roots)

    def test_read_segment_does_not_make_shared_guidance_a_write_target(self) -> None:
        command = f"cat {self.main}/AGENTS.md ; touch {self.other}/note"
        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.other)
        roots = pretool.bash_target_project_roots(tokens, self.other)
        self.assertNotIn(self.main, roots)
        self.assertIn(self.other, roots)

    def test_read_operand_exemption_does_not_hide_later_write_or_redirection(self) -> None:
        for command in (
            f"cat {self.main}/AGENTS.md ; touch {self.main}/note",
            f"cat {self.other}/AGENTS.md > {self.main}/note",
        ):
            with self.subTest(command=command):
                _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, self.other)
                self.assertIn(self.main, pretool.bash_target_project_roots(tokens, self.other))

    def test_the_project_root_remains_a_place_a_hook_writes(self) -> None:
        _, tokens, _ = bash_invocation(
            {"tool_input": {"command": self._start(self.main)}}, self.base
        )

        self.assertIn(self.main, pretool.bash_target_project_roots(tokens, self.base))

    def test_only_a_recognised_launcher_and_hook_earns_the_rules_exemption(self) -> None:
        for command in (
            f"/usr/bin/other-tool start --project {self.other} --rules {self.main}",
            f"{self.launcher} publish --project {self.other} --rules {self.main}",
        ):
            with self.subTest(command=command):
                _, tokens, _ = bash_invocation(
                    {"tool_input": {"command": command}}, self.base
                )
                self.assertIn(
                    self.main, pretool.bash_target_project_roots(tokens, self.base)
                )


if __name__ == "__main__":
    unittest.main()
