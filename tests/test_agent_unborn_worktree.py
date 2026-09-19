"""Initial repository snapshots must work without fabricating a Git commit."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_execution_capsule_state import git_state
from agent_continuation_fields import state_head


class UnbornWorktreeTests(unittest.TestCase):
    def test_initial_staging_and_first_commit_invalidate_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init", "-q", "-b", "main")
            source = root / "source.txt"
            source.write_text("initial\n")
            initial = git_state(root)
            self.assertEqual("unborn", initial["head"])
            failures = []
            state_head(initial["head"], "/head", failures)
            self.assertEqual([], failures)
            self.assertEqual(initial, git_state(root, initial))
            git("add", "source.txt")
            staged = git_state(root)
            source.write_text("changed\n")
            dirty = git_state(root, staged)
            self.assertNotEqual(staged["worktree_fingerprint"], dirty["worktree_fingerprint"])
            git("add", "source.txt")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "initial")
            self.assertNotEqual("unborn", git_state(root, dirty)["head"])

    def test_non_repository_still_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                git_state(Path(folder))

    def test_corrupt_head_is_not_treated_as_empty_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            (root / ".git/refs/heads/main").write_text("a" * 40 + "\n")
            with self.assertRaises(RuntimeError):
                git_state(root)
