"""A new request settles the session's earlier runs across one repository.

Reproduces a session that left a run paused (and resumed) in the main checkout,
did its next work in a linked worktree, and was then refused a publication from
the main checkout because the pre-tool gate reclaimed the old run and called it
"still open". The only way out was editing the run registry by hand. Every step
runs as a separate hook process against a disposable repository.
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
from agent_transfer_validate import _same_session
from test_work_continuity_lifecycle_e2e import (
    SESSION, TESTS_GATE, detail, environment, git, hook, record_gate, remaining_gates,
    run_id, start, turn_boundary,
)

_MODULE_STATE: list = []


def _build(project: Path) -> None:
    (project / "src").mkdir(parents=True)
    (project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    (project / "README.md").write_text("Baseline.\n", encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.email", "superseded@example.invalid")
    git(project, "config", "user.name", "Superseded")
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


def pretool_reason(cwd: Path, command: str) -> str:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "session_id": SESSION,
               "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "claude_pretool_gate.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        env={**environment(SESSION), "TAO_PRETOOL_RUNTIME": "claude"},
    )
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    return str(output.get("permissionDecisionReason") or "")


class SupersededSessionRunTests(unittest.TestCase):
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

    def resume(self, project: Path, run: str) -> None:
        self.ok(hook(project, ROOT, "resume", "--last", "--runtime", "claude",
                     "--runtime-session-id", SESSION, "--run-id", run))

    def paused_and_resumed_run(self, project: Path, request: str) -> str:
        """A run the Stop hook paused, the session resumed, and Stop paused again."""
        run = run_id(self.ok(start(project, ROOT, request)))
        self.ok(turn_boundary(project))
        self.resume(project, run)
        self.ok(turn_boundary(project))
        record = runs(project)[run]
        # A resumed run carries its generation in the binding; Stop still pauses it.
        self.assertEqual(("interrupted", 1), (record["state"], record["resume_generation"]))
        return run

    def test_new_request_in_a_linked_worktree_settles_the_paused_main_run(self) -> None:
        old = self.paused_and_resumed_run(self.main, "src/module.py 의 가드를 고쳐줘")
        (self.main / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
        peer = run_id(self.ok(start(self.main, ROOT, "다른 세션 작업", session="other-session")))
        git(self.main, "worktree", "add", "-q", str(self.linked), "-b", "fix/close")

        new = self.ok(start(self.linked, ROOT, "README 를 정리해줘"))

        self.assertIn("settled 1 superseded run(s)", new.stdout)
        self.assertIn(f"superseded run {old} left uncommitted work in its checkout", new.stdout)
        main_runs = runs(self.main)
        self.assertEqual("cancelled", main_runs[old]["state"])
        self.assertEqual(run_id(new), main_runs[old]["superseded_by"])
        self.assertEqual("running", main_runs[peer]["state"])
        self.assertEqual("value = 2\n", (self.main / "src" / "module.py").read_text())
        # The new work proceeds, and the main checkout no longer reclaims the
        # old run and refuses a publication there as "still open".
        gate = self.ok(record_gate(self.linked, ROOT, TESTS_GATE))
        self.assertNotIn("tests", remaining_gates(gate))
        self.assertNotIn("is still open", pretool_reason(self.main, "git push origin main"))
        self.assertEqual("cancelled", runs(self.main)[old]["state"])

    def test_a_continued_paused_run_is_never_settled(self) -> None:
        first = run_id(self.ok(start(self.main, ROOT, "src/module.py 의 가드를 고쳐줘")))
        self.ok(turn_boundary(self.main))

        follow = self.ok(start(self.main, ROOT, "이어서 해줘", "--continue-from", first))

        self.assertIn(f"work id: {first}", follow.stdout)
        self.assertEqual("interrupted", runs(self.main)[first]["state"])

    def test_a_failed_run_keeps_its_repair_record(self) -> None:
        git(self.main, "worktree", "add", "-q", str(self.linked), "-b", "fix/close")
        failed = run_id(self.ok(start(self.linked, ROOT, "src/module.py 의 가드를 고쳐줘")))
        self.assertEqual(1, hook(self.linked, ROOT, "finish").returncode)
        self.assertEqual("failed", runs(self.linked)[failed]["state"])

        new = self.ok(start(self.main, ROOT, "README 를 정리해줘"))

        self.assertNotIn("superseded run(s)", new.stdout)
        self.assertEqual("failed", runs(self.linked)[failed]["state"])

    def test_transfer_accepts_a_resumed_source_of_the_same_session(self) -> None:
        request = "같은 작업을 워크트리에서 끝냈어"
        source = self.paused_and_resumed_run(self.main, request)
        git(self.main, "worktree", "add", "-q", str(self.linked), "-b", "fix/close")
        # The same request elsewhere is a transfer, so the replacement's start
        # leaves the source for `cancel --replacement-evidence` to settle.
        replacement = self.ok(start(self.linked, ROOT, request))
        self.assertEqual("interrupted", runs(self.main)[source]["state"])
        replacement_evidence = Path(detail(replacement, "evidence: ").split(": ", 1)[1])
        transition_run(self.linked, replacement_evidence, "completed", run_id=run_id(replacement))

        settled = hook(
            self.main, ROOT, "cancel",
            "--evidence", str(self.main / ".tao" / "runs" / source / "preflight.json"),
            "--replacement-evidence", str(replacement_evidence),
        )

        self.assertNotIn("runtime sessions do not match", settled.stdout)
        self.assertEqual(0, settled.returncode, settled.stdout)
        self.assertIn("settled as cancelled", settled.stdout)
        self.assertEqual("cancelled", runs(self.main)[source]["state"])


class TransferSessionComparisonTests(unittest.TestCase):
    def test_generation_is_checked_per_run_and_sessions_must_match(self) -> None:
        stamped = {"runtime": "claude", "session_id": "s", "resume_generation": 4}
        bare = {"runtime": "claude", "session_id": "s"}
        self.assertTrue(_same_session(stamped, {"resume_generation": 4}, bare, {}))
        self.assertFalse(_same_session(stamped, {"resume_generation": 3}, bare, {}))
        self.assertFalse(_same_session(
            stamped, {"resume_generation": 4}, {**bare, "session_id": "other"}, {}))


if __name__ == "__main__":
    unittest.main()
