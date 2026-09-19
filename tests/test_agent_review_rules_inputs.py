import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_review_rules_inputs import review_rules_inputs


class ReviewRulesInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "project"
        self.rules = Path(self.tmp.name) / "rules"
        for root in (self.project, self.rules):
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            self.write(root, "AGENTS.md", "instructions")
            self.commit(root)

    def write(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self, root):
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)

    def test_unrelated_commits_and_dirty_tests_preserve_inputs(self):
        before = review_rules_inputs(self.project, self.rules)
        self.assertIsNotNone(before)
        self.write(self.rules, "scripts/claude_bash_readonly.py", "admission")
        self.write(self.rules, "tests/test_anything.py", "test")
        self.commit(self.rules)
        self.assertEqual(before, review_rules_inputs(self.project, self.rules))
        self.write(self.rules, "tests/test_anything.py", "new test")
        self.assertEqual(before, review_rules_inputs(self.project, self.rules))

    def test_unknown_code_documents_and_config_invalidate(self):
        for name in ("scripts/agent_review_hook.py", "scripts/new_checker.py",
                     "common/rules.md", "workflow-routes.json", "AGENTS.md"):
            with self.subTest(name=name):
                before = review_rules_inputs(self.project, self.rules)
                self.write(self.rules, name, "changed")
                self.assertNotEqual(before, review_rules_inputs(self.project, self.rules))

    def test_same_repository_and_non_git_do_not_gain_exemption(self):
        self.assertIsNone(review_rules_inputs(self.rules, self.rules))
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        self.assertIsNone(review_rules_inputs(self.project, plain))

    def test_deleted_input_and_symlink_are_not_reused(self):
        before = review_rules_inputs(self.project, self.rules)
        (self.rules / "AGENTS.md").unlink()
        self.assertNotEqual(before, review_rules_inputs(self.project, self.rules))
        (self.rules / "AGENTS.md").symlink_to(self.project / "AGENTS.md")
        self.assertIsNone(review_rules_inputs(self.project, self.rules))
