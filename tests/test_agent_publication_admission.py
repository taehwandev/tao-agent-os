from pathlib import Path
from argparse import Namespace
import importlib.util
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
from agent_route_state import request_fingerprint
from agent_run_registry import register_run, transition_run


def _agent_hook():
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'agent-hook.py'
    spec = importlib.util.spec_from_file_location('publication_repeat_hook', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_real_gate_names_the_missing_effect_for_a_git_write_run(self):
        """A commit-only run's push refusal says which effect is missing and how to declare it."""
        from tests.test_claude_pretool_gate import (
            PublicationWaitsForFinishTests, _attest_finished_publication, _reason,
            resolve_runtime_evidence, transition_run,
        )
        fixture = PublicationWaitsForFinishTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture._open_project(Path(tmp))
            evidence = resolve_runtime_evidence(root, {'runtime': 'claude', 'session_id': fixture.SESSION})
            transition_run(root, evidence, 'completed')
            _attest_finished_publication(root, evidence, effect='git_write')
            reason = _reason(fixture._decide(root, 'git push origin work')[1])
        self.assertIn('admitted for git_write and this publication needs external_write', reason)
        self.assertIn('--approved-effect external_write', reason)
        self.assertNotIn('may be missing', reason)


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

    def test_same_finished_request_does_not_start_a_second_publication_run(self):
        request = '커밋+pr 해줘. 플립에 설치해주고'
        intake = {'request': request, 'continuation_scope': '',
                  'request_classified': False, 'classification_evidence': ''}
        session = {'runtime': 'codex', 'session_id': 'publication-session'}
        evidence = self.root / '.tao' / 'preflight.json'
        evidence.write_text(json.dumps({
            'project': str(self.root), 'rules': str(self.root),
            'request_fingerprint': request_fingerprint(intake),
            'runtime_session': session,
            'route': {'command': 'commit', 'request_classification': {
                'intent_envelope': {'authority': 'envelope', 'schema_valid': True,
                                    'failures': [], 'effective_effect': 'external_write'},
            }},
        }))
        run = register_run(self.root, evidence, {'command': 'commit'}, intake)
        transition_run(self.root, evidence, 'completed', run_id=run['run_id'])
        self.assertTrue(PublicationAdmission.record_finish(self.root, evidence))

        hook = _agent_hook()
        args = Namespace(
            project=self.root, rules=self.root, command='commit', request=request,
            continuation_scope='', request_classified=False,
            classification_evidence='', read_only=False, output=None,
            repair_cycle=0, approved_effect='external_write',
        )
        results = []
        def record(_hook, success, details, *_args, **_kwargs):
            results.append((success, details))
            return 0 if success else 1

        with (patch.object(hook, 'runtime_session', return_value=session),
              patch.object(hook, 'finish_with_result', side_effect=record),
              patch.object(hook, '_start_admitted_action', side_effect=AssertionError('second preflight'))):
            hook.start_hook(args)
        self.assertEqual(1, len(results))
        self.assertFalse(results[0][0])
        self.assertIn('completed, unchanged publication receipt', ' '.join(results[0][1]))

        with (patch.object(hook, 'runtime_session', return_value={
                  'runtime': 'codex', 'session_id': 'another-session',
              }),
              patch.object(hook, '_start_admitted_action', side_effect=AssertionError('fresh preflight'))):
            with self.assertRaisesRegex(AssertionError, 'fresh preflight'):
                hook.start_hook(args)

        # A new request, a stronger effect, and changed source each need fresh admission.
        for changed_request, changed_effect, change_source in (
            (request + ' 새 작업', 'external_write', False),
            (request, 'destructive', False),
            (request, 'external_write', True),
        ):
            if change_source:
                (self.root / 'source').write_text('new bytes')
            args.request = changed_request
            args.approved_effect = changed_effect
            with (patch.object(hook, 'runtime_session', return_value=session),
                  patch.object(hook, '_start_admitted_action', side_effect=AssertionError('fresh preflight'))):
                with self.assertRaisesRegex(AssertionError, 'fresh preflight'):
                    hook.start_hook(args)

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

    def refusal(self, effect='external_write'):
        return PublicationAdmission.refusal(self.root, self.evidence, effect)

    def test_refusal_names_the_first_failed_check_and_matches_allows(self):
        self.assertEqual('missing_receipt', self.refusal())
        self.finish('git_write')
        self.assertEqual('', self.refusal('git_write'))
        self.assertEqual('effect:git_write<external_write', self.refusal())
        self.finish()
        (self.root / 'source').write_text('unreviewed')
        self.assertEqual('project_changed', self.refusal())
        (self.root / 'source').write_text('original')
        self.assertEqual('', self.refusal())
        self.evidence.write_text('{}')
        self.assertEqual('foreign_receipt', self.refusal())
        self.evidence.with_name('publication.json').write_text('not json')
        self.assertEqual('unreadable_receipt', self.refusal())
        for effect in ('git_write', 'external_write'):
            self.assertEqual(self.allowed(effect), self.refusal(effect) == '')
        self.finish()
        self.evidence.unlink()
        self.assertEqual('unverifiable_receipt', self.refusal())
        self.assertFalse(self.allowed())

    def test_denial_names_each_cause_instead_of_every_possibility(self):
        with patch.object(gate, 'finished_session_evidence', return_value=self.evidence):
            deny = lambda command: gate.finished_publication_denial(self.root, 'session', command, self.root)
            self.finish('git_write')
            self.assertIn('admitted for git_write and this publication needs external_write', deny('git push'))
            self.finish()
            (self.root / 'source').write_text('unreviewed')
            self.assertIn('project files changed after finish', deny('git push'))
            (self.root / 'source').write_text('original')
            self.assertIn('not a lone admissible publication', deny('git push && touch extra'))

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
