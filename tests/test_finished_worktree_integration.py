"""A finished worktree run admits the fast-forward that brings it home.

The goal loop finishes in `<repo>/.tao/worktrees/<slice>` and then runs
`git -C <repo> merge --ff-only <sha>`. That merge used to need a second
lifecycle in the main checkout, because publication admission covered only
add/commit/push/tag and looked the finish up against the checkout the command
names rather than the worktree that held the run.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# This checkout's `tests` package, not whichever one the shell happens to sit
# in: the suite runs from a linked worktree beside the main checkout, and both
# hold a directory of this name.
sys.path.insert(0, str(ROOT))

import importlib.util

import claude_pretool_gate as gate
from agent_publication_admission import PublicationAdmission
from agent_run_registry import transition_run
from agent_runtime_session import resolve_runtime_evidence
from support.global_state import STATE_HOME_ENV

from tests.test_claude_pretool_gate import _write_preflight

_HOOK_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_fast_forward_line", ROOT / "scripts" / "agent-hook.py"
)
agent_hook = importlib.util.module_from_spec(_HOOK_SPEC)
_HOOK_SPEC.loader.exec_module(agent_hook)


_STATE_HOME: "tempfile.TemporaryDirectory | None" = None
_OUTER_STATE_HOME: "str | None" = None


def setUpModule() -> None:
    """Keep the session-project index out of the developer's own `~/.tao`."""

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


def _gate_environment() -> dict:
    """Only what the gate needs to run, so no ambient hint decides a verdict.

    `PATH` and `HOME` stay because the admission shells out to git and reads
    the host-config rule against the home directory; clearing them would make
    every repository read fail for a reason the case is not about.
    """

    kept = {
        name: os.environ[name]
        for name in ("PATH", "HOME", STATE_HOME_ENV)
        if name in os.environ
    }
    return kept


