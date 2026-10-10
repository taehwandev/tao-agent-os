"""A checkout holding work or an open Tao run is not deleted through the gate.

Reproduces the loss of a task worktree whose branch had no commits of its own
(so it sat at an ancestor of main and looked merged) while it held modified
files, an untracked test and a running Tao run. `git worktree remove --force`
and `rm -rf` were deferred to the runtime's permission flow, which sees none
of that. Ordinary cleanup of a finished, clean, merged worktree stays allowed.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_claude_pretool_gate import _decide  # also puts scripts/ on sys.path
from support.global_state import STATE_HOME_ENV
import agent_run_registry
from agent_repository_checkouts import SETTLED_RUN_STATES, checkout_removal_hazard
from agent_worktree_identity import WorktreeSessionError, new_worktree_path, resolve_base_ref
from agent_worktree_session import create_worker_worktree, remove_worker_worktree
from claude_pretool_checkout_removal import checkout_removal_denial


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _write_registry(checkout: Path, *states: str) -> None:
    runs = [{"run_id": f"{index:032x}", "state": state} for index, state in enumerate(states)]
    path = checkout / ".tao" / "run-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "runs": runs}), encoding="utf-8")


class _Repository(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state_home = tempfile.TemporaryDirectory()
        self.addCleanup(state_home.cleanup)
        previous = os.environ.get(STATE_HOME_ENV)
        os.environ[STATE_HOME_ENV] = state_home.name
        self.addCleanup(
            lambda: os.environ.pop(STATE_HOME_ENV, None)
            if previous is None else os.environ.__setitem__(STATE_HOME_ENV, previous)
        )
        self.base = Path(temporary.name).resolve()
        self.main = self.base / "repo"
        self.main.mkdir()
        _git(self.main, "init", "-q", "-b", "main")
        _git(self.main, "config", "user.email", "tests@example.invalid")
        _git(self.main, "config", "user.name", "Tao Tests")
        (self.main / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (self.main / "module.py").write_text("value = 1\n", encoding="utf-8")
        _git(self.main, "add", "-A")
        _git(self.main, "commit", "-qm", "initial")
        self.worktrees = self.base / "repo-worktrees"
        self.task = self.worktrees / "task"
        # A task branch with no commits of its own: at main, so it looks merged.
        _git(self.main, "worktree", "add", "-q", "-b", "owner/fix/task", str(self.task), "main")

    def decision(self, command: str) -> tuple[str, str]:
        code, out = _decide(
            {
                "tool_name": "Bash",
                "cwd": str(self.main),
                "session_id": "removal-guard",
                "tool_input": {"command": command},
            }
        )
        self.assertEqual(0, code)
        if not out:
            return "silent", ""
        output = json.loads(out)["hookSpecificOutput"]
        return (
            output.get("permissionDecision", "defer"),
            output.get("permissionDecisionReason") or output.get("additionalContext", ""),
        )

    def removal_commands(self) -> list[str]:
        return [
            f"git worktree remove --force {self.task}",
            f"git worktree remove -f -f {self.task}",
            f"git -C {self.main} worktree remove --force ../repo-worktrees/task",
            f"rm -rf {self.task}",
            f"cd {self.worktrees} && rm -fr task",
            f"rm -r -f {self.worktrees}",
            f"git worktree remove --force {self.task} && git branch -D owner/fix/task",
        ]


class DirtyCheckoutIsKeptTests(_Repository):
    def test_modified_and_untracked_files_refuse_every_removal_form(self) -> None:
        (self.task / "module.py").write_text("value = 2\n", encoding="utf-8")
        (self.task / "test_new.py").write_text("pass\n", encoding="utf-8")
        for command in self.removal_commands():
            with self.subTest(command=command):
                verdict, reason = self.decision(command)
                self.assertEqual("deny", verdict)
                self.assertIn("uncommitted or untracked changes", reason)
                self.assertIn(str(self.task), reason)
        self.assertTrue((self.task / "test_new.py").is_file())

    def test_untracked_file_alone_is_work(self) -> None:
        (self.task / "test_new.py").write_text("pass\n", encoding="utf-8")
        self.assertEqual("it has uncommitted or untracked changes", checkout_removal_hazard(self.task))

    def test_ignored_files_alone_are_not_work(self) -> None:
        (self.task / ".tao").mkdir()
        (self.task / ".tao" / "cache.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual("", checkout_removal_hazard(self.task))


class UnsettledRunIsKeptTests(_Repository):
    def test_active_run_on_merged_looking_branch_refuses_even_plain_remove(self) -> None:
        # Clean as far as git can tell, and its branch is an ancestor of main.
        _write_registry(self.task, "completed", "running")
        _git(self.main, "merge-base", "--is-ancestor", "owner/fix/task", "main")
        for command in [f"git worktree remove {self.task}", *self.removal_commands()]:
            with self.subTest(command=command):
                verdict, reason = self.decision(command)
                self.assertEqual("deny", verdict)
                self.assertIn("unsettled Tao run (running)", reason)

    def test_every_unfinished_state_is_protected(self) -> None:
        for state in ("paused", "resuming", "interrupted", "blocked", "failed",
                      "reconcile_required", "claiming"):
            with self.subTest(state=state):
                _write_registry(self.task, state)
                self.assertIn(state, checkout_removal_hazard(self.task))

    def test_unreadable_registry_keeps_the_checkout(self) -> None:
        path = self.task / ".tao" / "run-registry.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIn("unreadable", checkout_removal_hazard(self.task))

    def test_settled_states_match_the_registry(self) -> None:
        self.assertEqual(agent_run_registry.SETTLED_RUN_STATES, SETTLED_RUN_STATES)


class FinishedCleanCheckoutIsRemovableTests(_Repository):
    def test_finished_clean_merged_worktree_is_still_removed(self) -> None:
        _write_registry(self.task, "completed", "cancelled")
        command = f"git worktree remove {self.task}"
        for each in [command, *self.removal_commands()]:
            with self.subTest(command=each):
                # The task's `.tao/` makes it a Tao project, so the existing
                # workflow-entry rules still apply; this guard adds nothing.
                self.assertNotIn("deletes the checkout", self.decision(each)[1])
                self.assertEqual("", checkout_removal_hazard(self.task))
        _git(self.main, "worktree", "remove", str(self.task))
        _git(self.main, "branch", "-d", "owner/fix/task")
        self.assertFalse(self.task.exists())

    def test_unrelated_recursive_removal_is_not_read_as_a_checkout(self) -> None:
        (self.task / "module.py").write_text("value = 2\n", encoding="utf-8")
        (self.task / "build").mkdir()
        self.assertEqual("", checkout_removal_denial(["rm", "-rf", "build"], self.task))
        self.assertEqual("", checkout_removal_denial(["rm", str(self.task / "module.py")], self.main))
        self.assertEqual("", checkout_removal_denial(["git", "worktree", "prune"], self.main))
        self.assertEqual(
            "", checkout_removal_denial(["git", "worktree", "remove", str(self.base / "gone")], self.main)
        )

    def test_a_symlink_to_a_checkout_removes_only_the_link(self) -> None:
        (self.task / "module.py").write_text("value = 2\n", encoding="utf-8")
        link = self.base / "link"
        link.symlink_to(self.task)
        self.assertEqual("", checkout_removal_denial(["rm", "-rf", str(link)], self.base))


class WorkerWorktreeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve() / "project"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (self.project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        _git(self.project, "init", "-q")
        _git(self.project, "config", "user.email", "tests@example.invalid")
        _git(self.project, "config", "user.name", "Tao Tests")
        _git(self.project, "add", "-A")
        _git(self.project, "commit", "-qm", "initial")
        self.worktree = new_worktree_path(self.project)
        create_worker_worktree(self.project, resolve_base_ref(self.project), self.worktree)

    def test_forced_removal_still_keeps_an_unsettled_run(self) -> None:
        _write_registry(self.worktree, "running")
        with self.assertRaises(WorktreeSessionError):
            remove_worker_worktree(self.project, self.worktree, force=True)
        self.assertTrue(self.worktree.is_dir())

    def test_settled_run_does_not_block_removal(self) -> None:
        _write_registry(self.worktree, "completed")
        self.assertTrue(remove_worker_worktree(self.project, self.worktree))
        self.assertFalse(self.worktree.exists())


if __name__ == "__main__":
    unittest.main()
