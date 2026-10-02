"""A Codex Bash call is judged in the workdir its transcript records, or not at all."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_exec_workdir import exec_workdir


def _code_call(code: str) -> dict:
    return {"type": "response_item",
            "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": code}}


class ExecWorkdirTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.worktree = self.base / "worktrees" / "CCE-1"
        self.other = self.base / "worktrees" / "CCE-2"
        self.worktree.mkdir(parents=True)
        self.other.mkdir(parents=True)

    def _payload(self, command: str, *rows: dict) -> dict:
        transcript = self.base / "rollout.jsonl"
        lines = [{"type": "session_meta", "payload": {"cwd": str(self.base)}}, *rows]
        transcript.write_text("\n".join(json.dumps(row) for row in lines) + "\n", encoding="utf-8")
        return {"cwd": str(self.base), "transcript_path": str(transcript),
                "tool_name": "Bash", "tool_input": {"command": command}}

    def test_a_code_mode_batch_maps_each_command_to_its_own_workdir(self) -> None:
        code = (
            "const r = await Promise.allSettled([\n"
            f'  tools.exec_command({{cmd:"adb -s A shell dumpsys package p | rg \'v=\'", workdir:"{self.worktree}"}}),\n'
            f'  tools.exec_command({{"cmd":"git status --short","workdir":"{self.other}"}}),\n'
            "]);"
        )
        payload = self._payload("adb -s A shell dumpsys package p | rg 'v='", _code_call(code))
        self.assertEqual(str(self.worktree), exec_workdir(payload))
        payload = self._payload("git status --short", _code_call(code))
        self.assertEqual(str(self.other), exec_workdir(payload))

    def test_escaped_quotes_in_the_command_still_match(self) -> None:
        command = 'rg -n "linkPreview" feature'
        code = f'await tools.exec_command({{cmd:{json.dumps(command)}, workdir:"{self.worktree}"}})'
        self.assertEqual(str(self.worktree), exec_workdir(self._payload(command, _code_call(code))))

    def test_a_classic_function_call_is_read_from_its_arguments(self) -> None:
        row = {"type": "response_item", "payload": {
            "type": "function_call", "name": "exec_command", "call_id": "c2",
            "arguments": json.dumps({"cmd": "pwd", "workdir": str(self.worktree)})}}
        self.assertEqual(str(self.worktree), exec_workdir(self._payload("pwd", row)))

    def test_uncertain_calls_fall_back_to_the_payload_cwd(self) -> None:
        same_command_two_dirs = (
            f'tools.exec_command({{cmd:"pwd", workdir:"{self.worktree}"}});'
            f'tools.exec_command({{cmd:"pwd", workdir:"{self.other}"}});'
        )
        cases = {
            "two workdirs for one command": self._payload("pwd", _code_call(same_command_two_dirs)),
            "no workdir named": self._payload("pwd", _code_call('tools.exec_command({cmd:"pwd"})')),
            "command not in the latest call": self._payload(
                "ls", _code_call(f'tools.exec_command({{cmd:"pwd", workdir:"{self.worktree}"}})')),
            "workdir that does not exist": self._payload(
                "pwd", _code_call(f'tools.exec_command({{cmd:"pwd", workdir:"{self.base}/gone"}})')),
            "relative workdir": self._payload(
                "pwd", _code_call('tools.exec_command({cmd:"pwd", workdir:"worktrees/CCE-1"})')),
        }
        for name, payload in cases.items():
            with self.subTest(name):
                self.assertIsNone(exec_workdir(payload))

    def test_only_the_newest_call_is_consulted(self) -> None:
        older = _code_call(f'tools.exec_command({{cmd:"pwd", workdir:"{self.worktree}"}})')
        newer = _code_call('tools.exec_command({cmd:"ls"})')
        self.assertIsNone(exec_workdir(self._payload("pwd", older, newer)))

    def test_an_unreadable_transcript_falls_back(self) -> None:
        payload = {"tool_input": {"command": "pwd"}, "transcript_path": str(self.base / "missing.jsonl")}
        self.assertIsNone(exec_workdir(payload))


class GateUsesTheExecWorkdirTests(unittest.TestCase):
    def test_codex_payload_cwd_is_replaced_and_claude_payload_is_not(self) -> None:
        import claude_pretool_gate as gate

        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory).resolve()
            transcript = worktree / "rollout.jsonl"
            code = f'tools.exec_command({{cmd:"pwd", workdir:"{worktree}"}})'
            transcript.write_text(json.dumps(_code_call(code)) + "\n", encoding="utf-8")
            payload = {"cwd": "/", "transcript_path": str(transcript),
                       "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "codex"}):
                self.assertEqual(str(worktree), gate._with_codex_exec_workdir(payload)["cwd"])
            with patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": "claude"}):
                self.assertEqual("/", gate._with_codex_exec_workdir(payload)["cwd"])


if __name__ == "__main__":
    unittest.main()
