"""Discovery from a protected checkout must work without admitting writes."""

import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_readonly import bash_command_kind, bash_invocation
from claude_command_effect import command_effect
import claude_pretool_gate as pretool
from support.stable_launcher import stable_launcher_path


class DiscoveryCommandTests(unittest.TestCase):
    def setUp(self):
        self.scripts = Path(__file__).resolve().parents[1] / "scripts"
        self.launcher = shlex.quote(str(stable_launcher_path()))

    def effect(self, command):
        cwd, tokens, simple = bash_invocation(
            {"tool_input": {"command": command}}, Path("/tmp"))
        return command_effect(tokens, simple, bash_command_kind(tokens, simple, cwd))[0]

    def test_trusted_discovery_entrypoints_are_read_only(self):
        for alias in ("project-discover", "agent-entry"):
            script = shlex.quote(str(self.scripts / f"{alias}.py"))
            for prefix in (f"{self.launcher} {alias}", script,
                           f"python3 {script}", f"python3 -B {script}"):
                with self.subTest(prefix=prefix):
                    self.assertEqual("read_only", self.effect(
                        f"{prefix} --request 'new city project' --cwd /tmp "
                        "--search-root /tmp --max-depth 2 --format json"))

    def test_entry_runtime_and_command_are_manifest_hints(self):
        self.assertEqual("read_only", self.effect(
            f"{self.launcher} agent-entry --request=test --runtime=codex --command=task"))

    def test_help_and_documented_switches_are_read_only(self):
        for args in ("--help", "-h", "--request=test --registry=/tmp/projects.json "
                     "--include-default-search-roots --no-default-search-roots"):
            self.assertEqual("read_only", self.effect(
                f"{self.launcher} project-discover {args}"))

    def test_unrecognized_and_incomplete_options_are_not_admitted(self):
        for args in ("--output /tmp/file", "--output=/tmp/file", "--out=/tmp/file",
                     "--write", "--execute", "--request", "--cwd", "extra",
                     "--request x --search-root", "--request x --future-write=yes",
                     "--request x -- --output /tmp/file", "--request x --help=yes"):
            with self.subTest(args=args):
                self.assertNotEqual("read_only", self.effect(
                    f"{self.launcher} project-discover {args}"))

    def test_discovery_does_not_admit_entry_only_flags(self):
        self.assertNotEqual("read_only", self.effect(
            f"{self.launcher} project-discover --request x --runtime codex"))

    def test_untrusted_scripts_and_interpreter_code_remain_unadmitted(self):
        for command in ("python3 /tmp/project-discover.py --request x",
                        "/tmp/agent-entry.py --request x",
                        f"python3 -c {shlex.quote(str(self.scripts / 'project-discover.py'))}",
                        "/tmp/tao-hook project-discover --request x"):
            with self.subTest(command=command):
                self.assertNotEqual("read_only", self.effect(command))

    def test_shell_writes_and_substitutions_remain_unadmitted(self):
        prefix = f"{self.launcher} project-discover --request x"
        for suffix in (" > /project/result", " && touch /project/result", " | tee /project/result",
                       " --cwd $(touch /project/result)"):
            with self.subTest(suffix=suffix):
                self.assertNotEqual("read_only", self.effect(prefix + suffix))

    def test_protected_checkout_allows_lookup_but_still_denies_write(self):
        with tempfile.TemporaryDirectory(dir=self.scripts.parent) as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "AGENTS.md").write_text("Uses tao-hook.\n")
            policy = root / ".agents/shared"
            policy.mkdir(parents=True)
            (policy / "worktree-policy.json").write_text(json.dumps({
                "schema_version": 1, "require_linked_worktree": True,
                "protected_branches": ["main"]}))
            self.assertEqual(root, pretool.find_project_root(root))
            self.assertIsNotNone(pretool.worktree_denial(root))
            for command, allowed in ((
                f"{self.launcher} project-discover --request x --cwd {root}", True),
                (f"touch {root}/owned.txt", False)):
                output = io.StringIO()
                with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}, clear=True), \
                        redirect_stdout(output):
                    pretool.decide({"tool_name": "Bash", "cwd": "/workspace",
                                    "session_id": "discovery-regression",
                                    "tool_input": {"command": command}})
                value = output.getvalue().strip()
                decision = json.loads(value)["hookSpecificOutput"]["permissionDecision"] if value else "allow"
                self.assertEqual("allow" if allowed else "deny", decision)


if __name__ == "__main__":
    unittest.main()
