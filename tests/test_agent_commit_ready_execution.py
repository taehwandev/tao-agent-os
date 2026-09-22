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
        for step in ("start", "review", "gate-batch", "finish"):
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
