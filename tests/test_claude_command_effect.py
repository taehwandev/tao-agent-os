from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_readonly import bash_invocation, bash_command_kind
from claude_command_effect import command_effect


class CommandEffectTests(unittest.TestCase):
    def effect(self, command):
        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
        return command_effect(tokens, simple, bash_command_kind(tokens, simple))

    def test_effects_are_distinct_without_changing_legacy_authority(self):
        for command, expected in (
            ("rg value file", "read_only"),
            ("curl -q https://example.test", "read_only"),
            ("touch file", "mutating"),
            ("cat file | tee destination", "mutating"),
            ("curl -q -X POST https://example.test", "mutating"),
            ("curl -q -o saved.json https://example.test", "mutating"),
            ("curl -q -H '-XPOST' https://example.test", "read_only"),
            ("cat file > destination", "mutating"),
            ("custom-tool inspect", "unknown"),
            ("python3 custom.py", "unknown"),
            ("curl https://example.test", "unknown"),
            ("curl -q --unknown https://example.test", "unknown"),
        ):
            with self.subTest(command=command):
                self.assertEqual(expected, self.effect(command)[0])

    def test_unknown_explanation_names_boundary_without_echoing_sensitive_arguments(self):
        effect, reason = self.effect("curl -H 'Authorization: Bearer PRIVATE' https://example.test/private")
        self.assertEqual("unknown", effect)
        self.assertIn("put -q first", reason)
        self.assertNotIn("PRIVATE", reason)
        self.assertNotIn("example.test", reason)

    def test_unparsed_or_mixed_command_never_becomes_a_verified_read(self):
        for command in ("cat file && custom-tool", "curl -q https://example.test | tee saved", "echo $(python3 unknown.py)"):
            self.assertNotEqual("read_only", self.effect(command)[0])
