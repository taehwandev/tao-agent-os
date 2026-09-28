"""A new project can obtain its first directory without granting project writes."""
from contextlib import redirect_stdout
from pathlib import Path
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_readonly import bash_command_kind, bash_invocation
import claude_pretool_gate as pretool


class ProjectBootstrapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name).resolve()
        (self.workspace / "AGENTS.md").write_text(
            "<!-- BEGIN MANAGED TAO AGENT OS WORKSPACE GUARD -->\n")
        self.target = self.workspace / "new-city"

    def kind(self, command):
        cwd, tokens, simple = bash_invocation(
            {"tool_input": {"command": command}}, self.workspace)
        return bash_command_kind(tokens, simple, cwd)

    def test_new_direct_child_directory_is_bootstrap(self):
        for prefix in ("mkdir", "mkdir -p"):
            self.assertEqual("bootstrap", self.kind(f"{prefix} {shlex.quote(str(self.target))}"))
        self.assertFalse(self.target.exists())

    def test_existing_projects_and_hidden_paths_are_not_bootstrap(self):
        self.target.mkdir()
        for target in (self.target, self.workspace / ".git"):
            self.assertEqual("mutating", self.kind(f"mkdir -p {target}"))

    def test_symlink_is_not_bootstrap_but_unmarked_location_is(self):
        self.target.symlink_to(self.workspace / "absent")
        self.assertEqual("mutating", self.kind(f"mkdir -p {self.target}"))
        (self.workspace / "AGENTS.md").write_text("Ordinary project instructions")
        self.assertEqual("bootstrap", self.kind(f"mkdir -p {self.workspace}/another"))

    def test_recursive_and_aliased_non_project_locations_are_bootstrap(self):
        (self.workspace / "AGENTS.md").unlink()
        self.assertEqual("bootstrap", self.kind(f"mkdir -p {self.workspace}/deep/new/project"))
        self.assertEqual("mutating", self.kind(f"mkdir {self.workspace}/deep/new/project"))
        alias = self.workspace / "alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        self.assertEqual("bootstrap", self.kind(f"mkdir {alias}/aliased-project"))

    def test_recursive_creation_cannot_enter_an_existing_git_project(self):
        existing = self.workspace / "existing"
        existing.mkdir()
        (existing / ".git").mkdir()
        self.assertEqual("mutating", self.kind(f"mkdir -p {existing}/deep/new/project"))
        alias = self.workspace / "existing-alias"
        alias.symlink_to(existing, target_is_directory=True)
        self.assertEqual("mutating", self.kind(f"mkdir -p {alias}/new-project"))

    def test_existing_checkout_does_not_block_explicit_external_project(self):
        (self.workspace / "AGENTS.md").unlink()
        protected = self.workspace / "protected"
        protected.mkdir()
        subprocess.run(["git", "init", "-q", str(protected)], check=True)
        (protected / "AGENTS.md").write_text("Uses tao-hook.\n")
        policy = protected / ".agents/shared"
        policy.mkdir(parents=True)
        (policy / "worktree-policy.json").write_text(json.dumps({
            "schema_version": 1, "require_linked_worktree": True,
            "protected_branches": ["main"]}))
        self.assertIsNotNone(pretool.worktree_denial(protected))
        with patch.object(pretool, "throwaway_checkout", return_value=False):
            self.assertIn(protected, pretool._edit_target_roots([(protected / "file.txt", True)]))
        external = self.workspace / "external"
        for command, expected, launcher in (
            (f"mkdir {external}", "allow", protected),
            (f"touch {external}/file.txt", "allow", protected),
            (f"touch {protected}/file.txt", "deny", self.workspace),
            (f"touch {protected}/file.txt", "deny", protected),
        ):
            if expected == "deny":
                with patch.object(pretool, "throwaway_checkout", return_value=False):
                    scope = pretool._call_scope(
                        {"tool_input": {"command": command}}, "Bash", launcher)
                    self.assertIn(protected, scope.roots)
            output = io.StringIO()
            with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}, clear=True), \
                    patch.object(pretool, "throwaway_checkout", return_value=False), redirect_stdout(output):
                pretool.decide({"tool_name": "Bash", "cwd": str(launcher),
                                "session_id": "location-independent-projects",
                                "tool_input": {"command": command}})
            value = output.getvalue().strip()
            decision = json.loads(value)["hookSpecificOutput"]["permissionDecision"] if value else "allow"
            self.assertEqual(expected, decision, command)
            if expected == "allow":
                subprocess.run(shlex.split(command), check=True)
        self.assertTrue((external / "file.txt").is_file())
        for command in (
            f"cd {external} && touch another.txt",
            f"cd {external} && printf content > another.txt",
        ):
            output = io.StringIO()
            with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}, clear=True), \
                    patch.object(pretool, "throwaway_checkout", return_value=False), redirect_stdout(output):
                pretool.decide({"tool_name": "Bash", "cwd": str(protected),
                                "session_id": "location-independent-projects",
                                "tool_input": {"command": command}})
            self.assertEqual("", output.getvalue().strip(), command)
        alias = external / "protected-link.txt"
        alias.symlink_to(protected / "file.txt")
        output = io.StringIO()
        with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}, clear=True), \
                patch.object(pretool, "throwaway_checkout", return_value=False), redirect_stdout(output):
            pretool.decide({"tool_name": "Bash", "cwd": str(self.workspace),
                            "session_id": "location-independent-projects",
                            "tool_input": {"command": f"touch {alias}"}})
        self.assertEqual("deny", json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"])

    def test_git_checkouts_keep_their_write_protection(self):
        (self.workspace / ".git").mkdir()
        self.assertEqual("mutating", self.kind(f"mkdir -p {self.target}"))

    def test_options_multiple_targets_and_chained_writes_stay_mutating(self):
        for command in (f"mkdir -m 777 {self.target}", f"mkdir {self.target} {self.workspace}/other",
                        f"mkdir -p {self.target} && touch {self.target}/code.py"):
            self.assertEqual("mutating", self.kind(command))


if __name__ == "__main__":
    unittest.main()