class FinishedWorktreeIntegrationTests(unittest.TestCase):
    """The admission itself: one repository, one finished worktree, one commit."""

    SESSION = "worktree-finish-session"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.main = (Path(self.temp.name).resolve() / "main")
        self.main.mkdir()
        self.git(self.main, "init", "-q", "-b", "main")
        self.git(self.main, "config", "user.email", "test@example.invalid")
        self.git(self.main, "config", "user.name", "Test")
        (self.main / ".gitignore").write_text(".tao/\n")
        (self.main / "AGENTS.md").write_text("uses tao-hook\n")
        (self.main / "source").write_text("original")
        self.git(self.main, "add", ".")
        self.git(self.main, "commit", "-qm", "base")
        self.worktree = self.main / ".tao" / "worktrees" / "slice"
        self.git(self.main, "worktree", "add", "-q", "-b", "slice", str(self.worktree))
        self.worktree = self.worktree.resolve()
        self.evidence = self.worktree / ".tao" / "runs" / "example" / "preflight.json"
        self.evidence.parent.mkdir(parents=True)

    def git(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True, capture_output=True, text=True,
        ).stdout

    def finish(self, effect: str = "git_write") -> bool:
        """Write the receipt a passing finish writes, for the given route effect."""

        self.evidence.write_text(json.dumps({
            "rules": str(self.worktree),
            "route": {"request_classification": {"intent_envelope": {
                "authority": "envelope", "schema_valid": True,
                "failures": [], "effective_effect": effect,
            }}},
        }))
        return PublicationAdmission.record_finish(self.worktree, self.evidence)

    def slice_commit(self) -> str:
        """The reviewed change, attested, then committed exactly as finished."""

        (self.worktree / "source").write_text("reviewed change")
        assert self.finish()
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        return self.git(self.worktree, "rev-parse", "HEAD").strip()

    def evidence_lookup(self, root: Path, session_id: str) -> "Path | None":
        if Path(root).resolve() == self.worktree and session_id == self.SESSION:
            return self.evidence
        return None

    def admits(self, command: str, cwd: "Path | None" = None) -> bool:
        tokens = shlex.split(command)
        with patch.object(gate, "finished_session_evidence", self.evidence_lookup):
            return gate.publishes_finished_work(
                self.main, self.SESSION, tokens, cwd if cwd is not None else self.worktree
            )

    def admits_command(self, command: str, cwd: "Path | None" = None) -> bool:
        with patch.object(gate, "finished_session_evidence", self.evidence_lookup):
            return gate.publishes_finished_command(
                self.main, self.SESSION, command,
                cwd if cwd is not None else self.worktree,
            )

    def test_fast_forward_of_the_finished_commit_is_admitted(self) -> None:
        sha = self.slice_commit()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertTrue(self.admits(command))
        self.assertTrue(self.admits_command(command))

    def test_the_branch_name_names_the_same_commit(self) -> None:
        self.slice_commit()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only slice"

        self.assertTrue(self.admits(command))
        self.assertTrue(self.admits_command(command))

    def test_quiet_and_no_edit_stay_the_same_reference_move(self) -> None:
        sha = self.slice_commit()
        target = shlex.quote(str(self.main))

        for command in (
            f"git -C {target} merge --ff-only -q {sha}",
            f"git -C {target} merge --quiet --ff-only {sha}",
            f"git -C {target} merge --ff-only --no-edit {sha}",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.admits(command))

    def test_the_admission_holds_when_the_shell_sits_in_the_main_checkout(self) -> None:
        sha = self.slice_commit()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertTrue(self.admits(command, cwd=self.main))

    def test_an_edit_after_finish_is_refused(self) -> None:
        sha = self.slice_commit()
        (self.worktree / "source").write_text("unreviewed")
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))
        self.assertFalse(self.admits_command(command))

    def test_an_untracked_file_after_finish_is_refused(self) -> None:
        """A clean worktree is what binds the commit to the attested bytes."""

        sha = self.slice_commit()
        (self.worktree / "scratch.py").write_text("print('x')\n")
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))

    def test_a_worktree_that_moved_past_the_commit_is_refused(self) -> None:
        sha = self.slice_commit()
        (self.worktree / "source").write_text("later work")
        self.git(self.worktree, "commit", "-qam", "after the finish")
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))

    def test_a_diverged_target_is_refused(self) -> None:
        """`--ff-only` would fail there, and the gate must not say otherwise."""

        sha = self.slice_commit()
        (self.main / "other").write_text("main moved on")
        self.git(self.main, "add", "-A")
        self.git(self.main, "commit", "-qm", "main work")
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))

    def test_autostash_over_leftovers_the_commit_already_holds_is_admitted(self) -> None:
        """A run that began in main leaves its own edits there; they are in the commit."""

        (self.main / "source").write_text("original\nsecond\n")
        self.git(self.main, "commit", "-qam", "two lines")
        self.git(self.worktree, "merge", "-q", "--ff-only", "main")
        (self.worktree / "source").write_text("changed\nsecond\nthird\n")
        assert self.finish()
        self.git(self.worktree, "commit", "-qam", "slice work")
        sha = self.git(self.worktree, "rev-parse", "HEAD").strip()
        # Part of the reviewed change, left behind before the move.
        (self.main / "source").write_text("changed\nsecond\n")
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only --autostash {sha}"

        self.assertTrue(self.admits(command))
        self.assertTrue(self.admits_command(command))
        self.git(self.main, "merge", "-q", "--ff-only", "--autostash", sha)
        self.assertEqual("", self.git(self.main, "status", "--porcelain", "--untracked-files=no"))

    def test_autostash_over_a_change_the_commit_lacks_is_refused(self) -> None:
        sha = self.slice_commit()
        target = shlex.quote(str(self.main))

        (self.main / "source").write_text("someone else's work")
        self.assertFalse(self.admits(f"git -C {target} merge --ff-only --autostash {sha}"))
        self.git(self.main, "checkout", "--", "source")
        (self.main / "AGENTS.md").write_text("another session's edit\n")
        self.assertFalse(self.admits(f"git -C {target} merge --ff-only --autostash {sha}"))
        self.git(self.main, "checkout", "--", "AGENTS.md")
        (self.main / "source").unlink()
        self.assertFalse(self.admits(f"git -C {target} merge --ff-only --autostash {sha}"))

    def test_autostash_needs_the_fast_forward_flag(self) -> None:
        sha = self.slice_commit()

        self.assertFalse(self.admits(f"git -C {shlex.quote(str(self.main))} merge --autostash {sha}"))

    def test_an_already_integrated_commit_is_still_admitted(self) -> None:
        """Target HEAD equal to the commit is a no-op, not a divergence."""

        sha = self.slice_commit()
        self.git(self.main, "merge", "--ff-only", sha)
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertTrue(self.admits(command))

    def test_every_other_integration_shape_is_refused(self) -> None:
        sha = self.slice_commit()
        target = shlex.quote(str(self.main))

        for command in (
            f"git -C {target} merge {sha}",
            f"git -C {target} merge --no-ff {sha}",
            f"git -C {target} merge --ff-only --no-commit {sha}",
            f"git -C {target} merge --ff-only {sha} extra",
            f"git -C {target} merge --ff-only",
            f"git -C {target} rebase {sha}",
            f"git -C {target} pull --ff-only origin slice",
            f"git -C {target} merge --ff-only -m subject {sha}",
            f"git --git-dir={target}/.git merge --ff-only {sha}",
        ):
            with self.subTest(command=command):
                self.assertFalse(self.admits(command))
                self.assertFalse(self.admits_command(command))

    def test_a_chained_write_beside_the_merge_is_refused(self) -> None:
        sha = self.slice_commit()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertTrue(self.admits_command(f"{command} && git -C {shlex.quote(str(self.main))} log --oneline -1"))
        self.assertFalse(self.admits_command(f"{command} && touch extra"))

    def test_a_read_route_finish_creates_no_integration_authority(self) -> None:
        (self.worktree / "source").write_text("reviewed change")
        self.assertFalse(self.finish("read"))
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        sha = self.git(self.worktree, "rev-parse", "HEAD").strip()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))

    def test_another_session_cannot_reuse_this_finish(self) -> None:
        sha = self.slice_commit()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"
        tokens = shlex.split(command)

        with patch.object(gate, "finished_session_evidence", self.evidence_lookup):
            self.assertFalse(
                gate.publishes_finished_work(
                    self.main, "some-other-session", tokens, self.worktree
                )
            )

    def test_no_finished_run_anywhere_is_refused(self) -> None:
        (self.worktree / "source").write_text("unattested change")
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        sha = self.git(self.worktree, "rev-parse", "HEAD").strip()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        self.assertFalse(self.admits(command))


