"""Canonical skill maintenance in the runtime repository's linked worktree."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_skill_maintenance import _target_scope_is_allowed


class CanonicalWorktreeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rules = Path(self.temp.name) / "rules"
        self.rules.mkdir()
        self.relative = "common/skills/example/references/current-guidance.md"
        target = self.rules / self.relative
        target.parent.mkdir(parents=True)
        target.write_text("guidance\n")
        (target.parent.parent / "SKILL.md").write_text("skill\n")
        for args in (
            ("init", "-q"), ("add", "."),
            ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture"),
        ):
            self.git(self.rules, *args)
        self.project = Path(self.temp.name) / "task"
        self.git(self.rules, "worktree", "add", "-qb", "task", str(self.project))

    def git(self, root, *args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    def allowed(self, project=None, relative=None):
        project = project or self.project
        relative = relative or self.relative
        return _target_scope_is_allowed(
            project=project, rules=self.rules, target_path=project / relative,
            target_scope="project", target_relative=relative, promotion_target="example",
        )

    def test_canonical_linked_worktree_is_allowed(self):
        self.assertTrue(self.allowed())

    def test_foreign_repository_with_identical_bundle_is_refused(self):
        foreign = Path(self.temp.name) / "foreign"
        foreign.mkdir()
        self.git(foreign, "init", "-q")
        target = foreign / self.relative
        target.parent.mkdir(parents=True)
        target.write_text("guidance\n")
        (target.parent.parent / "SKILL.md").write_text("skill\n")
        self.assertFalse(self.allowed(foreign))

    def test_subdirectory_and_noncanonical_paths_are_refused(self):
        self.assertFalse(self.allowed(self.project / "common"))
        self.assertFalse(self.allowed(relative="vendor/skills/example/SKILL.md"))

    def test_missing_canonical_rules_bundle_is_refused(self):
        (self.rules / "common/skills/example/SKILL.md").unlink()
        self.assertFalse(self.allowed())

    def test_symlink_escape_is_refused(self):
        target = self.project / self.relative
        target.unlink()
        target.symlink_to(self.rules / self.relative)
        self.assertFalse(self.allowed())


if __name__ == "__main__":
    unittest.main()
