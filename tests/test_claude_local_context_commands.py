"""Exact local context grammar without an exemption for arbitrary writes."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_local_context_commands import local_context_kind


class LocalContextCommandTests(unittest.TestCase):
    def test_reference_and_execution_send_share_local_effect(self):
        for tail in ([], ["--evidence", "/repo/preflight.json"]):
            self.assertEqual("runtime_control", local_context_kind(
                "agent-mailbox", ["send", "--to=claude", "--json", *tail]))

    def test_bad_grammar_does_not_gain_admission(self):
        for alias, arguments in (
            ("project-memory", ["--project"]),
            ("project-memory", ["capture", "--source"]),
            ("project-memory", ["capture", "--source="]),
            ("project-memory", ["retire", "id", "extra"]),
            ("project-memory", ["capture", "--unknown", "path"]),
            ("agent-mailbox", ["send", "--to", "--output"]),
            ("agent-mailbox", ["send", "extra"]),
            ("work-cards", ["close", "id"]),
        ):
            with self.subTest(alias=alias, arguments=arguments):
                self.assertIsNone(local_context_kind(alias, arguments))
