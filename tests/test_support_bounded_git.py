"""How long a local Git read may take, and what a caller sees when it doesn't.

Fifteen Git reads ran unbounded. The bound only helps if exceeding it reaches
each caller as the failure it already handles, so these tests check the
conversion at both ends: the runner reports a timeout as a failed run, and the
callers that were converted still take their own fail-closed path when it
happens.
"""

from __future__ import annotations

import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_continuation_store
import agent_worktree_fingerprint
import support.graphify_graph_freshness as graph_freshness
from support.bounded_git import GIT_READ_TIMEOUT_SECONDS, run_git


def timing_out(*_args, **_keywords):
    raise subprocess.TimeoutExpired(cmd=["git", "status"], timeout=GIT_READ_TIMEOUT_SECONDS)


class BoundedGitTests(unittest.TestCase):
    def test_a_command_that_finishes_is_returned_untouched(self) -> None:
        completed = run_git(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, completed.returncode)
        self.assertEqual("true", completed.stdout.strip())

    def test_exceeding_the_bound_is_reported_as_a_failed_run(self) -> None:
        """Not raised: every caller already handles a non-zero Git result."""

        with patch("subprocess.run", timing_out):
            completed = run_git(["git", "status"], cwd=ROOT, text=True, stdout=subprocess.PIPE)

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("git status", completed.stderr)
        self.assertIn("bound", completed.stderr)

    def test_the_refusal_matches_what_the_caller_asked_to_capture(self) -> None:
        """A caller unpacking bytes must not be handed str, or vice versa."""

        with patch("subprocess.run", timing_out):
            binary = run_git(["git", "status"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            quiet = run_git(["git", "status"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self.assertIsInstance(binary.stdout, bytes)
        self.assertIsInstance(binary.stderr, bytes)
        self.assertIsNone(quiet.stderr)

    def test_a_command_that_never_answers_is_actually_stopped(self) -> None:
        """The bound is real, not just handled.

        Injecting the exception proves only the handler. This runs a command
        that would never finish and requires the call to come back, which is
        what a stalled Git read looks like from the caller's side.
        """

        started = time.monotonic()
        completed = run_git(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=ROOT,
            timeout=0.3,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        elapsed = time.monotonic() - started

        self.assertNotEqual(0, completed.returncode)
        self.assertLess(elapsed, 10, "the call outlived its own bound")

    def test_a_caller_that_names_no_bound_still_gets_one(self) -> None:
        seen = {}

        def spy(*args, **keywords):
            seen.update(keywords)
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)

        with patch("subprocess.run", spy):
            run_git(["git", "status"], cwd=ROOT, stdout=subprocess.PIPE)

        self.assertEqual(GIT_READ_TIMEOUT_SECONDS, seen.get("timeout"))

    def test_the_default_bound_is_stated_once(self) -> None:
        self.assertGreaterEqual(GIT_READ_TIMEOUT_SECONDS, 5)
        self.assertLessEqual(GIT_READ_TIMEOUT_SECONDS, 30)


class ConvertedCallersFailClosedTests(unittest.TestCase):
    """A stalled Git read must not become a permissive answer."""

    def test_the_capsule_fingerprint_raises_rather_than_binding_nothing(self) -> None:
        with patch("subprocess.run", timing_out):
            with self.assertRaises(RuntimeError):
                agent_worktree_fingerprint.git_output(ROOT, "rev-parse", "HEAD")

    def test_the_packet_boundary_refuses_rather_than_assuming_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
            (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            packet = project / ".tao" / "runs" / ("0" * 32) / "continuation.json"
            packet.parent.mkdir(parents=True)
            packet.write_text("{}", encoding="utf-8")

            with patch("subprocess.run", timing_out):
                ignored = agent_continuation_store._git_ignores(project, packet)

        self.assertFalse(ignored, "an unanswered git check-ignore may not read as ignored")

    def test_graph_freshness_reports_no_head_rather_than_a_stale_one(self) -> None:
        with patch("subprocess.run", timing_out):
            self.assertIsNone(graph_freshness._git_head(ROOT))


if __name__ == "__main__":
    unittest.main()
