"""Exercise compact preparation through real CLI boundaries in disposable Git."""
import json
import sys
import unittest

import test_claude_pretool_execution as fixture_module


class CommitReadyExecutionTests(unittest.TestCase):
    def test_completed_review_to_commit_ready_without_committing(self):
        self._exercise_preparation("git_write")

    def test_external_scope_reuses_review_and_falls_back_on_changed_bytes(self):
        self._exercise_preparation("external_write")

    def test_commit_route_finishes_after_review_without_a_readiness_gate_call(self):
        """66 of 66 observed commit runs spent a fifth hook call on this gate."""
        fixture, invoke, source = self._commit_route_fixture()
        started = invoke("start", "--command", "commit", "--request", "Commit the fixture",
                         "--intent", "commit_fixture", "--target-summary", "Disposable fixture",
                         "--approved-effect", "git_write")
        self.assertIn("finish derives commit readiness", started)
        self._review(invoke)
        # A manual review-hook record is accepted and ignored, never an error.
        ignored = invoke("gate-batch", "--gate-record", json.dumps({
            "gate": "review hook", "evidence": "review passed"}))
        self.assertIn("ignored", ignored)
        finished = invoke("finish")
        self.assertIn("commit readiness: derived", finished)

    def test_bytes_changed_after_review_still_require_commit_readiness(self):
        fixture, invoke, source = self._commit_route_fixture()
        invoke("start", "--command", "commit", "--request", "Commit the fixture",
               "--intent", "commit_fixture", "--target-summary", "Disposable fixture",
               "--approved-effect", "git_write")
        self._review(invoke)
        source.write_text("changed after review\n")
        fixture.run_command(["git", "add", "answer.txt"], check=True)
        finished = invoke("finish", expect=1)
        self.assertNotIn("commit readiness: derived", finished)
        self.assertIn("commit readiness", finished)

    def _commit_route_fixture(self):
        fixture = fixture_module.PretoolExecutionTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.project / ".gitignore").write_text((fixture_module.ROOT / ".gitignore").read_text())
        (fixture.project / "VIBEGUARD.md").write_text((fixture_module.ROOT / "VIBEGUARD.md").read_text())
        fixture.run_command(["git", "add", ".gitignore", "VIBEGUARD.md"], check=True)
        fixture.run_command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                             "commit", "-qm", "fixture policy"], check=True)
        source = fixture.project / "answer.txt"
        source.write_text("verified fixture\n")
        fixture.run_command(["git", "add", "answer.txt"], check=True)
        base = [sys.executable, str(fixture_module.ROOT / "scripts/agent-hook.py")]
        common = ["--project", str(fixture.project), "--rules", str(fixture_module.ROOT)]

        def invoke(hook, *arguments, expect=0):
            result = fixture.run_command(base + [hook] + common + list(arguments))
            self.assertEqual(expect, result.returncode, result.stdout + result.stderr)
            return result.stdout

        return fixture, invoke, source

    def _review(self, invoke):
        invoke("review", "--review-outcome", "pass",
               "--code-review-evidence", "Reviewed the staged disposable answer file",
               "--docs-freshness-evidence", "Fixture has no documentation contract",
               "--structure-review-evidence", "One text fixture; no runtime owner added")

    def _exercise_preparation(self, effect):
        fixture = fixture_module.PretoolExecutionTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Match the repository's existing local-secret exclusions; no installer
        # or audit exception is needed for this disposable integration target.
        (fixture.project / ".gitignore").write_text((fixture_module.ROOT / ".gitignore").read_text())
        (fixture.project / "VIBEGUARD.md").write_text((fixture_module.ROOT / "VIBEGUARD.md").read_text())
        fixture.run_command(["git", "add", ".gitignore", "VIBEGUARD.md"], check=True)
        fixture.run_command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                             "commit", "-qm", "fixture policy"], check=True)
        fixture.start()
        evidence = next((fixture.project / ".tao/runs").glob("*/preflight.json"))
        source = fixture.project / "answer.txt"
        source.write_text("verified fixture\n")
        base = [sys.executable, str(fixture_module.ROOT / "scripts/agent-hook.py")]
        common = ["--project", str(fixture.project), "--rules", str(fixture_module.ROOT)]

        def invoke(hook, *arguments, explicit=True):
            command = base + [hook] + common
            if explicit:
                command += ["--evidence", str(evidence)]
            result = fixture.run_command(command + list(arguments))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return result.stdout

        self.assertEqual("verified fixture\n", source.read_text())
        invoke("gate-batch", "--gate-record", json.dumps({"gate": "tests",
            "evidence": "Disposable fixture output read and asserted successfully",
            "fields": {"check": "Fixture output assertion", "result": "1 test; 0 failures"}}),
            "--gate-record", json.dumps({"gate": "retrospective check",
                "evidence": "Fixture lifecycle follows the existing bugfix contract without a guidance gap",
                "fields": {"skills_checked": "bugfix-debugging", "outcome": "no_reusable_gap",
                           "observation": "not_needed"}}))
        invoke("review", "--review-outcome", "pass",
               "--code-review-evidence", "Reviewed disposable answer file; no executable or external effects",
               "--docs-freshness-evidence", "Fixture has no changed public behavior or documentation contract",
               "--structure-review-evidence", "One text fixture; no runtime owner added")
        invoke("finish")
        fixture.run_command(["git", "add", "answer.txt"], check=True)
        head = fixture.run_command(["git", "rev-parse", "HEAD"], check=True).stdout
        staged = fixture.run_command(["git", "diff", "--cached"], check=True).stdout
        output = invoke("start", "--command", "commit", "--request", "Commit the verified fixture",
                        "--intent", "prepare_commit", "--target-summary", "Disposable fixture",
                        "--approved-effect", effect, "--commit-ready", explicit=False)
        self.assertNotIn("SUCCESS gate-batch", output)
        self.assertIn("commit readiness: derived from the current review attestation", output)
        for step in ("start", "review", "finish"):
            self.assertIn("SUCCESS " + step, output)
        self.assertEqual(head, fixture.run_command(["git", "rev-parse", "HEAD"], check=True).stdout)
        self.assertEqual(staged, fixture.run_command(["git", "diff", "--cached"], check=True).stdout)
        if effect == "external_write":
            source.write_text("changed after review\n")
            fixture.run_command(["git", "add", "answer.txt"], check=True)
            output = invoke("start", "--command", "commit", "--request", "Proceed with the agreed outcome",
                            "--intent", "prepare_commit", "--target-summary", "Disposable fixture",
                            "--approved-effect", effect, "--commit-ready", explicit=False)
            self.assertIn("SUCCESS start", output)
            self.assertIn("no evidence was reused", output)
            self.assertNotIn("SUCCESS review", output)
            self.assertNotIn("SUCCESS finish", output)
            self.assertEqual(head, fixture.run_command(["git", "rev-parse", "HEAD"], check=True).stdout)
