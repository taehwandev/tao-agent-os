from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import claude_pretool_gate as gate
from agent_evidence_inputs import EvidenceInputs
from agent_publication_admission import PublicationAdmission


class PublicationHoldTests(unittest.TestCase):
    def test_real_gate_holds_then_releases_the_same_publication(self):
        from tests.test_claude_pretool_gate import (
            PublicationWaitsForFinishTests, _attest_finished_publication, _reason,
            resolve_runtime_evidence, transition_run,
        )
        fixture = PublicationWaitsForFinishTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture._open_project(Path(tmp))
            policy_path = root / gate.WORKTREE_POLICY_PATH
            policy = json.loads(policy_path.read_text())
            policy['publication_commands'] = [{
                'argv_prefix': ['gh', 'workflow', 'run', 'release.yml'], 'publishes': True,
            }]
            policy_path.write_text(json.dumps(policy))
            commands = (
                'gh release create v1 --verify-tag --notes-file /tmp/notes.md',
                'gh api --method POST repos/owner/repo/releases -f tag_name=v1',
                'gh api repos/owner/repo/actions/runs/42/pending_deployments -f state=approved',
                'gh workflow run release.yml',
            )
            for command in commands:
                self.assertIn('still open', _reason(fixture._decide(root, command)[1]))
            evidence = resolve_runtime_evidence(root, {'runtime': 'claude', 'session_id': fixture.SESSION})
            transition_run(root, evidence, 'completed')
            _attest_finished_publication(root, evidence)
            for command in commands:
                self.assertIn('a successful finish', _reason(fixture._decide(root, command)[1]))

    def test_release_uses_same_publication_boundary_in_all_command_forms(self):
        for command in (
            'gh release create v1 --verify-tag --notes-file /tmp/notes.md',
            'gh release upload v1 artifact.tgz',
            'gh api --method POST repos/owner/repo/releases -f tag_name=v1',
            'gh api repos/owner/repo/actions/runs/42/pending_deployments -f state=approved',
            'env gh release create v1',
            'bash -lc "gh release create v1"',
            'gh release create v1 && gh release view v1',
        ):
            with self.subTest(command=command):
                self.assertEqual('publishes', gate.publication_hold(command))

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

    def finish(self, effect='external_write', failure_reason=None):
        self.evidence.write_text(json.dumps({
            'rules': str(self.root),
            'route': {'request_classification': {'intent_envelope': {
                'authority': 'envelope', 'schema_valid': True,
                'failures': [], 'effective_effect': effect,
            }}},
        }))
        return PublicationAdmission.record_finish(self.root, self.evidence, failure_reason)

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

    def test_large_repository_keeps_publication_bound_to_finished_bytes(self):
        files = self.root / 'files'
        files.mkdir()
        for index in range(5_001):
            (files / f'{index:04d}.txt').write_text('reviewed')

        with self.assertRaisesRegex(ValueError, 'input snapshot exceeds file limit'):
            EvidenceInputs.capture(self.root, [])
        self.assertTrue(self.finish())
        self.assertTrue(self.allowed())
        (files / '0000.txt').write_text('changed after finish')
        self.assertFalse(self.allowed())

    def test_publication_budget_failure_is_reported_without_a_receipt(self):
        reasons = []
        with patch.object(PublicationAdmission, '_MAX_FILES', 1):
            self.assertFalse(self.finish('git_write', reasons))
        self.assertEqual(['input snapshot exceeds file limit'], reasons)
        self.assertFalse(self.evidence.with_name('publication.json').exists())

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

    def test_release_after_commit_needs_no_new_lifecycle(self):
        (self.root / 'source').write_text('reviewed change')
        self.finish()
        self.git('add', '.')
        self.git('commit', '-qm', 'release')
        with patch.object(gate, 'finished_session_evidence', return_value=self.evidence):
            command = 'gh release create v1 --verify-tag --notes-file /tmp/notes.md'
            self.assertTrue(gate.publishes_finished_command(self.root, 'session', command, self.root))
            self.assertFalse(gate.publishes_finished_command(self.root, 'session', command + ' && touch extra', self.root))
            self.finish('git_write')
            self.assertFalse(gate.publishes_finished_command(self.root, 'session', command, self.root))
            self.finish()
            (self.root / 'source').write_text('unreviewed change')
            self.assertFalse(gate.publishes_finished_command(self.root, 'session', command, self.root))
