from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from claude_bash_readonly import bash_invocation, bash_command_kind


class HttpClassificationTests(unittest.TestCase):
    def kind(self, command: str) -> str:
        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
        return bash_command_kind(tokens, simple)

    def test_provider_independent_reads(self):
        for command in (
            "curl -q https://example.test/api/projects/",
            "curl --disable -sSfL --max-time 20 https://example.test/events | jq '.[] | .id'",
            "curl -q -I https://localhost:9000/health",
            "curl -q -XGET --url=https://example.test/v1 -o-",
            "curl -q --request HEAD --output - https://example.test/",
            "curl -q -H @/tmp/headers --connect-timeout 5 https://example.test/",
            "curl -q -H 'Authorization: Bearer dummy' https://example.test/",
            "curl -q -- https://example.test/a https://example.test/b",
            "cd /tmp && curl -q -sS https://example.test/ | head -10",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "read_only")

    def test_writes_and_unknowns_require_normal_authority_not_a_blanket_allowance(self):
        for suffix in (
            "-X POST", "--request=DELETE", "-XPUT", "-d '{}'", "-G -d x=1",
            "-F file=@secret", "-T secret", "--upload-file secret", "-o result",
            "-O", "--remote-name-all", "--dump-header headers", "--trace trace",
            "--cookie-jar cookies", "--config settings", "-K settings",
            "--next", "--alt-svc cache", "--hsts cache", "--libcurl code.c",
            "--unknown", "--request", "--output", "--header",
        ):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.kind("curl -q https://example.test/ " + suffix), "mutating")
        for command in (
            "curl https://example.test/",  # implicit config is not inspected
            "curl -s -q https://example.test/",  # -q must be first
            "curl -q file:///tmp/local", "curl -q ftp://example.test/",
            "curl -q https://example.test > saved.json",
            "curl -q https://example.test | tee saved.json",
            "curl -q https://example.test && touch saved",
            "curl -q", "curl -q --url=", "curl -q https://[invalid",
            "LD_PRELOAD=evil curl -q https://example.test/",
            "curl -q -H \"$(python3 -c 'print(1)')\" https://example.test/",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "mutating")


if __name__ == "__main__":
    unittest.main()
