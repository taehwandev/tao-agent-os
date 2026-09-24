"""A read-only review closes with its findings; a writable one still repairs.

Recording `--review-outcome findings` in a read-only review made the hook
demand a code repair and a repair-verify receipt for work the run could not
own, so a review whose product is its findings could never finish.
"""
import json
import sys
import unittest

import test_claude_pretool_execution as fixture_module


class ReadOnlyReviewFindingsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PretoolExecutionTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        project = self.fixture.project
        (project / ".gitignore").write_text((fixture_module.ROOT / ".gitignore").read_text())
        (project / "VIBEGUARD.md").write_text((fixture_module.ROOT / "VIBEGUARD.md").read_text())
        self.fixture.run_command(["git", "add", ".gitignore", "VIBEGUARD.md"], check=True)
        self.fixture.run_command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                                  "commit", "-qm", "fixture policy"], check=True)
        self.base = [sys.executable, str(fixture_module.ROOT / "scripts/agent-hook.py")]
        self.common = ["--project", str(project), "--rules", str(fixture_module.ROOT)]

    def hook(self, name, *arguments):
        return self.fixture.run_command(self.base + [name] + self.common + list(arguments))

    def review(self, *scope):
        return self.hook(
            "review", *scope, "--review-outcome", "findings",
            "--code-review-evidence", "Found one misleading sentence in the reviewed file",
            "--docs-freshness-evidence", "The finding concerns documentation wording only",
            "--structure-review-evidence", "No runtime owner added",
        )

    def record_route_gates(self):
        recorded = self.hook("gate-batch", "--gate-record", json.dumps({
            "gate": "tests", "evidence": "Fixture output asserted",
            "fields": {"check": "Fixture output assertion", "result": "1 test; 0 failures"}}),
            "--gate-record", json.dumps({"gate": "retrospective check",
                "evidence": "Fixture lifecycle follows the existing contract without a guidance gap",
                "fields": {"skills_checked": "bugfix-debugging", "outcome": "no_reusable_gap",
                           "observation": "not_needed"}}))
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)

    def test_read_only_review_with_findings_finishes_and_reports_them(self):
        self.fixture.start(read_only=True)
        self.record_route_gates()

        reviewed = self.review("--review-scope", "pathspec", "--review-path", "AGENTS.md")
        self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
        self.assertIn("findings recorded as this read-only review's result", reviewed.stdout)
        self.assertNotIn("repair-verify", reviewed.stdout)

        finished = self.hook("finish")
        self.assertEqual(0, finished.returncode, finished.stdout + finished.stderr)
        self.assertIn("completed with findings", finished.stdout)

    def test_writable_route_findings_still_require_repair(self):
        self.fixture.start()
        (self.fixture.project / "answer.txt").write_text("changed\n")
        self.record_route_gates()

        reviewed = self.review("--review-scope", "working-tree")
        self.assertNotEqual(0, reviewed.returncode)
        self.assertIn("unresolved findings", reviewed.stdout)


if __name__ == "__main__":
    unittest.main()
