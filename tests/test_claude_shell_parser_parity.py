"""One shell reader: the gate's verdicts are unchanged by moving its parser.

The publication hold carried its own copy of the shell grammar inside the
gate, and the two copies drifted -- `env -S "git push"` and `time -o out -P`
were each fixed in one only. Its vocabulary now lives in `claude_bash_syntax`
and its raw-line splitter in `claude_bash_raw_lines`.
`claude_shell_parser_parity.json` holds verdicts generated from the gate
before the move, for a corpus of the shapes those bypasses came from; every
public reading must still give them.
"""

from __future__ import annotations

import json
import shlex
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claude_bash_raw_lines as raw_lines  # noqa: E402
import claude_bash_readonly as readonly  # noqa: E402
import claude_bash_syntax as syntax  # noqa: E402
import claude_pretool_gate as gate  # noqa: E402
import claude_pretool_publication as publication  # noqa: E402
from claude_command_effect import command_effect  # noqa: E402

CORPUS = Path(__file__).with_name("claude_shell_parser_parity.json")
CWD = Path("/nonexistent-parity-cwd")


def _plain(value: object) -> object:
    """JSON's view of a verdict, so tuples and lists compare alike."""

    return json.loads(json.dumps(value))


def verdicts(command: str) -> dict:
    try:
        words = shlex.split(command)
    except ValueError:
        words = None
    _cwd, tokens, simple = readonly.bash_invocation({"tool_input": {"command": command}}, CWD)
    kind = readonly.bash_command_kind(tokens, simple)
    return _plain({
        "hold": gate.publication_hold(command),
        "segments": raw_lines.raw_command_segments(command),
        "segments_strict": raw_lines.raw_command_segments(command, reject_redirections=True),
        "substitution_runs": raw_lines.substitution_runs(command),
        "behind": None if words is None else syntax.command_behind_wrappers(words),
        "before_finish": None if words is None else gate.publishes_before_finish(words),
        "stripped": None if words is None else readonly.strip_env_assignments(words),
        "unwrapped": None if words is None else readonly.strip_env_wrapper(words),
        "tokens": tokens,
        "simple": simple,
        "kind": kind,
        "effect": command_effect(tokens, simple, kind)[0],
        "syntax_segments": syntax.command_segments(tokens),
    })


class ShellParserParityTests(unittest.TestCase):
    def test_every_corpus_verdict_matches_the_gate_before_the_move(self) -> None:
        cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 100)
        for case in cases:
            with self.subTest(command=case["command"]):
                self.assertEqual(case["expected"], verdicts(case["command"]))

    def test_the_gate_re_exports_the_publication_readers(self) -> None:
        tokens = ["env", "-S", "git push"]
        self.assertEqual(
            publication.publishes_before_finish(tokens), gate.publishes_before_finish(tokens)
        )
        self.assertEqual("unreadable", gate.publishes_before_finish(tokens))
        self.assertFalse(hasattr(gate, "_command_segments"))
        self.assertFalse(hasattr(gate, "_shell_command_parts"))


class ZshFileSubstitutionTests(unittest.TestCase):
    """The one place the two copies disagreed, settled on the stricter side.

    `claude_bash_syntax` already treated zsh's `=(...)` as a substitution;
    the gate's copy did not, so `git status =(git push)` read as a plain
    status while zsh ran the push. It is now unreadable, and only at the
    start of an unquoted word, where zsh expands it.
    """

    def test_a_word_opening_file_substitution_is_unreadable(self) -> None:
        for command in ("git status =(git push)", "cat =(git push)", "echo ok;=(git push)"):
            with self.subTest(command=command):
                self.assertEqual("unreadable", gate.publication_hold(command))
                self.assertIsNone(raw_lines.raw_command_segments(command))

    def test_an_array_or_quoted_text_is_not_a_substitution(self) -> None:
        for command in ("arr=(a b) && git status", "echo '=(git push)'", 'echo "=(x)"'):
            with self.subTest(command=command):
                self.assertEqual("", gate.publication_hold(command))
                self.assertFalse(raw_lines.substitution_runs(command))


if __name__ == "__main__":
    unittest.main()
