from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

import agent_run_interruption as boundary
import claude_stop_gate
import codex_stop_gate
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_claim import claim_resume
from agent_continuation_resume import resume_list
from agent_continuation_store import continuation_path
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import active_runs, register_run, registry_path, transition_run
from test_agent_continuation_checkpoint import initialize_git


class Run:
    def __init__(self, directory: str, runtime: str = 'codex', version=2, packet=False):
        self.project = Path(directory) / 'project'
        self.project.mkdir()
        (self.project / 'AGENTS.md').write_text('uses tao\n')
        (self.project / 'source.txt').write_text('before\n')
        if packet:
            initialize_git(self.project)
        self.route = {'command': 'task', 'gates': ['scope', 'verify'], 'required_docs': []}
        if version is not None:
            self.route['lifecycle_version'] = version
        self.intake = {'request': 'bounded local work', 'request_classified': False}
        self.evidence = self.project / '.tao' / 'runs' / uuid.uuid4().hex / 'preflight.json'
        self.evidence.parent.mkdir(parents=True)
        self.run = register_run(self.project, self.evidence, self.route, self.intake)
        self.session = {'runtime': runtime, 'session_id': 'bound-session'}
        self.binding = {
            'project': str(self.project), 'rules': str(self.project),
            'route': self.route, 'request_intake': self.intake, 'runtime_session': self.session,
            'execution_snapshot': {
                'schema_version': PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                'route_fingerprint': route_fingerprint(self.route),
                'request_fingerprint': request_fingerprint(self.intake), 'required_docs': [],
            },
        }
        self.evidence.write_text(json.dumps(self.binding))

    def checkpoint(self, phase='acting'):
        return write_continuation_checkpoint(
            project=self.project, rules=self.project, run_id=self.run['run_id'],
            kind='initial', binding_path=self.evidence, phase=phase,
            work={'objective': 'bounded local work', 'blockers': ['external outcome unresolved'] if phase == 'blocked' else []},
        )

    def state(self):
        return json.loads(registry_path(self.project).read_text())['runs'][-1]['state']

    def stop(self):
        return boundary.record_turn_boundary(self.project, **self.session)


