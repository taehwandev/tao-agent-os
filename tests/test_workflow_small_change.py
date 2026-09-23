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
from workflow_route import ROOT, resolve_docs


class SmallChangeTests(unittest.TestCase):
    def test_compact_manifest_keeps_short_retrospective_after_review(self):
        route = resolve_docs('small-change', None, [])
        self.assertEqual(['tests', 'review hook', 'retrospective check'], route['gates'])
        self.assertFalse(route['missing'])
        self.assertFalse(route['blocking'])
        self.assertTrue(route['skill_feedback']['enabled'])
        self.assertIn('retrospective', str(route['hooks']))
        self.assertEqual(2, len(route['required_docs']))
        self.assertNotIn(
            'workflows/skills/review-and-commit/SKILL.md', route['required_docs']
        )
        self.assertEqual(['start', 'review', 'finish'],
                         [h['hook'] for h in route['hooks'] if h['required']])
        full = resolve_docs('bugfix', None, [])
        self.assertEqual(['tests', 'review hook', 'retrospective check'], full['gates'])
        self.assertIn('scope_change_policy', full)

    def test_compact_start_does_not_require_an_extra_checkpoint(self):
        self.assertEqual([], work_checkpoint_advice(SimpleNamespace(command="small-change")))

    def test_named_routine_concerns_stay_optional_until_evidence_selects_docs(self):
        cases = (
            ('android', ['ui', 'testing']),
            ('ios', ['ui', 'testing']),
            ('web', ['ui', 'verification']),
            (None, ['state', 'error']),
        )
        for platform, concerns in cases:
            with self.subTest(platform=platform, concerns=concerns):
                route = resolve_docs('small-change', platform, concerns)
                self.assertEqual(2, len(route['required_docs']))
                self.assertTrue(route['reference_docs'])

    def test_verified_owner_promotes_only_its_specific_surface_contract(self):
        route = resolve_docs(
            'small-change',
            'android',
            ['ui', 'testing'],
            surface_paths=[
                'feature/example/src/main/kotlin/com/example/ui/ProfileScreen.kt'
            ],
        )

        required = route['required_docs']
        self.assertGreater(len(required), 2)
        self.assertIn(
            'platforms/android/skills/android-compose-ui/references/current-guidance.md',
            required,
        )
        self.assertNotIn(
            'common/skills/testing/references/current-guidance.md', required
        )
        self.assertNotIn(
            'platforms/android/skills/android-external-skill-source-coverage/'
            'references/current-guidance.md',
            required,
        )

    def test_reported_android_input_case_drops_broad_concern_bundle(self):
        route = resolve_docs(
            'small-change',
            'android',
            ['ui', 'testing'],
            request_text=(
                '경력에 글자수 초과하는 글 복붙 안됨 -> 복붙은 되고, '
                '초과 시 오류 표시되게 수정 필요'
            ),
        )

        required = route['required_docs']
        required_bytes = sum((ROOT / path).stat().st_size for path in required)
        self.assertEqual(2, len(required))
        self.assertLess(required_bytes, 20_000)

    def test_risky_concerns_require_full_route(self):
        for concern in ('auth', 'api', 'security', 'architecture', 'deployment'):
            with self.subTest(concern=concern):
                self.assertTrue(resolve_docs('small-change', None, [concern])['blocking'])

    def test_approved_commit_stays_within_compact_route(self):
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
            if effect == 'git_write':
                self.assertEqual([], failures)
            else:
                self.assertTrue(any('only local Git writes' in item for item in failures))
        self.assertTrue(effect_decision('small-change', envelope, tool_effect='git_write',
                                        **binding))

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
