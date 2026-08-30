from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_worktree_identity import (
    WorktreeSessionError,
    new_worktree_path,
    resolve_base_ref,
    worktree_root,
)
from agent_worktree_session import create_worker_worktree, remove_worker_worktree


class _TempGitRepoTestCase(unittest.TestCase):
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

    def _git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=self.project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


class CreateWorkerWorktreeTests(_TempGitRepoTestCase):
    def test_create_makes_an_isolated_worktree_from_head(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)

        snapshot = create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertTrue(worktree_path.is_dir())
        self.assertTrue((worktree_path / "tracked.txt").exists())
        self.assertRegex(snapshot.fingerprint, r"^[0-9a-f]{64}$")
        # The worktree is registered against the main repo.
        listing = self._git("worktree", "list").stdout.decode("utf-8")
        self.assertIn(str(worktree_path.resolve()), listing)

    def test_writes_inside_worktree_leave_the_main_tree_unchanged(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        create_worker_worktree(self.project, base_ref, worktree_path)

        (worktree_path / "worker-only.txt").write_text("isolated\n", encoding="utf-8")
        (worktree_path / "tracked.txt").write_text("changed in worktree\n", encoding="utf-8")

        # Main checkout tracked file is untouched, and the worker file never
        # appears in the main working tree.
        self.assertEqual(
            "tracked\n", (self.project / "tracked.txt").read_text(encoding="utf-8")
        )
        self.assertFalse((self.project / "worker-only.txt").exists())
        main_status = self._git("status", "--porcelain").stdout.decode("utf-8")
        self.assertEqual("", main_status.strip())

    def test_base_ref_is_head_and_hides_uncommitted_parent_changes(self) -> None:
        # An uncommitted change in the parent is not visible to a HEAD worktree.
        (self.project / "tracked.txt").write_text("dirty parent\n", encoding="utf-8")
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)

        create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertEqual(
            "tracked\n", (worktree_path / "tracked.txt").read_text(encoding="utf-8")
        )

    def test_two_workers_get_distinct_worktrees(self) -> None:
        base_ref = resolve_base_ref(self.project)
        first = new_worktree_path(self.project)
        second = new_worktree_path(self.project)

        create_worker_worktree(self.project, base_ref, first)
        create_worker_worktree(self.project, base_ref, second)

        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())


