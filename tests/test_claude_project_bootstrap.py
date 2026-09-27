"""A new project can obtain its first directory without granting project writes."""
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_readonly import bash_command_kind, bash_invocation


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
        for target in (self.target, self.workspace / ".git", self.workspace / "a/b"):
            self.assertEqual("mutating", self.kind(f"mkdir -p {target}"))

    def test_symlink_and_unmarked_workspace_are_not_bootstrap(self):
        self.target.symlink_to(self.workspace / "absent")
        self.assertEqual("mutating", self.kind(f"mkdir -p {self.target}"))
        (self.workspace / "AGENTS.md").write_text("Ordinary project instructions")
        self.assertEqual("mutating", self.kind(f"mkdir -p {self.workspace}/another"))

    def test_git_checkouts_keep_their_write_protection(self):
        (self.workspace / ".git").mkdir()
        self.assertEqual("mutating", self.kind(f"mkdir -p {self.target}"))

    def test_options_multiple_targets_and_chained_writes_stay_mutating(self):
        for command in (f"mkdir -m 777 {self.target}", f"mkdir {self.target} {self.workspace}/other",
                        f"mkdir -p {self.target} && touch {self.target}/code.py"):
            self.assertEqual("mutating", self.kind(command))


if __name__ == "__main__":
    unittest.main()
