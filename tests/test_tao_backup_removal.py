"""Removing Tao's own `*.tao-backup` files needs no workflow lifecycle.

Setup writes `<name>.tao-backup` beside a file before rewriting it. Deleting
those Tao-made files from a governed project was refused until a workflow run
existed, so each stray backup cost a whole lifecycle. A lone `rm [-f]` whose
every operand is such a regular file is now admitted; anything else keeps the
ordinary verdict.
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
    gate,
)
from support.global_state import STATE_HOME_ENV
from claude_local_context_commands import tao_backup_removal

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


def _scenario(base: Path, name: str) -> Path:
    project = _opt_in_project(base)
    if name == "plain":
        return project
    _require_linked_worktree(project, linked=name != "protected_main")
    if name == "linked_entry_required":
        policy = project / gate.WORKTREE_POLICY_PATH
        declared = json.loads(policy.read_text(encoding="utf-8"))
        declared["require_workflow_entry"] = True
        policy.write_text(json.dumps(declared), encoding="utf-8")
    return project


def _decision(project: Path, command: str) -> str:
    code, out = _decide(
        {
            "tool_name": "Bash",
            "cwd": str(project),
            "session_id": "no-run",
            "tool_input": {"command": command.format(project=project)},
        }
    )
    assert code == 0
    if not out:
        return "silent"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def _populate(project: Path) -> None:
    (project / "AGENTS.md").write_text("guidance\n", encoding="utf-8")
    (project / "AGENTS.md.tao-backup").write_text("old\n", encoding="utf-8")
    (project / "settings.json.tao-backup").write_text("{}\n", encoding="utf-8")
    (project / "other.txt").write_text("x\n", encoding="utf-8")
    (project / "dir.tao-backup").mkdir()
    (project / "dir.tao-backup" / "inner").write_text("x\n", encoding="utf-8")
    (project / "link.tao-backup").symlink_to(project / "AGENTS.md")


ADMITTED = (
    "rm {project}/AGENTS.md.tao-backup",
    "rm -f {project}/AGENTS.md.tao-backup",
    "rm AGENTS.md.tao-backup settings.json.tao-backup",
    "/bin/rm -f -- {project}/AGENTS.md.tao-backup",
)

NOT_ADMITTED = (
    "rm {project}/AGENTS.md",
    "rm -r {project}/dir.tao-backup/",
    "rm -rf {project}/dir.tao-backup",
    "rm {project}/AGENTS.md.tao-backup {project}/other.txt",
    "rm {project}/link.tao-backup",
    "rm {project}/*.tao-backup",
    "rm {project}/dir.tao-backup/../AGENTS.md.tao-backup",
    "rm {project}/missing.tao-backup",
    "rm {project}/.tao-backup",
    "rm {project}/AGENTS.md.tao-backup && touch {project}/other.txt",
)

SCENARIOS = ("plain", "protected_main", "linked_entry_required")


class TaoBackupRemovalTests(unittest.TestCase):
    def test_tao_backup_removal_is_admitted_without_a_run(self) -> None:
        for scenario in SCENARIOS:
            for command in ADMITTED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    _populate(project)
                    self.assertNotIn(_decision(project, command), {"deny", "ask"})

    def test_backup_in_another_protected_project_is_admitted(self) -> None:
        # The reported shape: the session sits in one governed project and the
        # backup belongs to another project's protected main checkout.
        for command, admitted in (
            ("rm {project}/AGENTS.md.tao-backup", True),
            ("rm -f {project}/AGENTS.md.tao-backup {project}/settings.json.tao-backup", True),
            ("rm {project}/AGENTS.md", False),
            ("rm {project}/AGENTS.md.tao-backup {project}/other.txt", False),
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                session_project = _scenario(Path(tmp) / "here", "plain")
                target = _scenario(Path(tmp) / "there", "protected_main")
                _populate(target)
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(session_project),
                        "session_id": "no-run",
                        "tool_input": {"command": command.format(project=target)},
                    }
                )
                self.assertEqual(0, code)
                verdict = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "silent"
                if admitted:
                    self.assertNotIn(verdict, {"deny", "ask"})
                else:
                    self.assertIn(verdict, {"deny", "ask"})

    def test_anything_else_keeps_the_ordinary_verdict(self) -> None:
        # A protected main checkout defers ordinary commands to the native
        # permission layer, so only entry-requiring shapes can show a refusal.
        for scenario in ("plain", "linked_entry_required"):
            for command in NOT_ADMITTED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    _populate(project)
                    self.assertIn(_decision(project, command), {"deny", "ask"})

    def test_classifier_rejects_non_backup_operands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _populate(project)
            self.assertTrue(tao_backup_removal(["rm", "AGENTS.md.tao-backup"], project))
            self.assertFalse(tao_backup_removal(["rm", "AGENTS.md.tao-backup"], None))
            self.assertFalse(tao_backup_removal(["rm", "link.tao-backup"], project))
            self.assertFalse(tao_backup_removal(["rm", "-r", "dir.tao-backup"], project))
            self.assertFalse(tao_backup_removal(["rm", "dir.tao-backup"], project))
            self.assertFalse(tao_backup_removal(["rm", "-i", "AGENTS.md.tao-backup"], project))
            self.assertFalse(tao_backup_removal(["rm"], project))
            self.assertFalse(tao_backup_removal(["unlink", "AGENTS.md.tao-backup"], project))
            self.assertTrue((project / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
