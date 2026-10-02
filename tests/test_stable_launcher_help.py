"""`tao-hook --help` lists the aliases instead of failing, and the gate reads it as a lookup."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "support"))

import claude_worktree_gate as gate
from stable_launcher import _launcher_script_text, stable_launcher_path


class LauncherHelpTests(unittest.TestCase):
    def test_help_prints_the_aliases_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / "tao-hook"
            launcher.write_text(_launcher_script_text(), encoding="utf-8")
            for flag in ("--help", "-h", "help"):
                with self.subTest(flag=flag):
                    result = subprocess.run([sys.executable, str(launcher), flag],
                                            capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("lifecycle: ", result.stdout)
                    self.assertIn("gate-batch", result.stdout)
                    self.assertNotIn("unsupported", result.stdout + result.stderr)

    def test_the_gate_reads_launcher_help_as_read_only(self) -> None:
        command = f"{stable_launcher_path()} --help"
        cwd, tokens, simple = gate.bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
        self.assertEqual("read_only", gate.bash_command_kind(tokens, simple, cwd))


if __name__ == "__main__":
    unittest.main()
