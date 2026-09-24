"""One hook run may reuse a Git answer; nothing outside it, or after its checks, may.

The scope is only safe if three edges hold: no scope means no reuse, a worktree
answer is dropped when the hook says its checks may have moved the tree, and a
caller that refuses signature-based reuse still gets a content-derived
fingerprint rather than someone else's recorded one.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_continuation_store
import agent_execution_capsule_state as capsule_state
import support.bounded_git as bounded_git
from support.git_read_scope import (
    git_read_scope,
    invalidate_worktree_reads,
    stable_read,
    worktree_entry,
)


def git(project: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=project, check=True, capture_output=True)


class CountingGit:
    """Count Git processes started through the bounded runner."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.original = bounded_git.subprocess.run

    def __call__(self, args, *positional, **keywords):
        if args and args[0] == "git":
            self.calls.append(list(args[1:]))
        return self.original(args, *positional, **keywords)


class ScopePrimitiveTests(unittest.TestCase):
    def test_no_scope_computes_every_time(self):
        calls = []
        stable_read("k", lambda: calls.append(1))
        stable_read("k", lambda: calls.append(1))
        self.assertEqual(2, len(calls))
        self.assertIsNone(worktree_entry("k"))

    def test_stable_answer_is_computed_once_and_survives_invalidation(self):
        calls = []
        with git_read_scope():
            stable_read("k", lambda: calls.append(1) or "v")
            invalidate_worktree_reads()
            self.assertEqual("v", stable_read("k", lambda: calls.append(1) or "w"))
        self.assertEqual(1, len(calls))

    def test_worktree_answer_is_dropped_by_invalidation(self):
        with git_read_scope():
            worktree_entry("root")["head"] = "a"
            invalidate_worktree_reads()
            self.assertEqual({}, worktree_entry("root"))

    def test_errors_are_not_kept(self):
        def failing():
            raise RuntimeError("git failed")

        with git_read_scope():
            with self.assertRaises(RuntimeError):
                stable_read("k", failing)
            self.assertEqual("ok", stable_read("k", lambda: "ok"))

    def test_disabled_and_nested_scopes_start_empty(self):
        with git_read_scope():
            stable_read("k", lambda: "outer")
            with git_read_scope(enabled=False):
                self.assertEqual("fresh", stable_read("k", lambda: "fresh"))
            with git_read_scope():
                self.assertEqual("inner", stable_read("k", lambda: "inner"))
            self.assertEqual("outer", stable_read("k", lambda: "late"))


class GitStateScopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()
        (self.project / "a.txt").write_text("one\n")
        git(self.project, "init", "-q")
        git(self.project, "add", "a.txt")
        git(self.project, "-c", "user.name=T", "-c", "user.email=t@example.invalid",
            "commit", "-qm", "init")
        (self.project / "a.txt").write_text("two\n")
        self.counter = CountingGit()
        patcher = patch.object(bounded_git.subprocess, "run", self.counter)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_repeat_reads_in_one_epoch_start_no_git(self):
        with git_read_scope():
            first = capsule_state.git_states_for_paths(self.project, self.project)
            used = len(self.counter.calls)
            again = capsule_state.git_states_for_paths(self.project, self.project)
        self.assertEqual(first, again)
        self.assertEqual(used, len(self.counter.calls))

    def test_invalidation_observes_a_later_edit(self):
        with git_read_scope():
            before = capsule_state.git_state(self.project)
            (self.project / "a.txt").write_text("three, longer\n")
            self.assertEqual(before, capsule_state.git_state(self.project))
            invalidate_worktree_reads()
            after = capsule_state.git_state(self.project)
        self.assertNotEqual(before["worktree_fingerprint"], after["worktree_fingerprint"])
        self.assertEqual(after, capsule_state.git_state(self.project))

    def test_matching_record_is_returned_as_recorded(self):
        live = capsule_state.git_state(self.project)
        recorded = dict(live, worktree_fingerprint="f" * 64)
        with git_read_scope():
            capsule_state.git_state(self.project)
            self.assertEqual(recorded, capsule_state.git_state(self.project, recorded))

    def test_caller_without_record_gets_a_strong_capture_not_a_reused_record(self):
        live = capsule_state.git_state(self.project)
        recorded = dict(live, worktree_fingerprint="f" * 64)
        with git_read_scope():
            self.assertEqual(recorded, capsule_state.git_state(self.project, recorded))
            strong = capsule_state.git_state(self.project)
        self.assertEqual(live, strong)

    def test_check_ignore_is_asked_once_per_path(self):
        (self.project / ".gitignore").write_text(".tao/\n")
        packet = self.project / ".tao" / "runs" / "r" / "continuation.json"
        with git_read_scope():
            answers = [agent_continuation_store._git_ignores(self.project, packet) for _ in range(3)]
        self.assertEqual([True, True, True], answers)
        self.assertEqual(1, sum(1 for call in self.counter.calls if call[0] == "check-ignore"))


if __name__ == "__main__":
    unittest.main()
