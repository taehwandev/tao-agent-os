"""Which project a tool call touches, and whether that project is protected.

Split from `test_claude_pretool_gate.py` because these cases share one subject
and that file had outgrown its budget. Every one of them started as a bypass:
a path named through an option value, an operand assignment, a quoted script
body, a relative spelling, a runtime variable, a space, a backslash, adjacent
quotes, text the shell computes, a command too complex to parse, a filesystem
refusal, or a notebook key nothing read. They are kept together because they
answer the same question and fail the same way when one spelling is forgotten.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_claude_pretool_gate import (
    _decide,
    _opt_in_project,
    _reason,
    _require_linked_worktree,
)


class TargetProtectionTests(unittest.TestCase):
    def test_a_write_named_by_absolute_path_reaches_the_protected_checkout(
        self,
    ) -> None:
        """Bash is judged by its directory, which a named path steps around.

        Running from an unprotected directory found no project at the effective
        cwd and returned allow, so `cd /tmp && touch <protected>/file` wrote
        into the checkout the gate exists to protect. `path_arguments` was
        written for this and never called.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {"command": f"touch {project}/newfile"},
                }
            )

        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))
    def test_a_named_target_is_found_however_the_command_spells_it(self) -> None:
        """A path is a target wherever it sits in the token, not only at its head.

        Reading only tokens that begin with a slash missed an option's value,
        an operand assignment, an interpreter's quoted script, and any relative
        spelling; each of those wrote into the protected checkout.
        """

        forms = [
            "git diff --output={target}/f",
            "dd if=/dev/zero of={target}/f",
            "sh -c 'touch {target}/f'",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            for form in forms:
                command = form.format(target=project)
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(0, code, command)
                self.assertIn("worktree gate", _reason(out), command)

            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {"command": "touch ../protected/proj/f"},
                }
            )

        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))
    def test_a_target_named_through_a_variable_is_still_the_target(self) -> None:
        """The shell will expand it, so reading it unexpanded found no path."""

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
                for command in (
                    "touch $CLAUDE_PROJECT_DIR/should-not-write",
                    "touch ${CLAUDE_PROJECT_DIR}/should-not-write",
                ):
                    code, out = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(outside),
                            "session_id": "s",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual(0, code, command)
                    self.assertIn("worktree gate", _reason(out), command)
    def test_a_protected_path_containing_a_space_is_not_truncated(self) -> None:
        """Quoting is what carries the space, and matching stopped at it."""

        newline = chr(10)
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected space")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            for command in (
                f'touch "{project}/should-not-write"',
                f"sh -c 'touch \"{project}/should-not-write\"'",
                f"python3 - <<'E'{newline}open('{project}/x','w'){newline}E",
            ):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(0, code, command)
                self.assertIn("worktree gate", _reason(out), command)
    def test_a_notebook_edit_declares_its_target_like_every_other_edit(self) -> None:
        """NotebookEdit names `notebook_path`; only `file_path` was read.

        The tool was gated but its target was invisible, so a notebook inside a
        protected checkout was judged by the working directory alone.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            code, out = _decide(
                {
                    "tool_name": "NotebookEdit",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {"notebook_path": f"{project}/analysis.ipynb"},
                }
            )

        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))
    def test_a_target_the_filesystem_refuses_does_not_become_an_allow(self) -> None:
        """A crash in this gate is an allow, so it must not be reachable.

        A path longer than the filesystem accepts, or one carrying a null byte,
        made `resolve` and `exists` raise past `decide` to the top-level
        handler whose job is to fail open. A crafted target therefore turned an
        error into permission. Such a target is now treated the way text the
        shell computes is: unclaimable, and judged against the declared project.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
                for command in (
                    "touch " + "a" * 20000,
                    "touch \x00" + str(project) + "/f",
                ):
                    code, out = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(outside),
                            "session_id": "s",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual(0, code, command[:40])
                    self.assertIn("worktree gate", _reason(out), command[:40])

            # With no declared project there is nothing to protect, so the same
            # unanswerable target stays allowed rather than denying everywhere.
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {"command": "touch " + "a" * 20000},
                }
            )

        self.assertEqual(0, code)
        self.assertEqual("", out)
    def test_an_unlocatable_command_is_judged_against_the_main_checkout(self) -> None:
        """A linked worktree passing its own policy is not the question.

        Naming only the declared project answered with the one checkout that
        was never at risk, so a command whose target could not be read was
        cleared by it. A worktree and the main checkout it branched from are
        one repository, and the main checkout is the protected one.
        """

        with tempfile.TemporaryDirectory() as tmp:
            main = _opt_in_project(Path(tmp) / "main")
            _require_linked_worktree(main)
            worktree = _opt_in_project(Path(tmp) / "wt")
            (worktree / ".git").write_text(
                f"gitdir: {main}/.git/worktrees/proj\n", encoding="utf-8"
            )
            outside = Path(tmp) / "outside"
            outside.mkdir()
            environment = {
                "CLAUDE_PROJECT_DIR": str(worktree),
                "MAIN_TARGET": str(main),
                "REF": "MAIN_TARGET",
            }
            with patch.dict(os.environ, environment):
                for command in (
                    "touch ${MAIN_TARGET%/}/f",
                    "touch ${!REF}/f",
                    f"touch $(echo {main})/f",
                ):
                    code, out = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(outside),
                            "session_id": "s",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual(0, code, command)
                    self.assertIn("worktree gate", _reason(out), command)
    def test_a_path_assembled_from_adjacent_quotes_is_one_path(self) -> None:
        """`/main/pro"j"/f` is one path to the shell and two to a pattern.

        Quotes delimit a path containing spaces and also join fragments into
        one word, and reading them only as delimiters meant the assembled form
        reached a protected checkout from inside a nested shell.
        """

        newline = chr(10)
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            assembled = f"{str(project)[:-1]}\"{str(project)[-1]}\""
            for command in (
                f"touch {assembled}/f",
                f"sh -c 'touch {assembled}/f'",
                f"python3 - <<'E'{newline}open('{assembled}/f','w'){newline}E",
            ):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(0, code, command)
                self.assertIn("worktree gate", _reason(out), command)
    def test_a_read_only_substitution_is_not_an_unlocatable_mutation(self) -> None:
        """A substitution runs a program, so what it runs is the question.

        Masking every substitution called `echo $(rm -rf build)` a read;
        refusing to parse any of them called `echo $(date)` an unlocatable
        mutation and denied it outside every project. Classifying the
        substituted command separates the two.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": "echo $(date)"},
                    }
                )
                self.assertEqual(0, code)
                self.assertEqual("", out)

                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": "echo $(rm -rf build)"},
                    }
                )

        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))
    def test_a_backslash_escaped_space_names_the_same_directory(self) -> None:
        """`protected\\ space` and `"protected space"` are one path."""

        newline = chr(10)
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected space")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            escaped = str(project).replace(" ", "\\ ")
            for command in (
                f"touch {escaped}/f",
                f"sh -c 'touch {escaped}/f'",
                f"python3 - <<'E'{newline}open('{escaped}/f','w'){newline}E",
            ):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(0, code, command)
                self.assertIn("worktree gate", _reason(out), command)
    def test_text_the_shell_computes_is_judged_by_the_declared_project(self) -> None:
        """Spellings have no last move; knowing the targets does.

        A quoted space, an escaped space, `${VAR%/}` and `$(echo ...)` each
        arrived after the previous was closed. Where the shell builds the text,
        no reading of it locates the command, so the session's own project is
        what such a command is judged against.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
                for command in (
                    "touch ${CLAUDE_PROJECT_DIR%/}/f",
                    f"touch $(echo {project})/f",
                    f"touch `echo {project}`/f",
                    # Indirect expansion is the spelling that showed the rule
                    # was still an enumeration: it was not on the operator list
                    # and passed. The brace form is now matched positively, so
                    # anything that is not a bare name is computed text.
                    "touch ${!REF}/f",
                    "touch ${#VAR}/f",
                    "touch ${VAR^^}/f",
                ):
                    code, out = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(outside),
                            "session_id": "s",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual(0, code, command)
                    self.assertIn("worktree gate", _reason(out), command)

                # A plain substitution is resolved exactly, so it is not swept
                # up by the same rule, and ordinary work is untouched.
                for allowed in ("ls -la", "rm -rf build", "git commit -m 'x'"):
                    code, out = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(outside),
                            "session_id": "s",
                            "tool_input": {"command": allowed},
                        }
                    )
                    self.assertEqual(0, code, allowed)
                    self.assertEqual("", out, allowed)
    def test_a_command_too_complex_to_parse_is_judged_by_the_paths_it_names(
        self,
    ) -> None:
        """Refusing to tokenise says what a command does, not where it does it.

        A heredoc or a substitution parses to no tokens, which is the right
        answer for classification and left the gate with nothing to locate:
        `cd <protected> && python3 - <<'E'` ran unexamined. The raw text still
        names the checkout, and reading a path needs no syntax.
        """

        newline = chr(10)
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            unparseable = [
                f"cd {project} && python3 - <<'E'{newline}print(1){newline}E",
                f"python3 - <<'E'{newline}open('{project}/f','w'){newline}E",
                f"echo $(touch {project}/f)",
            ]
            for command in unparseable:
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(outside),
                        "session_id": "s",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(0, code, command)
                self.assertIn("worktree gate", _reason(out), command)

            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"python3 - <<'E'{newline}print(1){newline}E"
                    },
                }
            )

        self.assertEqual(0, code)
        self.assertEqual("", out)
    def test_a_linked_worktree_cannot_write_into_the_protected_checkout(self) -> None:
        """Its own policy passing is not the same as every target's passing.

        The first root answered for the whole command, and a linked worktree is
        a project in good standing, so naming the main checkout it branched
        from was never examined.
        """

        with tempfile.TemporaryDirectory() as tmp:
            main = _opt_in_project(Path(tmp) / "main")
            _require_linked_worktree(main)
            worktree = _opt_in_project(Path(tmp) / "wt")
            _require_linked_worktree(worktree, linked=True)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(worktree),
                    "session_id": "s",
                    "tool_input": {"command": f"touch {main}/f"},
                }
            )

        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))
    def test_reading_a_protected_path_from_outside_is_still_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(project)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(outside),
                    "session_id": "s",
                    "tool_input": {"command": f"cat {project}/AGENTS.md"},
                }
            )

        self.assertEqual(0, code)
        self.assertEqual("", out)
