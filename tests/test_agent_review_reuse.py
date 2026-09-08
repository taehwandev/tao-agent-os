from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from agent_gate_evidence import gate_evidence_path_for_preflight, reset_gate_evidence_ledger
from agent_review_attestation import ReviewAttestation, _record_shape_failures
from agent_review_hook import _run_review_checks, record_review_gate
from agent_review_reuse import ReviewReuse


class ReviewReuseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'review@example.invalid')
        self.git('config', 'user.name', 'Review Test')
        (self.project / '.gitignore').write_text('.tao/\n')
        (self.project / 'source.py').write_text('value = 1\n')
        (self.project / 'rule.md').write_text('review rules\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        (self.project / 'source.py').write_text('value = 2\n')
        (self.project / 'extra.py').write_text('extra = 1\n')
        self.source = self.args('review', 'a' * 32)
        self.checks = {
            'review_outcome': 'pass', 'review_scope': 'working-tree', 'review_paths': [],
            'review_subject': {'kind': 'working-tree'}, 'changed_path_count': 2,
            'structure_review': {'failures': [], 'warnings': [], 'checked_path_count': 2,
                                 'checked_paths': ['source.py', 'extra.py'], 'scope': 'changed files'},
            'workflow_validate': {'returncode': 0, 'stdout': 'machine validation passed'},
            'diff_check': {'returncode': 0}, 'vibeguard': {'returncode': 0, 'overall': 'Ready'},
        }

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def args(self, command, run_id):
        evidence = self.project / '.tao' / 'runs' / run_id / 'preflight.json'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        preflight = {'agent_run_id': run_id, 'project': str(self.project), 'rules': str(self.project),
                     'route': {'command': command, 'gates': ['review hook']}}
        evidence.write_text(json.dumps(preflight))
        reset_gate_evidence_ledger(evidence, preflight)
        return SimpleNamespace(project=self.project, rules=self.project, evidence=evidence,
                               review_scope='working-tree', max_source_file_lines=500,
                               max_function_lines=120, max_added_lines=300, max_changed_paths=25,
                               structure_review_evidence='', side_effect_audit_evidence='')

    def cache(self, args=None, paths=None):
        return ReviewReuse(args or self.source, paths or [], {'kind': 'working-tree'})

    def publish(self):
        source = self.cache()
        self.assertIsNotNone(source.before)
        failures = []
        source.complete(self.checks, failures)
        self.assertEqual([], failures)
        record_review_gate(self.source, self.checks)
        source.publish(self.checks)
        return source

    def staged_commit(self):
        self.git('add', '--all')
        return self.args('commit', 'b' * 32)

    def test_wholly_unstaged_source_reuses_after_full_staging_and_records_provenance(self):
        source = self.publish()
        commit = self.cache(self.staged_commit())
        self.assertEqual(source.before, commit.before)
        results = commit.load()
        self.assertEqual(self.checks['structure_review'], results['structure_review'])
        checks = dict(self.checks)
        failures = []
        commit.complete(checks, failures)
        record_review_gate(commit.args, checks)
        attestation = ReviewReuse.read(ReviewAttestation.path(commit.args.evidence))
        self.assertEqual([], _record_shape_failures(attestation))
        self.assertEqual(commit.reused['attestation_id'], attestation['review_checks']['source_attestation'])
        self.assertNotIn('tests', attestation['review_checks'])

    def test_publication_does_not_recapture_and_late_edits_still_miss(self):
        source = self.cache()
        failures = []
        source.complete(self.checks, failures)
        self.assertEqual([], failures)
        record_review_gate(self.source, self.checks)
        (self.project / 'source.py').write_text('value = 99\n')
        with patch.object(source, 'capture', side_effect=AssertionError('redundant capture')):
            source.publish(self.checks)
        self.assertTrue(source.path.is_file())
        self.assertIsNone(self.cache(self.staged_commit()).load())

    def test_unstaged_and_partially_staged_file_sets_miss(self):
        self.publish()
        args = self.args('commit', 'b' * 32)
        self.assertIsNone(self.cache(args).load())
        self.git('add', 'source.py')
        self.assertIsNone(self.cache(args).load())

    def test_partial_staged_bytes_and_staged_delete_recreation_miss(self):
        self.publish()
        args = self.staged_commit()
        (self.project / 'source.py').write_text('value = 3\n')
        self.git('add', 'source.py')
        (self.project / 'source.py').write_text('value = 2\n')
        self.assertIsNone(self.cache(args).before)
        self.git('rm', '-f', '--cached', 'source.py')
        self.assertIsNone(self.cache(args).before)

    def test_changed_bytes_modes_deletion_or_rules_miss(self):
        self.publish()
        args = self.staged_commit()
        (self.project / 'source.py').write_text('value = 3\n')
        self.git('add', 'source.py')
        self.assertIsNone(self.cache(args).load())
        (self.project / 'source.py').write_text('value = 2\n')
        os.chmod(self.project / 'source.py', 0o755)
        self.git('add', 'source.py')
        self.assertIsNone(self.cache(args).load())
        os.chmod(self.project / 'source.py', 0o644)
        self.git('add', 'source.py')
        (self.project / 'extra.py').unlink()
        self.git('add', '--all')
        self.assertIsNone(self.cache(args).load())
        (self.project / 'extra.py').write_text('extra = 1\n')
        (self.project / 'rule.md').write_text('changed rules\n')
        self.git('add', '--all')
        self.assertIsNone(self.cache(args).load())

    def test_threshold_scope_head_and_noncommit_route_miss(self):
        self.publish()
        args = self.staged_commit()
        args.max_function_lines += 1
        self.assertIsNone(self.cache(args).load())
        args.max_function_lines -= 1
        self.assertIsNone(self.cache(args, ['source.py']).load())
        self.assertIsNone(self.cache(self.source).load())
        self.git('commit', '-qm', 'new head')
        self.assertIsNone(self.cache(args).load())

    def test_missing_or_tampered_machine_proof_misses(self):
        source = self.publish()
        args = self.staged_commit()
        cache = ReviewReuse.read(source.path)
        tampered = json.loads(json.dumps(cache))
        tampered['checks']['workflow_validate']['stdout'] = 'caller-authored pass'
        source.path.write_text(json.dumps(tampered))
        self.assertIsNone(self.cache(args).load())
        source.path.write_text(json.dumps(cache))
        ledger_path = gate_evidence_path_for_preflight(self.source.evidence)
        ledger = ReviewReuse.read(ledger_path)
        ledger['entries'][-1]['source'] = 'manual'
        ledger_path.write_text(json.dumps(ledger))
        self.assertIsNone(self.cache(args).load())
        ReviewAttestation.path(self.source.evidence).unlink()
        self.assertIsNone(self.cache(args).load())

    def test_changed_bytes_during_review_cannot_make_receipt(self):
        cache = self.cache()
        (self.project / 'source.py').write_text('value = 3\n')
        failures = []
        cache.complete(self.checks, failures)
        self.assertIn('reviewed bytes changed', failures[0])
        self.assertNotIn('review_checks', self.checks)

    def test_symlink_target_changes_cannot_reuse_review(self):
        self.publish()
        args = self.staged_commit()
        target = self.project / '.tao' / 'target.py'
        target.write_text('value = 2\n')
        source = self.project / 'source.py'
        source.unlink()
        source.symlink_to(target)
        self.git('add', 'source.py')
        self.assertIsNone(self.cache(args).before)
        target.write_text('value = 99\n')
        self.assertIsNone(self.cache(args).load())

    def test_rules_alias_file_and_directory_bind_ignored_target_contents(self):
        targets = self.project / '.tao' / 'skills'
        targets.mkdir(parents=True)
        (targets / 'rule.md').write_text('rule one\n')
        package = targets / 'package'
        package.mkdir()
        (package / 'guide.md').write_text('guide one\n')
        (self.project / 'rule-alias.md').symlink_to(targets / 'rule.md')
        (self.project / 'skill-alias').symlink_to(package, target_is_directory=True)
        self.git('add', 'rule-alias.md', 'skill-alias')
        self.git('commit', '-qm', 'installed rule aliases')
        self.publish()
        args = self.staged_commit()
        self.assertIsNotNone(self.cache(args).load())
        (targets / 'rule.md').write_text('rule two\n')
        self.assertIsNone(self.cache(args).load())
        (targets / 'rule.md').write_text('rule one\n')
        self.assertIsNotNone(self.cache(args).load())
        (package / 'guide.md').write_text('guide two\n')
        self.assertIsNone(self.cache(args).load())

    def test_rules_alias_rejects_foreign_and_nested_symlink_targets(self):
        target = self.project / '.tao' / 'package'
        target.mkdir(parents=True)
        (target / 'nested').symlink_to(self.project / 'rule.md')
        alias = self.project / 'skill-alias'
        alias.symlink_to(target, target_is_directory=True)
        self.git('add', 'skill-alias')
        self.git('commit', '-qm', 'installed rule alias')
        self.assertIsNone(self.cache().before)
        alias.unlink()
        alias.symlink_to(self.project.parent, target_is_directory=True)
        self.assertIsNone(self.cache().before)

    def test_optional_cache_io_falls_back(self):
        source = self.publish()
        args = self.staged_commit()
        with patch.object(ReviewReuse, 'read', side_effect=OSError('unavailable')):
            self.assertIsNone(self.cache(args).load())
        with patch('agent_review_reuse.atomic_write_json', side_effect=OSError('unavailable')):
            source.publish(self.checks)

    def test_reuse_skips_only_costly_checks_and_keeps_fresh_checks(self):
        self.publish()
        args = self.staged_commit()
        reused = self.cache(args).load()
        checks, failures, commands = {}, [], []
        def runner(command, project):
            commands.append(command)
            return {'returncode': 1 if '--cached' in command else 0}
        with (
            patch('agent_review_hook.structure_review') as structure,
            patch('agent_review_hook.record_review_workflow_validation') as workflow,
            patch('agent_review_hook.record_review_base_drift') as base,
            patch('agent_review_hook.record_review_vibeguard') as audit,
            patch('agent_review_hook.record_review_worktree_stability') as stability,
        ):
            _run_review_checks(args, checks, failures, runner, lambda p: ({}, []), lambda p, r: [], lambda s: '',
                               review_paths=[], review_subject={'kind': 'working-tree'}, review_scope='working-tree',
                               status_before={'returncode': 0}, status_before_lines=['M source.py'],
                               full_status_before_lines=['M source.py'], local_config_scope=False, reused_checks=reused)
        structure.assert_not_called()
        workflow.assert_not_called()
        base.assert_called_once()
        audit.assert_called_once()
        stability.assert_called_once()
        self.assertIn('git diff --cached --check failed', failures)
        self.assertEqual(2, len(commands))


if __name__ == '__main__':
    unittest.main()
