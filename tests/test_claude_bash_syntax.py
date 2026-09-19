"""Command location and effect contracts across shell line boundaries."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from claude_bash_syntax import bash_invocation
from claude_bash_readonly import bash_command_kind


class ShellLineTests(unittest.TestCase):
    def invocation(self, command):
        return bash_invocation({'tool_input': {'command': command}}, Path('/tmp'))

    def test_multiline_reads_keep_individual_effects(self):
        for command in ('git status --short\nrg owner src', 'cat AGENTS.md\nsed -n "1,5p" README.md',
                        'rg own\\\ner src', "rg 'first\nsecond' src"):
            with self.subTest(command=command):
                _, tokens, simple = self.invocation(command)
                self.assertEqual('read_only', bash_command_kind(tokens, simple))

    def test_quoted_script_lines_preserve_explicit_directory_not_read_authority(self):
        cwd, tokens, simple = self.invocation("cd /tmp/task && python3 -c 'print(1)\nprint(2)'")
        self.assertEqual(Path('/tmp/task').resolve(), cwd)
        self.assertEqual('print(1)\nprint(2)', tokens[-1])
        self.assertTrue(simple)
        self.assertEqual('mutating', bash_command_kind(tokens, simple))

    def test_newlines_do_not_hide_writes_or_unsupported_shell(self):
        for command in ('git status\ntouch result', 'cat README.md\nrm result',
                        'cat README.md\ncat AGENTS.md > saved',
                        'cat <<EOF\nhello\nEOF', 'cat README.md # comment\ntouch result',
                        'cat "$(touch result)\ntext"', 'cat <(touch result)\ntrue',
                        'rg "unterminated\ntext', 'cat README.md\r\ntouch result',
                        'cat $\\\n(touch result)', 'cat <\\\n(touch result)'):
            with self.subTest(command=command):
                _, tokens, simple = self.invocation(command)
                self.assertEqual('mutating', bash_command_kind(tokens, simple))