class RunInterruptionTests(unittest.TestCase):
    def test_both_adapters_end_without_closeout_or_success_receipts(self):
        for runtime, adapter in [('codex', codex_stop_gate), ('claude', claude_stop_gate)]:
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as directory:
                run = Run(directory, runtime)
                output = io.StringIO()
                with patch.object(adapter, 'find_project_root', return_value=run.project), redirect_stdout(output):
                    self.assertEqual(0, adapter.decide({'cwd': str(run.project), 'session_id': 'bound-session'}))
                    self.assertEqual(0, adapter.decide({'cwd': str(run.project), 'session_id': 'bound-session', 'stop_hook_active': True}))
                self.assertEqual('', output.getvalue())
                self.assertEqual('interrupted', run.state())
                self.assertEqual([], active_runs(run.project))
                self.assertFalse(list((run.project / '.tao').rglob('finish.json')))
                self.assertFalse(list((run.project / '.tao').rglob('*.finished')))

    def test_no_run_stop_creates_no_state(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertFalse(boundary.record_turn_boundary(project, 'claude', 'session'))
            self.assertFalse((project / '.tao').exists())

    def test_foreign_session_and_unknown_versions_do_not_write(self):
        for version in [None, 1, 99, '2', True]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                run = Run(directory, version=version)
                before = registry_path(run.project).read_bytes()
                self.assertFalse(boundary.record_turn_boundary(run.project, 'claude', 'bound-session', run.evidence))
                self.assertFalse(boundary.record_turn_boundary(run.project, 'codex', 'foreign-session', run.evidence))
                handled = run.stop()
                self.assertEqual(version not in (None, 1) or type(version) is bool, handled)
                self.assertEqual(before, registry_path(run.project).read_bytes())

    def test_lock_and_write_failure_allow_turn_without_false_outcome(self):
        for failed_call in ['project_state_lock', 'atomic_write_json']:
            with self.subTest(call=failed_call), tempfile.TemporaryDirectory() as directory:
                run = Run(directory)
                before = registry_path(run.project).read_bytes()
                with patch.object(boundary, failed_call, side_effect=OSError('unavailable')):
                    self.assertTrue(run.stop())
                self.assertEqual(before, registry_path(run.project).read_bytes())
                self.assertEqual('running', run.state())

    def test_trusted_blocked_checkpoint_is_retained_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, packet=True)
            run.checkpoint('blocked')
            packet = continuation_path(run.project, run.run['run_id'])
            before = packet.read_bytes()
            self.assertTrue(run.stop())
            self.assertEqual('blocked', run.state())
            self.assertEqual(before, packet.read_bytes())
            self.assertTrue(run.stop())
            self.assertEqual('blocked', run.state())

    def test_exact_stopped_session_resumes_after_drift_check(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, packet=True)
            run.checkpoint()
            run.stop()
            with patch('agent_continuation_claim.runtime_session', return_value=run.session):
                self.assertEqual('free', resume_list(run.project)['entries'][0]['holder'])
                result = claim_resume(run.project, run.run['run_id'], expected_generation=0)
            self.assertEqual('ready', result['result'])
            self.assertEqual('running', run.state())
            self.assertEqual('acting', result['packet']['phase'])

    def test_resuming_blocked_work_preserves_unresolved_external_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, packet=True)
            run.checkpoint('blocked')
            run.stop()
            with patch('agent_continuation_claim.runtime_session', return_value=run.session):
                result = claim_resume(run.project, run.run['run_id'], expected_generation=0)
            self.assertEqual('ready', result['result'])
            self.assertEqual('blocked', result['packet']['phase'])
            self.assertEqual(['external outcome unresolved'], result['packet']['work']['blockers'])
            self.assertFalse(list((run.project / '.tao').rglob('finish.json')))

    def test_stopped_session_cannot_bypass_foreign_owner_or_drift(self):
        for foreign in [True, False]:
            with self.subTest(foreign=foreign), tempfile.TemporaryDirectory() as directory:
                run = Run(directory, packet=True)
                run.checkpoint('blocked')
                before = continuation_path(run.project, run.run['run_id']).read_bytes()
                run.stop()
                session = dict(run.session, session_id='foreign') if foreign else run.session
                if not foreign:
                    (run.project / 'source.txt').write_text('changed\n')
                with patch('agent_continuation_claim.runtime_session', return_value=session):
                    result = claim_resume(run.project, run.run['run_id'], expected_generation=0)
                self.assertEqual('live_owner_refused' if foreign else 'drift_refused', result['result'])
                self.assertEqual(before, continuation_path(run.project, run.run['run_id']).read_bytes())

    def test_unknown_version_resume_refuses_without_registry_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, version=99, packet=True)
            run.checkpoint()
            before = registry_path(run.project).read_bytes()
            result = claim_resume(run.project, run.run['run_id'], expected_generation=0)
            self.assertEqual('unsupported_lifecycle', result['result'])
            self.assertEqual(before, registry_path(run.project).read_bytes())

    def test_completed_record_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            transition_run(run.project, run.evidence, 'completed')
            before = registry_path(run.project).read_bytes()
            self.assertFalse(run.stop())
            self.assertEqual(before, registry_path(run.project).read_bytes())

    def test_newer_terminal_binding_suppresses_older_active_record(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            path = registry_path(run.project)
            registry = json.loads(path.read_text())
            registry['runs'].append(dict(registry['runs'][0], run_id=uuid.uuid4().hex, state='completed'))
            path.write_text(json.dumps(registry))
            before = path.read_bytes()
            self.assertFalse(run.stop())
            self.assertEqual(before, path.read_bytes())

    def test_known_versioned_evidence_allows_stop_on_registry_read_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            with patch.object(boundary, 'read_registry_state', side_effect=OSError('unavailable')):
                self.assertTrue(boundary.record_turn_boundary(run.project, **run.session, evidence=run.evidence))
            self.assertEqual('running', run.state())

    def test_version_is_bound_without_changing_legacy_fingerprint(self):
        import hashlib
        route = {'command': 'task', 'gates': []}
        legacy = {'command': 'task', 'platform': None, 'concerns': [], 'docs': [], 'required_docs': [], 'reference_docs': [], 'gates': []}
        expected = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(expected, route_fingerprint(route))
        self.assertNotEqual(expected, route_fingerprint(dict(route, lifecycle_version=2)))


if __name__ == '__main__':
    unittest.main()
