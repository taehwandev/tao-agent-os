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
        self.progress_patch = patch("agent_commit_ready._gate_progress", return_value={"remaining_gates": ["commit readiness"]})
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

    def publish_pathspec(self, paths, scope="pathspec"):
        self.fixture.source.review_scope = self.args.review_scope = scope
        self.args.review_path = list(paths)
        checks = copy.deepcopy(self.fixture.checks)
        checks["review_scope"] = "pathspec: " + ", ".join(paths)
        checks["review_paths"] = list(paths)
        names = self.fixture.git("diff", "--name-only", "-z", "--no-renames", "HEAD", "--", *paths)
        names += self.fixture.git("ls-files", "--others", "--exclude-standard", "-z", "--", *paths)
        reviewed = sorted({name.decode() for name in names.split(b"\0") if name})
        checks["changed_path_count"] = len(reviewed)
        checks["structure_review"].update(checked_paths=reviewed, checked_path_count=len(reviewed))
        source = review_fixture.ReviewReuse(self.fixture.source, list(paths), {"kind": "working-tree"})
        failures = []
        source.complete(checks, failures)
        self.assertEqual([], failures)
        review_fixture.record_review_gate(self.fixture.source, checks)
        source.publish(checks)

    def test_public_literal_pathspec_scope_reuses_the_exact_completed_review(self):
        self.publish_pathspec(["source.py", "extra.py"], scope="pathspec")
        path = self.fixture.project / ".tao" / "review-checks-latest.json"
        self.assertEqual("pathspec", json.loads(path.read_text())["snapshot"]["scope"])
        calls = []

        def dispatch(args):
            self.assertEqual("pathspec", args.review_scope)
            calls.append(args.hook)
            return 0

        self.assertEqual(0, prepare_commit(self.args, self.start, dispatch))
        self.assertEqual(["review", "finish"], calls)

    def test_same_paths_cannot_replace_the_completed_review_scope(self):
        self.publish_pathspec(["source.py", "extra.py"])
        for scope in ("working-tree", "commit-range", "local-config", "repo-hygiene"):
            with self.subTest(scope=scope):
                self.start.reset_mock()
                self.dispatch.reset_mock()
                self.args.review_scope = scope
                self.assert_ordinary_entry()

    def test_exact_pathspec_reuses_with_unchanged_unrelated_unstaged_files(self):
        (self.fixture.project / "rule.md").write_text("unrelated unstaged change\n")
        self.publish_pathspec(["source.py", "extra.py"])
        before = self.fixture.git("diff")
        calls = []
        self.assertEqual(0, prepare_commit(self.args, self.start, lambda args: calls.append(args.hook) or 0))
        self.assertEqual(["review", "finish"], calls)
        self.assertEqual(before, self.fixture.git("diff"))

    def test_exact_pathspec_reuses_with_unchanged_unrelated_untracked_files(self):
        outside = self.fixture.project / "unrelated.txt"
        outside.write_text("outside the reviewed staged unit\n")
        self.publish_pathspec(["source.py", "extra.py"])
        self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.assertEqual(2, self.dispatch.call_count)
        self.assertEqual("outside the reviewed staged unit\n", outside.read_text())

    def test_pathspec_review_requires_selected_changed_files_to_be_staged(self):
        self.fixture.git("reset", "--quiet", "--", "source.py")
        self.publish_pathspec(["source.py", "extra.py"])
        self.assert_ordinary_entry()

    def test_pathspec_review_requires_selected_untracked_files_to_be_staged(self):
        (self.fixture.project / "untracked.py").write_text("selected = True\n")
        self.publish_pathspec(["*.py"])
        self.assert_ordinary_entry()

    def test_pathspec_reuse_still_rejects_unrelated_unstaged_byte_drift(self):
        outside = self.fixture.project / "rule.md"
        outside.write_text("outside bytes before review\n")
        self.publish_pathspec(["source.py", "extra.py"])
        outside.write_text("outside bytes changed after review\n")
        self.assert_ordinary_entry()

    def test_index_coverage_drift_stops_before_each_dependent_hook(self):
        self.publish_pathspec(["source.py", "extra.py"])
        for phase in ("start", "review"):
            with self.subTest(phase=phase):
                self.fixture.git("add", "source.py")
                calls = []

                def start(args):
                    self._start(args)
                    if phase == "start":
                        self.fixture.git("reset", "--quiet", "--", "source.py")
                    return 0

                def dispatch(args):
                    calls.append(args.hook)
                    self.fixture.git("reset", "--quiet", "--", "source.py")
                    return 0

                self.assertEqual(2, prepare_commit(self.args, start, dispatch))
                self.assertEqual([] if phase == "start" else ["review"], calls)

    def test_exact_pathspec_covering_all_staged_files_reuses_completed_review(self):
        self.publish_pathspec(["source.py", "extra.py"])
        before = self.fixture.git("rev-parse", "HEAD")
        index = self.fixture.git("diff", "--cached")
        calls = []

        def dispatch(args):
            calls.append(args.hook)
            self.assertEqual(["source.py", "extra.py"], args.review_path)
            self.assertEqual("Exact diff reviewed", args.code_review_evidence)
            return 0

        self.assertEqual(0, prepare_commit(self.args, self.start, dispatch))
        self.start.assert_called_once()
        self.assertEqual(["review", "finish"], calls)
        self.assertEqual(before, self.fixture.git("rev-parse", "HEAD"))
        self.assertEqual(index, self.fixture.git("diff", "--cached"))

    def test_exact_141_path_review_reuses_without_repeating_entry(self):
        directory = self.fixture.project / "reviewed"
        directory.mkdir()
        paths = ["source.py", "extra.py"]
        for index in range(139):
            path = f"reviewed/unit_{index}.py"
            (self.fixture.project / path).write_text(f"value = {index}\n")
            paths.append(path)
        self.fixture.git("add", "reviewed")
        self.fixture.source.max_changed_paths = self.args.max_changed_paths = 141
        self.publish_pathspec(paths)
        calls = []
        self.assertEqual(0, prepare_commit(self.args, self.start, lambda args: calls.append(args.hook) or 0))
        self.start.assert_called_once()
        self.assertEqual(["review", "finish"], calls)

    def test_matching_git_pathspec_can_cover_the_complete_staged_unit(self):
        self.publish_pathspec(["*.py"])
        self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.assertEqual(2, self.dispatch.call_count)

    def test_matching_pathspec_cannot_reuse_with_existing_unreviewed_staged_file(self):
        self.publish_pathspec(["source.py"])
        self.assert_ordinary_entry()

    def test_matching_pathspec_cannot_reuse_with_new_unreviewed_staged_file(self):
        self.publish_pathspec(["*.py"])
        (self.fixture.project / "unreviewed.txt").write_text("outside reviewed scope\n")
        self.fixture.git("add", "unreviewed.txt")
        self.assert_ordinary_entry()

    def test_changed_expanded_or_removed_pathspecs_are_not_equivalent_reviews(self):
        self.publish_pathspec(["source.py", "extra.py"])
        for paths in ([], ["*.py"], ["extra.py", "source.py"], ["source.py", "extra.py", "rule.md"]):
            with self.subTest(paths=paths):
                self.start.reset_mock()
                self.dispatch.reset_mock()
                self.args.review_path = paths
                self.assert_ordinary_entry()

    def test_whole_tree_proof_cannot_be_reinterpreted_as_a_pathspec_review(self):
        self.args.review_path = ["source.py", "extra.py"]
        self.assert_ordinary_entry()

    def test_pathspec_review_does_not_cover_changed_staged_bytes(self):
        self.publish_pathspec(["source.py", "extra.py"])
        (self.fixture.project / "source.py").write_text("value = 3\n")
        self.fixture.git("add", "source.py")
        self.assert_ordinary_entry()

    def test_pathspec_review_requires_identical_checker_limits(self):
        self.publish_pathspec(["source.py", "extra.py"])
        self.args.max_changed_paths += 1
        self.assert_ordinary_entry()

    def test_pathspec_review_rejects_changed_rule_or_checker_proof(self):
        self.publish_pathspec(["source.py", "extra.py"])
        path = self.fixture.project / ".tao" / "review-checks-latest.json"
        original = json.loads(path.read_text())
        for field in ("rules_sha256", "checker_sha256"):
            with self.subTest(field=field):
                self.start.reset_mock()
                self.dispatch.reset_mock()
                cache = copy.deepcopy(original)
                cache["snapshot"][field] = "0" * 64
                path.write_text(json.dumps(cache))
                self.assert_ordinary_entry()

    def test_pathspec_review_requires_the_same_session_and_completed_run(self):
        self.publish_pathspec(["source.py", "extra.py"])
        with patch("agent_commit_ready.runtime_session", return_value={"runtime": "codex", "session_id": "other"}):
            self.assert_ordinary_entry()
        for state in ("running", "cancelled"):
            with self.subTest(state=state):
                self.start.reset_mock()
                self.dispatch.reset_mock()
                self.registry.write_text(json.dumps({"runs": [{"run_id": "a" * 32, "state": state}]}))
                self.assert_ordinary_entry()

    def test_pathspec_review_cannot_override_current_findings_or_missing_approval(self):
        self.publish_pathspec(["source.py", "extra.py"])
        for field, value in (("review_outcome", "findings"), ("approved_effect", "")):
            with self.subTest(field=field):
                previous = getattr(self.args, field, "")
                setattr(self.args, field, value)
                self.assertEqual(2, prepare_commit(self.args, self.start, self.dispatch))
                self.start.assert_not_called()
                self.dispatch.assert_not_called()
                setattr(self.args, field, previous)

    def test_pathspec_review_still_defers_completion_for_unread_required_docs(self):
        self.publish_pathspec(["source.py", "extra.py"])
        with patch("agent_commit_ready.required_doc_reuse", return_value={"unread": ["new.md"]}):
            self.assertEqual(0, prepare_commit(self.args, self.start, self.dispatch))
        self.start.assert_called_once()
        self.dispatch.assert_not_called()

    def test_pathspec_review_narrative_tampering_prevents_reuse(self):
        self.publish_pathspec(["source.py", "extra.py"])
        path = self.fixture.project / ".tao" / "review-checks-latest.json"
        cache = json.loads(path.read_text())
        cache["checks"]["review_input"]["code_review_evidence"] = "Changed review statement"
        path.write_text(json.dumps(cache))
        self.assert_ordinary_entry()

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
        self.assertEqual(["review", "finish"], calls)
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
        self.assertEqual(["review"], calls)


if __name__ == "__main__":
    unittest.main()
