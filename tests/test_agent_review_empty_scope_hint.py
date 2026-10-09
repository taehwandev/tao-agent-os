"""An empty review scope names the no-diff cleanup path.

A session that removed merged worktrees, branches and stashes reran review four
times with working-tree and pathspec scopes before giving up: the refusal named
the commit-range route only, although `repo-hygiene` was the scope that applies.
Kept apart from `test_agent_review_scope_guard.py`, which is over its budget.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_subjects import empty_review_scope_invocation_failure_details  # noqa: E402


class EmptyReviewScopeHintTests(unittest.TestCase):
    def test_the_refusal_names_the_repo_hygiene_route(self) -> None:
        details = empty_review_scope_invocation_failure_details(
            "review scope has no changed paths", "working-tree"
        )
        hint = next(line for line in details if line.startswith("no-diff cleanup:"))
        self.assertIn("--approved-effect destructive", hint)
        self.assertIn("--review-scope repo-hygiene", hint)
        self.assertTrue(details[-1].startswith("review did not start"))

    def test_the_refusal_names_the_cleanup_route_and_the_hygiene_concerns(self) -> None:
        """A destructive commit run without a hygiene concern was refused twice.

        The hint named the effect and the scope, so the session restarted with
        `--approved-effect destructive` and got the same refusal: the review also
        needs a branch, state or worktree concern, and the `cleanup` route, which
        needs no review, was the route for that removal all along.
        """
        details = empty_review_scope_invocation_failure_details(
            "review scope has no changed paths", "repo-hygiene"
        )
        hint = next(line for line in details if line.startswith("no-diff cleanup:"))
        self.assertIn("--command cleanup", hint)
        self.assertIn("--concern branch or state or worktree", hint)


if __name__ == "__main__":
    unittest.main()
