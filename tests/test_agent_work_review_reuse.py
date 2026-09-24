import json
import unittest

import test_agent_review_reuse as fixture
from agent_gate_evidence import resync_gate_evidence_ledger


class WorkReviewReuseTests(unittest.TestCase):
    setUp = fixture.ReviewReuseTests.setUp
    git = fixture.ReviewReuseTests.git
    args = fixture.ReviewReuseTests.args
    cache = fixture.ReviewReuseTests.cache
    publish = fixture.ReviewReuseTests.publish

    def bind(self, args, work_id, previous):
        payload = json.loads(args.evidence.read_text())
        payload['work'] = {'id': work_id, 'previous_action': previous}
        payload['runtime_session'] = {'runtime': 'codex', 'session_id': 'same'}
        args.evidence.write_text(json.dumps(payload))
        resync_gate_evidence_ledger(args.evidence, payload)

    def test_same_work_reuses_machine_checks_on_any_action_route(self):
        self.bind(self.source, 'a' * 32, '')
        self.publish()
        for command in ('release', 'bugfix', 'refactor'):
            with self.subTest(command=command):
                current = self.args(command, 'b' * 32)
                self.bind(current, 'a' * 32, 'a' * 32)
                self.assertIsNotNone(self.cache(current).load())

    def test_unrelated_work_cannot_reuse_even_identical_source(self):
        self.bind(self.source, 'a' * 32, '')
        self.publish()
        current = self.args('bugfix', 'b' * 32)
        self.bind(current, 'c' * 32, 'c' * 32)
        self.assertIsNone(self.cache(current).load())

    def test_commit_staging_requirement_is_preserved(self):
        self.bind(self.source, 'a' * 32, '')
        self.publish()
        current = self.args('commit', 'b' * 32)
        self.bind(current, 'a' * 32, 'a' * 32)
        self.assertIsNone(self.cache(current).load())
        self.git('add', '--all')
        self.assertIsNotNone(self.cache(current).load())

    def test_changed_code_misses_shared_review_cache(self):
        self.bind(self.source, 'a' * 32, '')
        self.publish()
        current = self.args('bugfix', 'b' * 32)
        self.bind(current, 'a' * 32, 'a' * 32)
        (self.project / 'source.py').write_text('value = 3\n')
        self.assertIsNone(self.cache(current).load())