class FinishedWorktreeIntegrationGateTests(unittest.TestCase):
    """The same act through the real PreToolUse entry, from both directories."""

    SESSION = "goal-loop-session"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.main = (Path(self.temp.name).resolve() / "repo")
        self.main.mkdir()
        self.git(self.main, "init", "-q", "-b", "main")
        self.git(self.main, "config", "user.email", "test@example.invalid")
        self.git(self.main, "config", "user.name", "Test")
        (self.main / ".gitignore").write_text(".tao/\n")
        (self.main / "AGENTS.md").write_text("uses tao-hook\n")
        (self.main / "source").write_text("original")
        self.git(self.main, "add", ".")
        self.git(self.main, "commit", "-qm", "base")
        self.worktree = self.main / ".tao" / "worktrees" / "slice"
        self.git(self.main, "worktree", "add", "-q", "-b", "slice", str(self.worktree))
        self.worktree = self.worktree.resolve()

    def git(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True, capture_output=True, text=True,
        ).stdout

    def finish_the_slice(self) -> str:
        """Run the lifecycle the way the loop does: work, finish, commit."""

        _write_preflight(self.worktree, self.SESSION)
        evidence = resolve_runtime_evidence(
            self.worktree, {"runtime": "claude", "session_id": self.SESSION}
        )
        assert evidence is not None
        (self.worktree / "source").write_text("reviewed change")
        transition_run(self.worktree, evidence, "completed")
        payload = json.loads(evidence.read_text())
        payload["route"]["request_classification"] = {"intent_envelope": {
            "authority": "envelope", "schema_valid": True, "failures": [],
            "effective_effect": "git_write",
        }}
        evidence.write_text(json.dumps(payload))
        assert PublicationAdmission.record_finish(self.worktree, evidence)
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        return self.git(self.worktree, "rev-parse", "HEAD").strip()

    def decide(self, cwd: Path, command: str) -> tuple[int, str]:
        payload = {
            "tool_name": "Bash",
            "cwd": str(cwd),
            "session_id": self.SESSION,
            "tool_input": {"command": command},
        }
        buffer = io.StringIO()
        with patch.dict(os.environ, _gate_environment(), clear=True):
            with redirect_stdout(buffer):
                code = gate.decide(payload)
        return code, buffer.getvalue()

    def reason(self, out: str) -> str:
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_an_unattested_fast_forward_still_needs_workflow_entry(self) -> None:
        """The premise: this refusal is what forced the second lifecycle."""

        (self.worktree / "source").write_text("unattested change")
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        sha = self.git(self.worktree, "rev-parse", "HEAD").strip()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        for cwd in (self.worktree, self.main):
            with self.subTest(cwd=str(cwd)):
                code, out = self.decide(cwd, command)
                self.assertEqual(0, code)
                self.assertIn("run the workflow start hook", self.reason(out))

    def test_the_finish_admits_the_fast_forward_from_either_directory(self) -> None:
        sha = self.finish_the_slice()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}"

        for cwd in (self.worktree, self.main):
            with self.subTest(cwd=str(cwd)):
                code, out = self.decide(cwd, command)
                self.assertEqual(0, code)
                decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
                self.assertEqual("allow", decision)
                self.assertIn("a successful finish", self.reason(out))

    def test_head_from_the_worktree_is_refused_with_the_exact_command(self) -> None:
        """`HEAD` there names main's own HEAD; the refusal names the commit to use."""

        sha = self.finish_the_slice()
        command = f"git -C {shlex.quote(str(self.main))} merge --ff-only HEAD"

        code, out = self.decide(self.worktree, command)

        self.assertEqual(0, code)
        reason = self.reason(out)
        self.assertIn("HEAD is", reason)
        self.assertIn(f"merge --ff-only {sha}", reason)
        code, out = self.decide(self.worktree, f"git -C {shlex.quote(str(self.main))} merge --ff-only {sha}")
        self.assertEqual("allow", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_copying_out_of_every_project_is_not_a_project_write(self) -> None:
        """A user's recording copied to the session scratchpad touches no project."""

        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(outside)], check=False))
        (outside / "recording.mov").write_bytes(b"movie")
        scratch = outside / "scratchpad"
        scratch.mkdir()
        cases = {
            f"cp {shlex.quote(str(outside / 'recording.mov'))} {shlex.quote(str(scratch / 'rec.mov'))}": True,
            f"cp -p {shlex.quote(str(self.main / 'source'))} {shlex.quote(str(scratch))}": True,
            f"cp {shlex.quote(str(outside / 'recording.mov'))} {shlex.quote(str(self.main / 'rec.mov'))}": False,
            f"cp -l {shlex.quote(str(self.main / 'source'))} {shlex.quote(str(scratch / 'link'))}": False,
            f"cp -t {shlex.quote(str(self.main))} {shlex.quote(str(outside / 'recording.mov'))}": False,
            f"mkdir -p {shlex.quote(str(scratch / 'frames'))}": True,
            f"mkdir {shlex.quote(str(self.main / 'frames'))}": False,
            f'mdfind -name "Screen Recording"; defaults read com.apple.screencapture location': True,
        }
        for command, admitted in cases.items():
            with self.subTest(command=command):
                code, out = self.decide(self.main, command)
                self.assertEqual(0, code)
                refused = bool(out) and "run the workflow start hook" in self.reason(out)
                self.assertEqual(not admitted, refused, out)

    def test_finish_names_the_main_checkout_and_the_commit(self) -> None:
        line = agent_hook._fast_forward_line(self.worktree)
        self.assertIn(f"git -C {self.main} merge --ff-only <the commit sha>", line)
        sha = self.finish_the_slice()
        line = agent_hook._fast_forward_line(self.worktree)
        self.assertIn(f"git -C {self.main} merge --ff-only {sha}", line)
        self.assertIn("never `HEAD`", line)
        self.assertEqual("", agent_hook._fast_forward_line(self.main))

    def test_the_finish_does_not_admit_a_plain_merge(self) -> None:
        sha = self.finish_the_slice()
        command = f"git -C {shlex.quote(str(self.main))} merge --no-ff {sha}"

        code, out = self.decide(self.worktree, command)

        self.assertEqual(0, code)
        self.assertIn("run the workflow start hook", self.reason(out))


if __name__ == "__main__":
    unittest.main()
