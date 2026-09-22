from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import claude_pretool_gate as gate
from agent_publication_admission import PublicationAdmission


class PublicationHoldTests(unittest.TestCase):
    def test_pr_creation_is_publication_in_plain_and_wrapped_commands(self):
        for command in ('gh pr create --fill', 'env gh pr create --fill',
                        'bash -lc "gh pr create --fill"', 'gh pr create --fill && echo done'):
            with self.subTest(command=command):
                self.assertEqual('publishes', gate.publication_hold(command))

    def test_pr_reads_remain_reads(self):
        self.assertEqual('', gate.publication_hold('gh pr view 1'))


class PublicationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / '.gitignore').write_text('.tao/\n')
        (self.root / 'source').write_text('original')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.evidence = self.root / '.tao/runs/example/preflight.json'
        self.evidence.parent.mkdir(parents=True)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def finish(self, effect='external_write'):
        self.evidence.write_text(json.dumps({
            'rules': str(self.root),
            'route': {'request_classification': {'intent_envelope': {
                'authority': 'envelope', 'schema_valid': True,
                'failures': [], 'effective_effect': effect,
            }}},
        }))
        return PublicationAdmission.record_finish(self.root, self.evidence)

    def allowed(self, effect='external_write'):
        return PublicationAdmission.allows(self.root, self.evidence, effect)

    def test_git_write_finish_never_authorizes_external_publication(self):
        self.assertTrue(self.finish('git_write'))
        self.assertTrue(self.allowed('git_write'))
        self.assertFalse(self.allowed())

    def test_edit_after_finish_refuses_publication(self):
        self.assertTrue(self.finish())
        (self.root / 'source').write_text('new bytes')
        self.assertFalse(self.allowed())

    def test_identical_content_commit_and_repeated_checks_remain_admissible(self):
        (self.root / 'source').write_text('reviewed change')
        self.assertTrue(self.finish())
        self.git('add', '.')
        self.git('commit', '-qm', 'reviewed')
        self.assertTrue(self.allowed())
        self.assertTrue(self.allowed())

    def test_missing_receipt_and_changed_evidence_fail_closed(self):
        self.assertFalse(self.allowed())
        self.finish()
        self.evidence.write_text('{}')
        self.assertFalse(self.allowed())

    def test_read_finish_does_not_create_publication_authority(self):
        self.assertFalse(self.finish('read'))
        self.assertFalse(self.allowed())

    def test_gate_applies_effect_and_content_admission_after_finish_lookup(self):
        self.finish('git_write')
        with patch.object(gate, 'finished_session_evidence', return_value=self.evidence):
            self.assertTrue(gate.publishes_finished_work(self.root, 'session', ['git', 'commit', '-m', 'done']))
            self.assertFalse(gate.publishes_finished_work(self.root, 'session', ['git', 'push']))
            self.assertFalse(gate.publishes_finished_work(self.root, 'session', ['gh', 'pr', 'create']))
            self.finish()
            self.assertTrue(gate.publishes_finished_work(self.root, 'session', ['gh', 'pr', 'create']))
            (self.root / 'source').write_text('unreviewed')
            self.assertFalse(gate.publishes_finished_work(self.root, 'session', ['git', 'push']))
