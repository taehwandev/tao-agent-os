from __future__ import annotations

import copy
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import test_agent_review_reuse as review_fixture
from agent_commit_ready import prepare_commit
from agent_gate_evidence import reset_gate_evidence_ledger


class CommitReadyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = review_fixture.ReviewReuseTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.session = {"runtime": "codex", "session_id": "commit-session"}
        preflight = json.loads(self.fixture.source.evidence.read_text())
        preflight["runtime_session"] = self.session
        self.fixture.source.evidence.write_text(json.dumps(preflight))
        reset_gate_evidence_ledger(self.fixture.source.evidence, preflight)
        self.registry = self.fixture.project / ".tao" / "run-registry.json"
        self.registry.write_text(json.dumps({"runs": [{
            "run_id": preflight["agent_run_id"], "state": "completed",
        }]}))
        self.fixture.checks.update(code_review_evidence="Exact diff reviewed",
                                   docs_freshness_evidence="Documentation unchanged")
        self.fixture.publish()
        self.fixture.git("add", "--all")
        self.args = copy.copy(self.fixture.source)
        self.args.__dict__.update(command="commit", approved_effect="git_write",
            read_only=False, repair_cycle=0, output=None, evidence=None,
            review_path=[], hook="start", commit_ready=True)
        self.start = Mock(side_effect=self._start)
        self.dispatch = Mock(return_value=0)
        self.session_patch = patch("agent_commit_ready.runtime_session", return_value=self.session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.docs_patch = patch("agent_commit_ready.required_doc_reuse", return_value={"unread": []})
        self.docs_patch.start()
        self.addCleanup(self.docs_patch.stop)
        self.progress_patch = patch("agent_commit_ready._gate_progress", return_value={"remaining_gates": []})
        self.progress_patch.start()
        self.addCleanup(self.progress_patch.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def _start(self, args):
        commit = self.fixture.args("commit", "b" * 32)
        preflight = json.loads(commit.evidence.read_text())
        preflight["route"]["gates"] = ["request intake", "review hook", "commit readiness"]
        commit.evidence.write_text(json.dumps(preflight))
        args.evidence = commit.evidence
        return 0

    def test_single_invocation_runs_existing_checks_in_order_without_git_write(self):
        calls = []
        def dispatch(args):
            calls.append(args.hook)
            if args.hook == "review":
                self.assertEqual("Exact diff reviewed", args.code_review_evidence)
                self.assertEqual("pass", args.review_outcome)
            return 0
        before = self.fixture.git("rev-parse", "HEAD")
        index = self.fixture.git("diff", "--cached")
        self.assertEqual(0, prepare_commit(self.args, self.start, dispatch))
        self.start.assert_called_once()
        self.assertEqual(["review", "gate-batch", "finish"], calls)
        self.assertEqual(before, self.fixture.git("rev-parse", "HEAD"))
        self.assertEqual(index, self.fixture.git("diff", "--cached"))

    def assert_ordinary_entry(self):
        self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_called_once()
        self.assertFalse(self.start.call_args.args[0].commit_ready)
        self.dispatch.assert_not_called()

    def test_external_authority_is_preserved_without_request_phrase_matching(self):
        self.args.approved_effect = "external_write"
        self.args.request = "Carry out the previously agreed outcome"
        self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.assertEqual("external_write", self.start.call_args.args[0].approved_effect)
        self.assertEqual(self.args.request, self.start.call_args.args[0].request)

    def test_local_approval_is_not_widened_by_publication_words(self):
        self.args.request = "commit push PR publish"
        self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.assertEqual("git_write", self.start.call_args.args[0].approved_effect)

    def test_changed_staged_bytes_enter_ordinary_workflow_without_reuse(self):
        (self.fixture.project / "source.py").write_text("changed = True\n")
        self.fixture.git("add", "source.py")
        self.assert_ordinary_entry()

    def test_unrelated_staging_requires_ordinary_review(self):
        (self.fixture.project / "unrelated.py").write_text("other = 1\n")
        self.fixture.git("add", "unrelated.py")
        self.assert_ordinary_entry()

    def test_wrong_session_evidence_is_not_reused(self):
        with patch("agent_commit_ready.runtime_session", return_value={"runtime": "codex", "session_id": "other"}):
            self.assert_ordinary_entry()

    def test_unfinished_source_is_not_reused(self):
        self.registry.write_text(self.registry.read_text().replace("completed", "running"))
        self.assert_ordinary_entry()

    def test_missing_current_approval_refuses_before_start(self):
        self.args.approved_effect = ""
        self.assertEqual(2, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_not_called()

    def test_current_findings_are_not_overridden_by_prior_pass(self):
        self.args.review_outcome = "findings"
        self.assertEqual(2, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_not_called()

    def test_failed_review_never_records_readiness_or_finishes(self):
        self.dispatch.return_value = 1
        self.assertEqual(1, prepare_commit(self.args, self.start, self.dispatch))
        self.dispatch.assert_called_once()
        self.assertEqual("review", self.dispatch.call_args.args[0].hook)

    def test_missing_doc_history_defers_compact_completion_without_failing_entry(self):
        with patch("agent_commit_ready.required_doc_reuse", return_value={"unread": ["new.md"]}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_called_once()
        self.dispatch.assert_not_called()
        self.assertIn("Reuse unchanged readings retained in context", output.getvalue())
        self.assertIn("do not start again", output.getvalue())

    def test_unstaged_entry_explains_staging_and_preserves_the_current_run(self):
        self.fixture.git("reset", "--quiet")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assert_ordinary_entry()
        self.assertIn("stage only the intended files before review", output.getvalue())
        self.assertIn("before --commit-ready", output.getvalue())

    def test_drift_during_start_stops_before_review(self):
        def start(args):
            self._start(args)
            (self.fixture.project / "source.py").write_text("changed = True\n")
            return 0
        self.assertEqual(2, prepare_commit(self.args, start, self.dispatch))
        self.dispatch.assert_not_called()

    def test_altered_review_narrative_is_not_reused(self):
        path = self.fixture.project / ".tao" / "review-checks-latest.json"
        cache = json.loads(path.read_text())
        cache["checks"]["review_input"]["code_review_evidence"] = "Altered narrative"
        path.write_text(json.dumps(cache))
        self.assert_ordinary_entry()

    def test_fallback_start_failure_does_not_run_downstream_checks(self):
        (self.fixture.project / "source.py").write_text("changed = True\n")
        self.fixture.git("add", "source.py")
        self.start.side_effect = None
        self.start.return_value = 1
        self.assertEqual(1, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_called_once()
        self.dispatch.assert_not_called()

    def test_failed_start_prevents_all_dependent_calls(self):
        self.start.side_effect = None
        self.start.return_value = 1
        self.assertEqual(1, prepare_commit(self.args, self.start, self.dispatch))
        self.dispatch.assert_not_called()

    def test_incomplete_ledger_never_attempts_finish(self):
        calls = []
        with patch("agent_commit_ready._gate_progress", return_value={"remaining_gates": ["review hook"]}):
            self.assertEqual(2, prepare_commit(self.args, self.start, lambda args: calls.append(args.hook) or 0))
        self.assertEqual(["review", "gate-batch"], calls)


if __name__ == "__main__":
    unittest.main()