class ContinuingInTheSameWorktreeTests(_TempGitRepoTestCase):
    """A task should be able to carry on where it left off.

    `git worktree add` refuses a path that already exists, so asking for the
    worktree a task already has raised and the caller got a new one: a fresh
    checkout, and the work in progress left behind. Separating tasks by
    worktree is right, but it stopped being something you could continue
    inside, which turns every follow-up turn into a new working copy.
    """

    def test_the_same_worktree_can_be_asked_for_twice(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        first = create_worker_worktree(self.project, base_ref, worktree_path)

        second = create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertEqual(first.fingerprint, second.fingerprint)
        # And it is still one registered worktree, not a second registration.
        listing = self._git("worktree", "list").stdout.decode("utf-8")
        self.assertEqual(1, listing.count(str(worktree_path.resolve())))

    def test_work_in_progress_survives_the_continuation(self) -> None:
        # The point of continuing: an unfinished edit is still there.
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        create_worker_worktree(self.project, base_ref, worktree_path)
        (worktree_path / "in-progress.py").write_text("half\n", encoding="utf-8")

        create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertEqual(
            "half\n", (worktree_path / "in-progress.py").read_text(encoding="utf-8")
        )

    def test_an_existing_directory_that_is_not_a_worktree_is_refused(self) -> None:
        """Reuse rests on the proof, not on the path existing.

        Otherwise any directory dropped at a canonical-looking name would be
        adopted as an isolated worktree and handed the trust that goes with it.
        """

        base_ref = resolve_base_ref(self.project)
        impostor = new_worktree_path(self.project)
        impostor.mkdir(parents=True)
        (impostor / "decoy.txt").write_text("not a worktree\n", encoding="utf-8")

        with self.assertRaises(WorktreeSessionError):
            create_worker_worktree(self.project, base_ref, impostor)

    def test_a_worktree_of_another_repository_is_refused(self) -> None:
        # Sharing Git's common directory is part of the proof: a worktree of a
        # different repository at the right path is still not this project's.
        other = Path(self.temporary_directory.name) / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.invalid"], cwd=other, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=other, check=True)
        (other / "f.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=other, check=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=other, check=True)

        foreign = new_worktree_path(self.project)
        foreign.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(foreign), "HEAD"],
            cwd=other,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        with self.assertRaises(WorktreeSessionError):
            create_worker_worktree(self.project, resolve_base_ref(self.project), foreign)


class FailClosedTests(_TempGitRepoTestCase):
    def test_invalid_base_ref_raises_and_does_not_touch_main_tree(self) -> None:
        worktree_path = new_worktree_path(self.project)

        with self.assertRaises(WorktreeSessionError):
            create_worker_worktree(self.project, "does-not-exist", worktree_path)

        self.assertFalse(worktree_path.exists())
        self.assertEqual(
            "tracked\n", (self.project / "tracked.txt").read_text(encoding="utf-8")
        )

    def test_empty_base_ref_raises(self) -> None:
        with self.assertRaises(WorktreeSessionError):
            create_worker_worktree(self.project, "", new_worktree_path(self.project))

    def test_existing_occupied_path_raises_rather_than_falling_back(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        worktree_path.mkdir()
        (worktree_path / "squatter.txt").write_text("occupied\n", encoding="utf-8")

        with self.assertRaises(WorktreeSessionError):
            create_worker_worktree(self.project, base_ref, worktree_path)

    def test_rejects_non_generated_worktree_name_before_git_mutation(self) -> None:
        invalid_path = worktree_root(self.project) / "not-generated"

        with self.assertRaisesRegex(WorktreeSessionError, "generated worker path"):
            create_worker_worktree(
                self.project,
                resolve_base_ref(self.project),
                invalid_path,
            )

        self.assertFalse(invalid_path.exists())


class RemoveWorkerWorktreeTests(_TempGitRepoTestCase):
    def test_remove_cleans_up_a_worktree(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertTrue(remove_worker_worktree(self.project, worktree_path))
        self.assertFalse(worktree_path.exists())
        listing = self._git("worktree", "list").stdout.decode("utf-8")
        self.assertNotIn(str(worktree_path.resolve()), listing)

    def test_remove_missing_worktree_reports_gone_without_crashing(self) -> None:
        worktree_path = new_worktree_path(self.project)
        self.assertFalse(remove_worker_worktree(self.project, worktree_path))


class RemoveDirtyWorktreeFailClosedTests(_TempGitRepoTestCase):
    """A dirty worktree must not be silently force-deleted (Fix 2)."""

    def _make_dirty_worktree(self) -> Path:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        create_worker_worktree(self.project, base_ref, worktree_path)
        (worktree_path / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        (worktree_path / "extra.txt").write_text("untracked\n", encoding="utf-8")
        return worktree_path

    def test_dirty_worktree_without_force_raises_and_preserves_it(self) -> None:
        worktree_path = self._make_dirty_worktree()

        with self.assertRaises(WorktreeSessionError):
            remove_worker_worktree(self.project, worktree_path)

        # The unmerged work is preserved; nothing was auto-force-deleted.
        self.assertTrue(worktree_path.exists())
        self.assertEqual(
            "dirty\n", (worktree_path / "tracked.txt").read_text(encoding="utf-8")
        )
        listing = self._git("worktree", "list").stdout.decode("utf-8")
        self.assertIn(str(worktree_path.resolve()), listing)

    def test_dirty_worktree_with_explicit_force_removes(self) -> None:
        worktree_path = self._make_dirty_worktree()

        self.assertTrue(remove_worker_worktree(self.project, worktree_path, force=True))
        self.assertFalse(worktree_path.exists())

    def test_clean_worktree_without_force_still_removes(self) -> None:
        base_ref = resolve_base_ref(self.project)
        worktree_path = new_worktree_path(self.project)
        create_worker_worktree(self.project, base_ref, worktree_path)

        self.assertTrue(remove_worker_worktree(self.project, worktree_path))
        self.assertFalse(worktree_path.exists())


class WorktreeRootTests(_TempGitRepoTestCase):
    def test_new_paths_live_under_the_project_worktree_root(self) -> None:
        path = new_worktree_path(self.project)
        self.assertEqual(worktree_root(self.project), path.parent)
        self.assertTrue(str(path).startswith(str(self.project)))


if __name__ == "__main__":
    unittest.main()
