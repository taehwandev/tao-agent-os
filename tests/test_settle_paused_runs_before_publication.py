"""A publication settles the session's paused run that a later finish superseded.

Reproduces a session that left a run paused (or failed) in the main checkout,
continued the work in a linked worktree, finished it there and merged it, then
ran `git push` from the main checkout with no new start. The pre-tool gate
resumed the old run and refused the push as "still open", with no close path
short of editing the run registry. Every step runs as a separate hook process
against a disposable repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _tao_test_support import ROOT, SCRIPTS, TemplateRepository, fake_vibeguard_environment

from agent_run_registry import transition_run
from test_work_continuity_lifecycle_e2e import (
    SESSION, detail, environment, git, hook, run_id, start, turn_boundary,
)

_MODULE_STATE: list = []
OTHER = "other-session"


def _build(project: Path) -> None:
    (project / "src").mkdir(parents=True)
    (project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.email", "settle@example.invalid")
    git(project, "config", "user.name", "Settle")
    git(project, "add", ".")
    git(project, "commit", "-qm", "fixture")


_FIXTURE = TemplateRepository(_build)


def setUpModule() -> None:
    directory = tempfile.TemporaryDirectory(prefix="tao-state-home-")
    state = mock.patch.dict(os.environ, {"TAO_STATE_HOME": directory.name})
    state.start()
    vibeguard = fake_vibeguard_environment()
    vibeguard.start()
    _MODULE_STATE.extend((state, directory, vibeguard))


def tearDownModule() -> None:
    state, directory, vibeguard = _MODULE_STATE
    vibeguard.stop()
    state.stop()
    directory.cleanup()
    _MODULE_STATE.clear()
    _FIXTURE.cleanup()


def runs(project: Path) -> dict[str, dict]:
    path = project / ".tao" / "run-registry.json"
    return {run["run_id"]: run for run in json.loads(path.read_text(encoding="utf-8"))["runs"]}


def pretool(cwd: Path, command: str) -> str:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "session_id": SESSION,
               "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "claude_pretool_gate.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        env={**environment(SESSION), "TAO_PRETOOL_RUNTIME": "claude"},
    )
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    return str(output.get("permissionDecisionReason") or output.get("additionalContext") or "")


class PausedRunBeforePublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.main = self.root / "project"
        _FIXTURE.copy_to(self.main)
        self.linked = self.root / "project-worktrees" / "close"

    def ok(self, result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result

    def paused(self, state: str = "interrupted", session: str = SESSION) -> str:
        """Run A, left paused by a turn boundary or by a failed finish."""
        run = run_id(self.ok(start(self.main, ROOT, "src/module.py 의 가드를 고쳐줘", session=session)))
        if state == "failed":
            (self.main / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(1, hook(self.main, ROOT, "finish", session=session).returncode)
            git(self.main, "checkout", "--", "src/module.py")
        self.ok(turn_boundary(self.main, session=session))
        self.assertEqual(state, runs(self.main)[run]["state"])
        return run

    def continued_in_worktree(self, paused: str) -> tuple[str, Path]:
        """Run B: the same work continued in a linked worktree, which keeps A open."""
        git(self.main, "worktree", "add", "-q", str(self.linked), "-b", "fix/close")
        later = self.ok(start(self.linked, ROOT, "워크트리에서 이어서 고쳐줘", "--continue-from", paused))
        return run_id(later), Path(detail(later, "evidence: ").split(": ", 1)[1])

    def finish(self, run: str, evidence: Path) -> None:
        transition_run(self.linked, evidence, "completed", run_id=run)
        (self.linked / "src" / "module.py").write_text("value = 3\n", encoding="utf-8")
        git(self.linked, "commit", "-qam", "fix module")
        git(self.main, "merge", "-q", "--ff-only", "fix/close")

    def assert_settled_before_push(self, state: str) -> None:
        old = self.paused(state)
        new, evidence = self.continued_in_worktree(old)
        self.finish(new, evidence)

        reason = pretool(self.main, "git push origin main")

        self.assertNotIn("is still open", reason)
        self.assertIn(f"paused run {old}", reason)
        self.assertIn(f"superseded by its later finished run {new}", reason)
        record = runs(self.main)[old]
        self.assertEqual(
            ("cancelled", new, state),
            (record["state"], record["superseded_by"], record["superseded_from_state"]),
        )

    def test_a_later_finish_settles_the_interrupted_run_before_a_push(self) -> None:
        self.assert_settled_before_push("interrupted")

    def test_a_later_finish_settles_the_failed_run_before_a_push(self) -> None:
        self.assert_settled_before_push("failed")

    def test_without_a_later_finish_the_paused_run_is_kept(self) -> None:
        old = self.paused()
        self.continued_in_worktree(old)

        self.assertIn("is still open", pretool(self.main, "git push origin main"))
        self.assertNotIn("superseded_by", runs(self.main)[old])

    def test_a_paused_run_updated_after_the_finish_began_is_kept(self) -> None:
        old = self.paused()
        new, evidence = self.continued_in_worktree(old)
        self.ok(hook(self.main, ROOT, "resume", "--last", "--runtime", "claude",
                     "--runtime-session-id", SESSION, "--run-id", old))
        self.ok(turn_boundary(self.main))
        self.finish(new, evidence)

        self.assertNotIn("superseded by", pretool(self.main, "git push origin main"))
        self.assertNotIn("superseded_by", runs(self.main)[old])

    def test_an_ordinary_command_does_not_settle_the_paused_run(self) -> None:
        old = self.paused()
        new, evidence = self.continued_in_worktree(old)
        self.finish(new, evidence)

        self.assertNotIn("superseded by", pretool(self.main, "python3 tools/x.py"))
        self.assertNotIn("superseded_by", runs(self.main)[old])

    def test_another_sessions_paused_run_is_untouched(self) -> None:
        peer = self.paused(session=OTHER)
        git(self.main, "worktree", "add", "-q", str(self.linked), "-b", "fix/close")
        later = self.ok(start(self.linked, ROOT, "README 를 정리해줘"))
        self.finish(run_id(later), Path(detail(later, "evidence: ").split(": ", 1)[1]))

        self.assertNotIn("superseded by", pretool(self.main, "git push origin main"))
        self.assertEqual("interrupted", runs(self.main)[peer]["state"])

    def test_a_run_owing_reconciliation_is_untouched(self) -> None:
        first = self.ok(start(self.main, ROOT, "src/module.py 의 가드를 고쳐줘"))
        old = run_id(first)
        transition_run(self.main, Path(detail(first, "evidence: ").split(": ", 1)[1]),
                       "reconcile_required", run_id=old)
        new, evidence = self.continued_in_worktree(old)
        self.finish(new, evidence)

        self.assertNotIn("superseded by", pretool(self.main, "git push origin main"))
        self.assertEqual("reconcile_required", runs(self.main)[old]["state"])


if __name__ == "__main__":
    unittest.main()
