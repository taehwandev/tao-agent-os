"""An agent cannot approve its own project memory.

`project-memory approve` is how the user says a record was reviewed. Anything
the agent itself runs passes through PreToolUse, and the user's own `!`
commands do not, so refusing the approval there makes "approved" mean the user
approved it.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_pretool_gate as gate  # noqa: E402
from support.global_state import STATE_HOME_ENV  # noqa: E402


class ProjectMemoryApprovalIsTheUsersTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / "proj"
        (self.project / ".tao").mkdir(parents=True)
        (self.project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {STATE_HOME_ENV: str(self.base / "state")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _bash(self, command: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            gate.decide({
                "tool_name": "Bash",
                "cwd": str(self.project),
                "session_id": "memory-session",
                "tool_input": {"command": command},
            })
        return buffer.getvalue()

    def test_every_spelling_of_approve_is_refused(self) -> None:
        launcher = gate.stable_launcher_path()
        script = ROOT / "scripts" / "agent_project_memory.py"
        commands = (
            f"{launcher} project-memory --project {self.project} approve 0123456789abcdef --digest d",
            f"python3 {script} --project {self.project} approve 0123456789abcdef --digest d",
            f"cat README.md && {launcher} project-memory --project {self.project} approve 0123456789abcdef --digest d",
            f"bash -lc '{launcher} project-memory --project {self.project} approve 0123456789abcdef --digest d'",
            f"echo $({launcher} project-memory --project {self.project} approve 0123456789abcdef --digest d)",
            f"cd {self.base} ; python3 -m agent_project_memory --project {self.project} approve x --digest d",
        )
        for command in commands:
            with self.subTest(command=command):
                out = self._bash(command)
                self.assertTrue(out, "approve must be refused")
                decision = json.loads(out)["hookSpecificOutput"]
                self.assertEqual("deny", decision["permissionDecision"])
                self.assertIn("ask them to run the approve command themselves", decision["permissionDecisionReason"])

    def test_recall_capture_and_reads_are_not_refused_as_approval(self) -> None:
        launcher = gate.stable_launcher_path()
        for command in (
            f"{launcher} project-memory --project {self.project} recall --scope bugfix",
            f"grep -n approve {ROOT / 'scripts' / 'agent_project_memory.py'}",
            f"rg 'project-memory approve' {self.project}",
        ):
            with self.subTest(command=command):
                self.assertFalse(gate.approves_project_memory(command))
                self.assertNotIn(
                    "Tao project memory", self._bash(command),
                    "only approval is the user's",
                )


if __name__ == "__main__":
    unittest.main()
