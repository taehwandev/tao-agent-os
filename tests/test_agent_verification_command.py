import tempfile
import unittest
from pathlib import Path

from tests import test_agent_gate_reuse as fixture
from agent_verification_command import resolve_verification_target, verification_target_is_changed


class VerificationTargetTests(unittest.TestCase):
    def test_nested_project_change_is_checked_in_its_own_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory).resolve()
            project = rules / '.tao' / 'worktrees' / 'task'
            project.mkdir(parents=True)
            git = fixture.GateEvidenceReuseTests.git
            for root in (rules, project):
                git(root, 'init', '-q')
                (root / '.gitignore').write_text('.tao/\n')
            target = project / 'owner.py'
            target.write_text('VALUE = 1\n')
            resolved = resolve_verification_target(project, rules, 'owner.py')
            self.assertEqual((target, 'project', 'owner.py', project), resolved)
            self.assertTrue(verification_target_is_changed(project, target))
            self.assertFalse(verification_target_is_changed(rules, target))

    def test_same_root_keeps_rules_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'owner.py').write_text('VALUE = 1\n')
            self.assertEqual('rules', resolve_verification_target(root, root, 'owner.py')[1])
