"""Exact local context grammar without an exemption for arbitrary writes."""

import sys
import unittest
import tempfile
import shlex
import subprocess
import os
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_local_context_commands import local_context_kind
from claude_bash_readonly import bash_invocation, bash_command_kind


class LocalContextCommandTests(unittest.TestCase):
    def test_only_installed_label_mode_is_exempt_without_a_run(self):
        from tests.test_claude_pretool_gate import _opt_in_project, _decide, _require_linked_worktree
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)), \
                patch.dict(os.environ, {"TAO_ALLOW_MAIN_CHECKOUT_EDIT": "0"}):
            home = Path(directory)
            helper = home / "Library/Application Support/Spill/adapters/setup/spill-token-metering-setup.mjs"
            helper.parent.mkdir(parents=True)
            helper.write_text("// fixture: classifier must never execute it\n")
            project = _opt_in_project(home)
            _require_linked_worktree(project)
            subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "baseline"], check=True)
            args = ["node", str(helper), "--label", "codex", "--task-type", "testing", "--stage", "verify", "--if-absent"]
            valid = shlex.join(args)
            invalid = [
                shlex.join(args + ["--label-file", str(project / "out")]),
                shlex.join(args + ["--label", "claude"]),
                shlex.join(["node", "-r", "evil.js", *args[1:]]),
                shlex.join(["./node", *args[1:]]),
                shlex.join(["node", str(helper)]),
                valid + " && touch extra", valid + " > out",
                shlex.join(["node", str(project / helper.name), *args[2:]]),
            ]
            for command in [valid, *invalid]:
                with self.subTest(command=command):
                    _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, project)
                    kind = bash_command_kind(tokens, simple)
                    self.assertEqual(command == valid, kind == "runtime_control")
                    payload = {"tool_name": "Bash", "cwd": str(project), "session_id": "label-test",
                               "tool_input": {"command": command}}
                    _, output = _decide(payload)
                    if command == valid:
                        self.assertEqual("", output)
                    else:
                        # Preserve normal admission (including native permission
                        # deferral on main); invalid syntax gets no new exemption.
                        with patch("claude_bash_readonly.spill_label_kind", return_value=None):
                            self.assertEqual(_decide(payload)[1], output)

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
