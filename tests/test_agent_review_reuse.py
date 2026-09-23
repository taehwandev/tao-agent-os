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
        rules = getattr(self, 'rules', self.project)
        preflight = {'agent_run_id': run_id, 'project': str(self.project), 'rules': str(rules),
                     'route': {'command': command, 'gates': ['review hook']}}
        evidence.write_text(json.dumps(preflight))
        reset_gate_evidence_ledger(evidence, preflight)
        return SimpleNamespace(project=self.project, rules=rules, evidence=evidence,
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

    def integration(self):
        self.rules = self.project / '.tao' / 'separate-rules'
        self.rules.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.rules)], check=True)
        subprocess.run(['git', '-C', str(self.rules), '-c', 'user.name=Test', '-c',
                        'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'rules'], check=True)
        self.source = self.args('review', 'a' * 32)
        source = self.publish()
        base = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('add', '--all')
        self.git('commit', '-qm', 'reviewed unit')
        head = self.git('rev-parse', 'HEAD').decode().strip()
        target = self.project / '.tao' / 'integration'
        self.git('worktree', 'add', '--detach', str(target), head)
        self.project = target
        args = self.args('commit', 'b' * 32)
        args.review_scope = 'commit-range'
        return source, ReviewReuse(args, ['extra.py', 'source.py'],
                                   {'kind': 'commit-range', 'base_sha': base, 'head_sha': head})

    def test_exact_committed_integration_reuses_original_attestation(self):
        source, target = self.integration()
        self.assertIsNotNone(target.before)
        self.assertEqual(self.checks['structure_review'], target.load()['structure_review'])
        self.assertEqual(ReviewReuse.read(source.path)['attestation_id'], target.reused['attestation_id'])
        checks = dict(self.checks, review_subject=target.subject, review_paths=target.paths,
                      review_scope=f"commit-range: {target.subject['base_sha']}..{target.subject['head_sha']}")
        failures = []
        target.complete(checks, failures)
        self.assertEqual([], failures)
        record_review_gate(target.args, checks)
        receipt = ReviewReuse.read(ReviewAttestation.path(target.args.evidence))
        self.assertEqual(target.reused['attestation_id'], receipt['review_checks']['source_attestation'])

    def test_integration_rejects_amended_bytes_even_with_same_parent(self):
        _, target = self.integration()
        (self.project / 'source.py').write_text('value = 3\n')
        self.git('add', 'source.py')
        self.git('commit', '--amend', '--no-edit', '-q')
        target.subject['head_sha'] = self.git('rev-parse', 'HEAD').decode().strip()
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).load())

    def test_integration_rejects_dirty_target_changed_limits_and_tampered_receipt(self):
        source, target = self.integration()
        target.args.max_function_lines += 1
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).load())
        target.args.max_function_lines -= 1
        (self.project / 'source.py').write_text('value = 99\n')
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).before)
        self.git('restore', 'source.py')
        cached = ReviewReuse.read(source.path)
        cached['checks']['workflow_validate']['stdout'] = 'forged'
        source.path.write_text(json.dumps(cached))
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).load())

    def test_integration_rejects_new_commit_and_changed_rules(self):
        _, target = self.integration()
        (self.rules / 'new-rule.md').write_text('new rule')
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).load())
        (self.rules / 'new-rule.md').unlink()
        self.git('commit', '--allow-empty', '-qm', 'another unit')
        self.assertIsNone(ReviewReuse(target.args, target.paths, target.subject).before)

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

    def test_publication_candidate_is_available_before_staging_and_fails_on_drift(self):
        source = self.publish()
        args = self.args('commit', 'b' * 32)

        candidate = ReviewReuse.publication_candidate(args.evidence)

        self.assertEqual(
            ['extra.py', 'source.py'],
            candidate['changed_paths'],
        )
        self.assertEqual(source.reused, None)
        (self.project / 'source.py').write_text('value = 99\n')
        self.assertIsNone(ReviewReuse.publication_candidate(args.evidence))

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
        self.assertEqual(['files', 'rules_sha256'], self.checks['review_snapshot_stability']['changed_fields'])

    def test_stability_capture_rereads_only_the_reviewed_files(self):
        """Settled rules and checker bytes are read once per review, not twice."""
        original = Path.read_bytes
        reads = []

        def recording(path):
            reads.append(path.name)
            return original(path)

        with patch('agent_review_reuse.RACY_WINDOW_NS', 0):
            cache = self.cache()
            with patch.object(Path, 'read_bytes', recording):
                failures = []
                cache.complete(self.checks, failures)
        self.assertEqual([], failures)
        self.assertIn('review_checks', self.checks)
        self.assertEqual(['extra.py', 'source.py'], sorted(reads))

    def test_same_size_rewrite_with_restored_mtime_still_changes_the_snapshot(self):
        rule = self.project / 'rule.md'
        with patch('agent_review_reuse.RACY_WINDOW_NS', 0):
            cache = self.cache()
            before = rule.stat()
            rule.write_text('review ruleX\n')
            os.utime(rule, ns=(before.st_atime_ns, before.st_mtime_ns))
            if rule.stat().st_ctime_ns == before.st_ctime_ns:
                self.skipTest('filesystem ctime is too coarse to observe this rewrite')
            failures = []
            cache.complete(self.checks, failures)
        self.assertIn('reviewed bytes changed', failures[0])
        self.assertIn('rules_sha256', self.checks['review_snapshot_stability']['changed_fields'])

    def test_attestation_revalidates_the_validation_states_instead_of_recapturing(self):
        from agent_execution_capsule_state import git_states_for_paths
        from agent_finish_final_checks import record_successful_review_workflow_validation

        states = record_successful_review_workflow_validation(
            self.project, self.project, self.source.evidence,
            {'returncode': 0}, {'returncode': 0}, 'working-tree')
        self.assertEqual(git_states_for_paths(self.project, self.project), states)
        with patch('agent_review_attestation.git_states_for_paths', wraps=git_states_for_paths) as capture:
            record_review_gate(self.source, self.checks, states)
        self.assertEqual({'project_record': states[0], 'rules_record': states[1]}, capture.call_args.kwargs)
        attestation = json.loads(ReviewAttestation.path(self.source.evidence).read_text())
        self.assertEqual(states, (attestation['project_git'], attestation['rules_git']))

        with patch('agent_review_attestation.git_states_for_paths', wraps=git_states_for_paths) as capture:
            record_review_gate(self.source, self.checks, object())
        self.assertEqual({'project_record': None, 'rules_record': None}, capture.call_args.kwargs)

    def test_symlinked_parent_matches_the_ancestor_predicate_it_replaced(self):
        from agent_review_reuse import _symlinked_parent

        def replaced(root, path):
            return any(parent.is_symlink() for parent in (path.parent, *path.parent.parents)
                       if parent != root and root in parent.parents)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real = base / 'real' / 'root'
            (real / 'd1' / 'd2').mkdir(parents=True)
            for name in ('top.txt', 'd1/f1', 'd1/d2/f'):
                (real / name).write_text('x\n')
            (real / 'link1').symlink_to('d1', target_is_directory=True)
            (real / 'd1' / 'link2').symlink_to('d2', target_is_directory=True)
            (base / 'alias').symlink_to(base / 'real', target_is_directory=True)
            relatives = ('top.txt', 'd1/f1', 'd1/d2/f', 'link1/f1', 'link1/d2/f', 'd1/link2/f')
            outcomes = []
            for root in (real, base / 'alias' / 'root'):
                for relative in relatives:
                    expected = replaced(root, root / relative)
                    self.assertEqual(expected, _symlinked_parent(root, root / relative), (root, relative))
                    outcomes.append(expected)
        self.assertEqual({True, False}, set(outcomes))

    def test_recently_changed_files_are_never_memoized(self):
        cache = self.cache()
        self.assertFalse([key for key in cache.hash_memo if key[0].startswith(str(self.project))])

    def test_unavailable_snapshot_remains_fail_closed_with_bounded_diagnostic(self):
        cache = self.cache()
        failures = []
        with patch.object(cache, 'capture', return_value=None):
            cache.complete(self.checks, failures)
        self.assertEqual(['reviewed bytes changed while the review hook was running'], failures)
        self.assertEqual({'status': 'FAIL', 'snapshot_available': False, 'changed_fields': []},
                         self.checks['review_snapshot_stability'])
        self.assertNotIn('review_checks', self.checks)

    def test_rules_only_drift_is_distinguished_without_exposing_content(self):
        cache = self.cache()
        after = dict(cache.before, rules_sha256='changed')
        failures = []
        with patch.object(cache, 'capture', return_value=after):
            cache.complete(self.checks, failures)
        self.assertEqual(['rules_sha256'], self.checks['review_snapshot_stability']['changed_fields'])
        self.assertNotIn('review_checks', self.checks)
        self.assertEqual(1, len(failures))

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
