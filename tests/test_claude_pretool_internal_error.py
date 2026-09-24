"""The gate's own failures allow the call, but visibly and learned.

A crash inside the gate used to allow in silence, so a broken check looked
exactly like a passing one. These cases pin the replacement: the verdict is
still an allow (never an approval), the agent and user get one warning naming
only the exception type, and one content-free lesson is recorded per window.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claude_pretool_gate as gate  # noqa: E402

SECRET = "secret-message /Users/someone/private git push --force"


class InternalErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "state"
        self.cwd = Path(directory.name) / "work"
        self.cwd.mkdir()
        environment = patch.dict(
            os.environ,
            {"TAO_STATE_HOME": str(self.state), "TAO_PRETOOL_RUNTIME": "claude"},
        )
        environment.start()
        self.addCleanup(environment.stop)
        enabled = patch.object(gate, "gate_enabled", return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def payload(self) -> dict:
        return {
            "tool_name": "Bash",
            "cwd": str(self.cwd),
            "session_id": "crash-session",
            "tool_input": {"command": "git status"},
        }

    def decide(self) -> tuple[str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(0, gate.decide(self.payload()))
        return out.getvalue(), err.getvalue()

    def records(self) -> list[dict]:
        inbox = self.state / "lessons" / "inbox"
        return [json.loads(path.read_text(encoding="utf-8")) for path in inbox.glob("*.json")]

    def test_a_crash_allows_with_a_warning_and_one_content_free_lesson(self) -> None:
        with patch.object(gate, "_call_scope", side_effect=RuntimeError(SECRET)):
            out, _ = self.decide()

        answer = json.loads(out)
        specific = answer["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", specific)
        warning = specific["additionalContext"]
        self.assertEqual(warning, answer["systemMessage"])
        self.assertIn("internal error (RuntimeError)", warning)
        self.assertIn("the command was allowed", warning)
        self.assertIn("recorded for repair", warning)
        self.assertNotIn("secret-message", out)

        records = self.records()
        self.assertEqual(1, len(records))
        self.assertEqual("gate_internal_error", records[0]["root_cause"])
        self.assertEqual("report_gate_internal_error", records[0]["next_action"])
        stored = json.dumps(records)
        for fragment in ("secret-message", "/Users/someone", "git push", "RuntimeError", "crash-session"):
            self.assertNotIn(fragment, stored)

    def test_a_repeated_crash_in_the_window_records_once(self) -> None:
        with patch.object(gate, "_call_scope", side_effect=RuntimeError(SECRET)):
            first, _ = self.decide()
            second, _ = self.decide()
        self.assertEqual(first, second)
        records = self.records()
        self.assertEqual(1, len(records))
        self.assertEqual(1, records[0]["occurrence_count"])

    def test_codex_keeps_its_silent_deferral_and_warns_on_stderr(self) -> None:
        with (
            patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}),
            patch.object(gate, "_call_scope", side_effect=ValueError(SECRET)),
        ):
            out, err = self.decide()
        self.assertEqual("", out)
        self.assertIn("internal error (ValueError)", err)
        self.assertNotIn("secret-message", err)

    def test_an_unresolvable_cwd_warns_instead_of_allowing_silently(self) -> None:
        with patch.object(gate.Path, "resolve", side_effect=OSError(SECRET)):
            out, _ = self.decide()
        self.assertIn("internal error (OSError)", json.loads(out)["systemMessage"])

    def test_a_broken_install_warns_alongside_the_verdict(self) -> None:
        with patch.object(gate, "_BROKEN_INSTALL", "ModuleNotFoundError"):
            out, _ = self.decide()
        answer = json.loads(out)
        self.assertIn("internal error (ModuleNotFoundError)", answer["systemMessage"])
        self.assertIn("worktree policy is off", answer["systemMessage"])
        self.assertEqual(["gate_internal_error"], [r["root_cause"] for r in self.records()])

    def test_a_warning_joins_a_denial_in_one_document(self) -> None:
        gate._PENDING_WARNINGS.clear()
        gate._PENDING_WARNINGS.append("Tao gate hit an internal error (KeyError); x; y.")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            gate.deny("refused", "worktree_isolation")
        answer = json.loads(out.getvalue())
        self.assertEqual("deny", answer["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("KeyError", answer["hookSpecificOutput"]["additionalContext"])
        self.assertEqual([], gate._PENDING_WARNINGS)

    def test_a_sprawl_count_failure_is_skipped_and_reported(self) -> None:
        project = self.cwd
        with patch.object(gate, "write_target_path", side_effect=PermissionError(SECRET)):
            self.assertIsNone(
                gate.sprawl_deny("Write", {"tool_input": {}}, project, project, "s")
            )
        self.assertEqual(1, len(gate._PENDING_WARNINGS))
        self.assertIn("PermissionError", gate._PENDING_WARNINGS[0])
        gate._PENDING_WARNINGS.clear()

    def test_an_exception_name_that_is_not_an_identifier_is_not_repeated(self) -> None:
        gate._PENDING_WARNINGS.clear()
        gate._gate_internal_error("bad name; rm -rf /", "x")
        self.assertIn("(Exception)", gate._PENDING_WARNINGS[0])
        gate._PENDING_WARNINGS.clear()


if __name__ == "__main__":
    unittest.main()
