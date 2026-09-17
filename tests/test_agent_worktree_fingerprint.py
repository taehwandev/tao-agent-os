from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_execution_capsule_state import git_state
from agent_worktree_fingerprint import (
    WorktreeSnapshot,
    WorktreeFingerprintLimitExceeded,
    capture_worktree_state,
    worktree_signature,
)


class WorktreeFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary_directory.name) / "project"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (self.project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Tao Agent OS Tests")
        self._git("add", "-A")
        self._git("commit", "-qm", "initial")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_unchanged_record_reuses_strong_fingerprint(self) -> None:
        (self.project / "untracked.txt").write_text("local\n", encoding="utf-8")
        recorded = git_state(self.project)

        with patch(
            "agent_execution_capsule_state.capture_worktree_state",
            side_effect=AssertionError("unchanged state must not repeat the strong scan"),
        ):
            current = git_state(self.project, recorded)

        self.assertEqual(recorded, current)

    def test_same_dirty_status_with_changed_content_runs_strong_scan(self) -> None:
        tracked = self.project / "tracked.txt"
        tracked.write_text("dirty-one\n", encoding="utf-8")
        recorded = git_state(self.project)
        tracked.write_text("dirty-two\n", encoding="utf-8")

        with patch(
            "agent_execution_capsule_state.capture_worktree_state",
            wraps=capture_worktree_state,
        ) as strong_capture:
            current = git_state(self.project, recorded)

        strong_capture.assert_called_once_with(self.project)
        self.assertNotEqual(
            recorded["worktree_fingerprint"], current["worktree_fingerprint"]
        )

    def test_head_change_during_reuse_retries_instead_of_returning_stale_record(self) -> None:
        recorded = git_state(self.project)
        old_head = recorded["head"]
        new_head = "f" * 40
        refreshed = WorktreeSnapshot(fingerprint="a" * 64, signature="b" * 64)

        with patch(
            "agent_execution_capsule_state.git_output",
            side_effect=[old_head, new_head, new_head, new_head],
        ), patch(
            "agent_execution_capsule_state.worktree_signature",
            return_value=recorded["worktree_signature"],
        ), patch(
            "agent_execution_capsule_state.capture_worktree_state",
            return_value=refreshed,
        ) as strong_capture:
            current = git_state(self.project, recorded)

        strong_capture.assert_called_once_with(self.project)
        self.assertEqual(new_head, current["head"])
        self.assertEqual(refreshed.fingerprint, current["worktree_fingerprint"])

    def test_same_size_replacement_with_restored_mtime_invalidates_signature(self) -> None:
        local = self.project / "untracked.txt"
        local.write_text("first\n", encoding="utf-8")
        before = local.stat()
        signature = worktree_signature(self.project)

        local.unlink()
        local.write_text("other\n", encoding="utf-8")
        os.utime(local, ns=(before.st_atime_ns, before.st_mtime_ns))

        self.assertNotEqual(signature, worktree_signature(self.project))

    def test_untracked_file_count_limit_stops_strong_scan(self) -> None:
        (self.project / "one.txt").write_text("1", encoding="utf-8")
        (self.project / "two.txt").write_text("2", encoding="utf-8")

        with patch("agent_worktree_fingerprint.MAX_UNTRACKED_FILES", 1):
            with self.assertRaises(WorktreeFingerprintLimitExceeded):
                capture_worktree_state(self.project)

    def test_untracked_byte_limit_stops_signature_and_strong_scan(self) -> None:
        (self.project / "large.bin").write_bytes(b"1234")

        with patch("agent_worktree_fingerprint.MAX_UNTRACKED_BYTES", 3):
            with self.assertRaises(WorktreeFingerprintLimitExceeded):
                worktree_signature(self.project)
            with self.assertRaises(WorktreeFingerprintLimitExceeded):
                capture_worktree_state(self.project)

    def test_staged_object_change_invalidates_signature(self) -> None:
        tracked = self.project / "tracked.txt"
        tracked.write_text("staged-one\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        signature = worktree_signature(self.project)
        tracked.write_text("staged-two\n", encoding="utf-8")
        self._git("add", "tracked.txt")

        self.assertNotEqual(signature, worktree_signature(self.project))

    def test_staging_the_same_tracked_bytes_preserves_state_identity(self) -> None:
        tracked = self.project / "tracked.txt"
        tracked.write_text("changed\n", encoding="utf-8")
        before = capture_worktree_state(self.project)

        self._git("add", "tracked.txt")

        self.assertEqual(before, capture_worktree_state(self.project))

    def test_staging_the_same_new_file_preserves_state_identity(self) -> None:
        (self.project / "new.txt").write_text("new\n", encoding="utf-8")
        before = capture_worktree_state(self.project)

        self._git("add", "new.txt")

        self.assertEqual(before, capture_worktree_state(self.project))

    def test_staging_the_same_rename_preserves_state_identity(self) -> None:
        (self.project / "tracked.txt").rename(self.project / "moved.txt")
        before = capture_worktree_state(self.project)

        self._git("add", "--all")

        self.assertEqual(before, capture_worktree_state(self.project))

    def test_untracked_symlink_removal_during_capture_retries_safely(self) -> None:
        local = self.project / "local-link"
        local.symlink_to("missing-target")
        original_readlink = os.readlink

        def raced_readlink(path: Path) -> str:
            if path == local:
                local.unlink(missing_ok=True)
                raise FileNotFoundError(path)
            return original_readlink(path)

        with patch("agent_worktree_fingerprint.os.readlink", raced_readlink):
            snapshot = capture_worktree_state(self.project)

        self.assertRegex(snapshot.fingerprint, r"^[0-9a-f]{64}$")

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


if __name__ == "__main__":
    unittest.main()
