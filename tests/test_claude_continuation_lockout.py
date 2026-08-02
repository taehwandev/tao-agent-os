"""The continuation adapter must never leave a session unable to edit.

Every case here failed as a hard denial of every subsequent edit before the
fix. They are grouped because they share one rule rather than one code path:
blocking a mutation is how the protocol stops a tool from running against a
checkpoint that would misdescribe it, so it is justified only when such a
checkpoint exists. A setup condition, a missing module, or a tool that never
ran produce no checkpoint to be wrong, and denying there costs the user the
editor they would need to fix it.

The suite's own history is the reason these run against a real `git init`
checkout driven through the real gate: the existing continuation tests use
non-git workspaces or hand-write `.gitignore` themselves, so all of them stayed
green while a fresh repository denied every edit.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_pretool_gate as gate
from agent_route_state import request_fingerprint
from agent_runtime_session import SESSION_ENV_VARS

SESSION_ID = "lockout-session"


def _decide(payload: dict) -> tuple[bool, str]:
    """Run the gate and report (allowed, reason). Silence is an allow."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        gate.decide(payload)
    raw = buffer.getvalue().strip()
    if not raw:
        return True, ""
    decision = json.loads(raw)["hookSpecificOutput"]
    allowed = decision.get("permissionDecision") != "deny"
    return allowed, decision.get("permissionDecisionReason", "")


class ContinuationLockoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.project = Path(self._temp.name).resolve()
        self.target = self.project / "module.py"
        self.target.write_text("value = 1\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "add", "-A"],
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
             "commit", "-q", "-m", "init"],
        ):
            subprocess.run(command, cwd=self.project, check=True)

        environment = dict(os.environ)
        for _, variable in SESSION_ENV_VARS:
            environment[variable] = SESSION_ID
        self.environment = environment
        request = "clear-exact: fix one named parser bug in module.py; blockers resolved"
        envelope = {
            "schema_version": 1,
            "request_fingerprint": request_fingerprint({"request": request}),
            "runtime_session_id": SESSION_ID,
            "mode": "work",
            "intent": "repair",
            "target_summary": "the named parser bug in module.py",
            "requested_effects": ["local_write"],
            "ambiguity": "resolved",
        }
        started = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "start",
             "--project", str(self.project), "--rules", str(ROOT),
             "--command", "bugfix", "--request", request,
             "--intent-envelope", json.dumps(envelope),
             "--runtime-session-id", SESSION_ID],
            capture_output=True, text=True, env=environment,
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)

    def _payload(self, *, tool: str = "Edit", key: str = "file_path") -> dict:
        return {
            "session_id": SESSION_ID,
            "cwd": str(self.project),
            "tool_name": tool,
            "tool_input": {key: str(self.target)},
        }

    def test_start_makes_the_state_directory_local_only(self) -> None:
        # The storage layer proves local-only status by asking Git. Nothing used
        # to create this file, so `check-ignore` answered "no" in every checkout
        # that had not been set up by hand.
        ignore = self.project / ".tao" / ".gitignore"
        self.assertTrue(ignore.is_file(), "start must establish the ignore rule")
        probe = subprocess.run(
            ["git", "check-ignore", "-q", str(self.project / ".tao" / "runs")],
            cwd=self.project, check=False,
        )
        self.assertEqual(0, probe.returncode, "the state root must be ignored")

    def test_fresh_repository_allows_the_first_edit(self) -> None:
        allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, reason)

    def test_existing_ignore_rules_are_not_replaced(self) -> None:
        # A project that already declared rules for this directory -- tracking a
        # skills subtree, as this repository does -- must keep them.
        ignore = self.project / ".tao" / ".gitignore"
        ignore.write_text("/*\n!/keep-me\n", encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "gate",
             "--project", str(self.project), "--rules", str(ROOT),
             "--gate-name", "reproduce", "--gate-evidence", "reproduced"],
            capture_output=True, text=True, env=self.environment, check=False,
        )
        self.assertIn("!/keep-me", ignore.read_text(encoding="utf-8"))

    def test_state_the_packet_cannot_be_stored_in_still_allows_editing(self) -> None:
        # `start` leaves an existing ignore file alone, so a project whose own
        # rules do not cover the run directory keeps a state root the packet
        # cannot legally be written to. Storage that cannot exist is not a
        # mutation running against a wrong checkpoint; there is no checkpoint.
        ignore = self.project / ".tao" / ".gitignore"
        ignore.write_text("/vibeguard-cache.json\n", encoding="utf-8")
        probe = subprocess.run(
            ["git", "check-ignore", "-q", str(self.project / ".tao" / "runs")],
            cwd=self.project, check=False,
        )
        self.assertNotEqual(0, probe.returncode, "fixture must leave runs unignored")
        allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, reason)

    def test_a_tool_that_never_ran_does_not_lock_out_later_edits(self) -> None:
        # A declined permission prompt leaves the pre-mutation checkpoint open,
        # because only PostToolUse clears it. Refusing forever on that basis
        # made one declined prompt end the session's ability to edit.
        allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, reason)
        allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, f"an unwritten pending must be superseded: {reason}")

    def test_an_open_pending_still_refuses_once_bytes_moved(self) -> None:
        # The negative control for the case above: same open pending, but the
        # tool did write. That needs reconciliation, not a fresh pending on top.
        allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, reason)
        self.target.write_text("value = 2\n", encoding="utf-8")
        allowed, reason = _decide(self._payload())
        self.assertFalse(allowed, "a written-but-unclosed mutation must refuse")
        self.assertIn("mutation_already_pending", reason)

    def test_notebook_edits_declare_their_target(self) -> None:
        # NotebookEdit names its target `notebook_path`. Reading only
        # `file_path` made every notebook edit look like a mutation with no
        # declared file, which the adapter refuses.
        notebook = self.project / "analysis.ipynb"
        notebook.write_text("{}\n", encoding="utf-8")
        self.target = notebook
        allowed, reason = _decide(
            self._payload(tool="NotebookEdit", key="notebook_path")
        )
        self.assertTrue(allowed, reason)

    def test_edits_outside_the_project_are_not_this_adapters_business(self) -> None:
        # Changed scope is project-local, so an edit elsewhere has no checkpoint
        # to contradict. Refusing it blocked every scratch file, runtime config,
        # and sibling checkout edited while a project run was open.
        outside = Path(self._temp.name).parent / "outside-the-project.txt"
        payload = self._payload()
        payload["tool_input"] = {"file_path": str(outside)}
        allowed, reason = _decide(payload)
        self.assertTrue(allowed, reason)

    def test_post_mutation_never_blocks_a_write_that_already_happened(self) -> None:
        # PostToolUse runs after the bytes landed, so a refusal cannot prevent
        # anything -- it only reports a successful write as a failed tool. An
        # unclosed bracket is already handled by resume refusing to treat those
        # bytes as verified progress.
        from claude_continuation_hook import ClaudeContinuationAdapter

        event = self._payload()
        event["hook_event_name"] = "PostToolUse"
        self.assertIsNone(
            ClaudeContinuationAdapter.run(event),
            "no pre-mutation bracket was opened, and post must still not block",
        )

    def test_a_missing_adapter_module_does_not_deny(self) -> None:
        # The gate promises never to fail to load. Denying every edit because an
        # import failed breaks that promise and removes the means of repair.
        with patch.object(gate, "ClaudeContinuationAdapter", None):
            allowed, reason = _decide(self._payload())
        self.assertTrue(allowed, reason)

    # The one denial the adapter keeps, and why it is the exception. Every case
    # above relaxes a refusal, so the boundary needs stating from the other side
    # too. Run evidence and the packet are the records the whole protocol
    # reasons from, and an agent rewriting them by hand is tampering with the
    # proof rather than doing work. This is also the one case where blocking
    # genuinely prevents something -- precisely what the relaxed cases lacked.

    def _run_evidence_dir(self) -> Path:
        return next((self.project / ".tao" / "runs").iterdir())

    def test_run_evidence_cannot_be_edited(self) -> None:
        self.target = self._run_evidence_dir() / "preflight.json"
        allowed, reason = _decide(self._payload())
        self.assertFalse(allowed)
        self.assertIn("project state", reason)

    def test_the_packet_cannot_be_edited(self) -> None:
        # Assert the reason, not just the refusal. Without the guard this path
        # still denies -- the packet write fails on its own once the adapter
        # tries to describe an edit to the packet -- so a bare assertFalse here
        # passes whether or not the boundary being tested exists at all.
        self.target = self._run_evidence_dir() / "continuation.json"
        allowed, reason = _decide(self._payload())
        self.assertFalse(allowed)
        self.assertIn("project state", reason)

    def test_a_symlink_into_project_state_is_resolved_first(self) -> None:
        # The check reads the resolved path, so an innocent name inside the
        # project cannot reach those records through the back door.
        link = self.project / "notes.py"
        link.symlink_to(self._run_evidence_dir() / "preflight.json")
        self.target = link
        allowed, reason = _decide(self._payload())
        self.assertFalse(allowed)
        self.assertIn("project state", reason)


if __name__ == "__main__":
    unittest.main()
