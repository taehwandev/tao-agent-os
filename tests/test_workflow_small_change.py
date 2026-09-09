"""Bounded work keeps verification without inheriting the full ceremony."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_hook_continuation import work_checkpoint_advice
from agent_review_hook import record_review_prerequisite_readiness
from workflow_effect_policy import effect_decision
from workflow_route import resolve_docs


class SmallChangeTests(unittest.TestCase):
    def test_compact_manifest_keeps_scope_sources_tests_and_review(self):
        route = resolve_docs('small-change', None, [])
        self.assertEqual(['request intake', 'work surface resolution', 'source docs',
                          'tests', 'review hook'], route['gates'])
        self.assertFalse(route['missing'])
        self.assertFalse(route['blocking'])
        self.assertFalse(route['skill_feedback']['enabled'])
        self.assertNotIn('retrospective', str(route['hooks']))
        self.assertEqual(3, len(route['required_docs']))
        self.assertEqual(['start', 'review', 'finish'],
                         [h['hook'] for h in route['hooks'] if h['required']])
        full = resolve_docs('bugfix', None, [])
        self.assertIn('reproduce', full['gates'])
        self.assertIn('cycle contract', full['gates'])
        self.assertIn('side-effect audit', full['gates'])
        self.assertGreater(len(full['gates']), len(route['gates']))

    def test_compact_start_does_not_require_an_extra_checkpoint(self):
        self.assertEqual([], work_checkpoint_advice(SimpleNamespace(command="small-change")))

    def test_risky_concerns_require_full_route(self):
        for concern in ('auth', 'api', 'security', 'architecture', 'deployment'):
            with self.subTest(concern=concern):
                self.assertTrue(resolve_docs('small-change', None, [concern])['blocking'])

    def test_approval_cannot_expand_compact_route_to_publication(self):
        envelope = dict(schema_version=1, request_fingerprint='a' * 64,
                        runtime_session_id='session-opaque-01', mode='work', intent='edit',
                        target_summary='existing local owner', requested_effects=['local_write'],
                        ambiguity='resolved')
        binding = dict(request_fingerprint=envelope['request_fingerprint'],
                       runtime_session_id='session-opaque-01')
        self.assertEqual([], effect_decision('small-change', envelope, **binding))
        for effect in ('git_write', 'external_write', 'destructive'):
            approval = dict(request_fingerprint=envelope['request_fingerprint'],
                            target_summary=envelope['target_summary'], effect=effect,
                            command='small-change')
            failures = effect_decision('small-change', envelope, tool_effect=effect,
                                       approval=approval, **binding)
            self.assertTrue(any('only local writes' in item for item in failures))

    def test_review_caller_cannot_raise_four_file_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / 'preflight.json'
            for command, limit in (('small-change', 4), ('bugfix', 100)):
                evidence.write_text(json.dumps({'route': {'command': command, 'gates': []}}))
                args = SimpleNamespace(evidence=evidence, project=root, rules=root,
                                       max_changed_paths=100)
                record_review_prerequisite_readiness(args, {}, [])
                self.assertEqual(limit, args.max_changed_paths)
