"""A representative review and finish stay within their Git process budget.

Before one hook run shared its Git answers, this exact lifecycle started 78
Git processes in `review` and 47 in `finish`, most of them the same HEAD,
top-level and porcelain-status reads. The bounds below sit just above the
current counts, so a change that drops the per-invocation reuse -- or adds a
new repeated read -- fails here instead of surfacing as hook latency.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import test_claude_pretool_execution as fixture_module

REVIEW_GIT_CALL_BOUND = 52
FINISH_GIT_CALL_BOUND = 34

# Counts every Git process the hook itself starts, then runs the hook in this
# same interpreter. Child processes (VibeGuard's own Git use) are not the
# hook's reads and are deliberately not counted.
COUNTING_RUNNER = r"""
import json, runpy, subprocess, sys
from pathlib import Path

calls = []
original = subprocess.Popen.__init__

def counting(self, args, *positional, **keywords):
    items = list(args) if isinstance(args, (list, tuple)) else [args]
    if items and Path(str(items[0])).name == "git":
        calls.append([str(item) for item in items[1:]])
    return original(self, args, *positional, **keywords)

subprocess.Popen.__init__ = counting
log, script = sys.argv[1], sys.argv[2]
sys.argv = [script, *sys.argv[3:]]
sys.path.insert(0, str(Path(script).parent))
code = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exit_:
    code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
finally:
    Path(log).write_text(json.dumps(calls))
raise SystemExit(code)
"""


class ReviewGitCallBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PretoolExecutionTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        project = self.fixture.project
        (project / ".gitignore").write_text((fixture_module.ROOT / ".gitignore").read_text())
        (project / "VIBEGUARD.md").write_text((fixture_module.ROOT / "VIBEGUARD.md").read_text())
        (project / "answer.txt").write_text("original\n")
        self.fixture.run_command(["git", "add", ".gitignore", "VIBEGUARD.md", "answer.txt"], check=True)
        self.fixture.run_command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                                  "commit", "-qm", "fixture policy"], check=True)
        self.script = str(fixture_module.ROOT / "scripts/agent-hook.py")
        self.common = ["--project", str(project), "--rules", str(fixture_module.ROOT)]
        self.log = Path(self.fixture.directory.name) / "git-calls.json"

    def counted_hook(self, name, *arguments):
        result = self.fixture.run_command(
            [sys.executable, "-c", COUNTING_RUNNER, str(self.log), self.script,
             name, *self.common, *arguments]
        )
        return result, json.loads(self.log.read_text())

    def test_review_and_finish_stay_within_git_call_budget(self):
        self.fixture.start()
        (self.fixture.project / "answer.txt").write_text("changed\n")
        recorded = self.fixture.run_command([sys.executable, self.script, "gate-batch", *self.common,
            "--gate-record", json.dumps({"gate": "tests", "evidence": "Fixture output asserted",
                "fields": {"check": "Fixture output assertion", "result": "1 test; 0 failures"}}),
            "--gate-record", json.dumps({"gate": "retrospective check",
                "evidence": "Fixture lifecycle follows the existing contract without a guidance gap",
                "fields": {"skills_checked": "bugfix-debugging", "outcome": "no_reusable_gap",
                           "observation": "not_needed"}})])
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)

        reviewed, review_calls = self.counted_hook(
            "review", "--review-outcome", "pass",
            "--code-review-evidence", "Reviewed the one-line fixture change; no defect",
            "--docs-freshness-evidence", "No documentation depends on the fixture value",
        )
        self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
        self.assertLessEqual(len(review_calls), REVIEW_GIT_CALL_BOUND, review_calls)

        finished, finish_calls = self.counted_hook("finish")
        self.assertEqual(0, finished.returncode, finished.stdout + finished.stderr)
        self.assertLessEqual(len(finish_calls), FINISH_GIT_CALL_BOUND, finish_calls)


if __name__ == "__main__":
    unittest.main()
