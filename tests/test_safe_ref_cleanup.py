"""Self-protecting local ref cleanup needs no workflow lifecycle.

`git branch -d`, a plain `git worktree remove`, `git worktree prune`, and the
remote-tracking prunes are refused by git itself whenever they could lose work.
A session with no run in a governed project was nevertheless told to run the
workflow start hook first, while the same command was admitted in the Tao
main checkout. The forcing spellings keep their existing treatment.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from test_claude_pretool_gate import (  # also puts scripts/ on sys.path
    _decide,
    _opt_in_project,
    _require_linked_worktree,
    _write_preflight,
    gate,
)
from support.global_state import STATE_HOME_ENV

_STATE_HOME: "tempfile.TemporaryDirectory | None" = None
_OUTER_STATE_HOME: "str | None" = None


def setUpModule() -> None:
    global _STATE_HOME, _OUTER_STATE_HOME
    _OUTER_STATE_HOME = os.environ.get(STATE_HOME_ENV)
    _STATE_HOME = tempfile.TemporaryDirectory()
    os.environ[STATE_HOME_ENV] = _STATE_HOME.name


def tearDownModule() -> None:
    if _OUTER_STATE_HOME is None:
        os.environ.pop(STATE_HOME_ENV, None)
    else:
        os.environ[STATE_HOME_ENV] = _OUTER_STATE_HOME
    if _STATE_HOME is not None:
        _STATE_HOME.cleanup()


ADMITTED = (
    "git branch -d merged-topic",
    "git branch --delete merged-a merged-b",
    "git -C {project} branch -d merged-topic",
    "git worktree prune",
    "git worktree prune -v",
    "git worktree prune --dry-run",
    "git -C {project} worktree prune --verbose",
    "git worktree remove ../old",
    "git -C {project} worktree remove ../old",
    "git fetch --prune",
    "git -C {project} fetch --prune",
    "git remote prune origin",
)

STILL_GOVERNED = (
    "git branch -D merged-topic",
    "git branch -d --force merged-topic",
    "git branch --delete --force merged-topic",
    "git branch -df merged-topic",
    "git branch -M renamed",
    "git worktree remove --force ../old",
    "git worktree remove -f ../old",
    "git stash drop",
    "git stash clear",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git push origin --delete merged-topic",
    "git branch -d x && touch y",
    "git branch -d x > out.txt",
)


def _scenario(base: Path, name: str, run_session: str = "") -> Path:
    project = _opt_in_project(base)
    if run_session:
        _write_preflight(project, run_session)  # before the fake .git marker
    if name == "plain":
        return project
    _require_linked_worktree(project, linked=name != "protected_main")
    if name == "linked_entry_required":
        policy = project / gate.WORKTREE_POLICY_PATH
        declared = json.loads(policy.read_text(encoding="utf-8"))
        declared["require_workflow_entry"] = True
        policy.write_text(json.dumps(declared), encoding="utf-8")
    return project


def _decision(project: Path, command: str, session: str = "no-run") -> str:
    code, out = _decide(
        {
            "tool_name": "Bash",
            "cwd": str(project),
            "session_id": session,
            "tool_input": {"command": command.format(project=project)},
        }
    )
    assert code == 0
    if not out:
        return "silent"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


SCENARIOS = ("plain", "protected_main", "linked", "linked_entry_required")


class SafeRefCleanupNeedsNoLifecycleTests(unittest.TestCase):
    def test_self_protecting_ref_cleanup_is_admitted_without_a_run(self) -> None:
        for scenario in SCENARIOS:
            for command in ADMITTED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    self.assertNotEqual("deny", _decision(project, command))

    def test_ref_cleanup_is_admitted_beside_a_writable_run(self) -> None:
        for scenario in ("plain", "linked_entry_required"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                project = _scenario(Path(tmp), scenario, "writable-run")
                self.assertNotEqual(
                    "deny",
                    _decision(project, "git branch -d merged-topic", "writable-run"),
                )

    def test_forcing_or_discarding_forms_still_need_their_route(self) -> None:
        for scenario in ("plain", "linked_entry_required"):
            for command in STILL_GOVERNED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    # Unchanged: refused without a run, or put to the operator
                    # where a worktree hazard already asks about it.
                    self.assertIn(_decision(project, command), {"deny", "ask"})

    def test_protected_checkout_keeps_approving_merged_branch_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _scenario(Path(tmp), "protected_main")
            self.assertEqual("allow", _decision(project, "git branch -d merged-topic"))


if __name__ == "__main__":
    unittest.main()
