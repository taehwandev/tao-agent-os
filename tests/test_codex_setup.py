from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.claude_setup import _merge_claude_mailbox_delivery
from support.codex_setup import (
    merge_codex_mailbox_delivery, merge_codex_pre_tool_gate, merge_codex_stop_gate,
)


class MailboxDeliverySetupTests(unittest.TestCase):
    CODEX = "/stable/tao-hook mailbox-hook deliver --runtime codex"
    CLAUDE = "/stable/tao-hook mailbox-hook deliver --runtime claude"

    def _commands(self, target: Path) -> list[str]:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return [hook["command"] for group in payload["hooks"]["UserPromptSubmit"]
                for hook in group["hooks"]]

    def test_codex_delivery_sits_beside_other_prompt_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"
            target.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "other-prompt-hook"}]},
                {"hooks": [{"type": "command", "command": "/old/tao-hook mailbox-hook deliver --runtime codex"}]},
            ]}}), encoding="utf-8")
            first = merge_codex_mailbox_delivery(target, self.CODEX, dry_run=False)
            second = merge_codex_mailbox_delivery(target, self.CODEX, dry_run=False)
            commands = self._commands(target)
        self.assertEqual(("installed", "ok"), (first, second))
        self.assertEqual(["other-prompt-hook", self.CODEX], commands)

    def test_claude_delivery_sits_beside_the_route_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            target.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
                {"matcher": ".*", "hooks": [{"type": "command",
                                             "command": "tao-hook workflow route triage --advisory"}]},
            ]}}), encoding="utf-8")
            first = _merge_claude_mailbox_delivery(target, self.CLAUDE, dry_run=False)
            second = _merge_claude_mailbox_delivery(target, self.CLAUDE, dry_run=False)
            commands = self._commands(target)
        self.assertEqual(("installed", "ok"), (first, second))
        self.assertEqual(["tao-hook workflow route triage --advisory", self.CLAUDE], commands)

    def test_dry_run_reports_missing_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"
            self.assertEqual("missing", merge_codex_mailbox_delivery(target, self.CODEX, dry_run=True))
            self.assertFalse(target.exists())


class CodexSetupTests(unittest.TestCase):
    def test_pretool_refresh_adds_native_patch_without_replacing_other_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"
            command = "/stable/tao-hook codex-pretool-gate"
            other = {"matcher": ".*", "hooks": [{"type": "command", "command": "other-hook"}]}
            original = {"hooks": {"PreToolUse": [other, {
                "matcher": "Edit|Write|MultiEdit|ApplyPatch|Bash",
                "hooks": [{"type": "command", "command": command}],
            }]}}
            target.write_text(json.dumps(original))
            self.assertEqual("would_update", merge_codex_pre_tool_gate(target, command, True))
            self.assertEqual(original, json.loads(target.read_text()))
            self.assertEqual("installed", merge_codex_pre_tool_gate(target, command, False))
            self.assertEqual("ok", merge_codex_pre_tool_gate(target, command, False))
            groups = json.loads(target.read_text())["hooks"]["PreToolUse"]
            self.assertEqual(2, len(groups))
            self.assertEqual(other, groups[0])
            matcher = groups[1]["matcher"]
            for tool in ("apply_patch", "ApplyPatch", "Edit", "Write", "MultiEdit", "Bash"):
                self.assertIsNotNone(re.fullmatch(matcher, tool))
            self.assertEqual(command, groups[1]["hooks"][0]["command"])

    def test_stop_gate_preserves_unmanaged_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"
            target.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "node spill-stop.js",
                                            "timeout": 5,
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            first = merge_codex_stop_gate(
                target, "/stable/tao-hook codex-stop-gate", dry_run=False
            )
            second = merge_codex_stop_gate(
                target, "/stable/tao-hook codex-stop-gate", dry_run=False
            )
            payload = json.loads(target.read_text(encoding="utf-8"))

        commands = [
            hook["command"]
            for group in payload["hooks"]["Stop"]
            for hook in group["hooks"]
        ]
        self.assertEqual("installed", first)
        self.assertEqual("ok", second)
        self.assertEqual(
            ["node spill-stop.js", "/stable/tao-hook codex-stop-gate"],
            commands,
        )

    def test_dry_run_reports_missing_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"

            status = merge_codex_stop_gate(
                target, "/stable/tao-hook codex-stop-gate", dry_run=True
            )

            self.assertEqual("missing", status)
            self.assertFalse(target.exists())

    def test_stale_managed_hook_is_replaced_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hooks.json"
            target.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/old/tao-hook codex-stop-gate",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            status = merge_codex_stop_gate(
                target, "/stable/tao-hook codex-stop-gate", dry_run=False
            )
            payload = json.loads(target.read_text(encoding="utf-8"))

        commands = [
            hook["command"]
            for group in payload["hooks"]["Stop"]
            for hook in group["hooks"]
        ]
        self.assertEqual("installed", status)
        self.assertEqual(["/stable/tao-hook codex-stop-gate"], commands)


class CodexAgentIntegrationTests(unittest.TestCase):
    def test_runtime_setup_installs_roles_and_preserves_user_agent_policy(self) -> None:
        from support.setup_agent_hooks_impl import configure_codex

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            config = codex_dir / "config.toml"
            policy = '[agents]\nenabled = false\nmax_concurrent_threads_per_session = 1\n'
            config.write_text(policy, encoding="utf-8")
            hooks = codex_dir / "hooks.json"
            hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "node spill-stop.js"},
            ]}]}}), encoding="utf-8")

            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                first = configure_codex(False, root=ROOT)
                second = configure_codex(False, root=ROOT)

            for name in ("tao_explorer", "tao_worker", "tao_reviewer"):
                rows = [row for row in first if row["hook"] == f"agents.{name}"]
                self.assertEqual(1, len(rows))
                self.assertEqual("installed", rows[0]["status"])
                self.assertEqual(
                    (ROOT / "templates" / "codex-agents" / f"{name}.toml").read_text(),
                    (codex_dir / "agents" / f"{name}.toml").read_text(),
                )
                self.assertEqual("ok", next(
                    row["status"] for row in second if row["hook"] == f"agents.{name}"
                ))
            self.assertIn(policy, config.read_text())
            stop_commands = [hook["command"]
                             for group in json.loads(hooks.read_text())["hooks"]["Stop"]
                             for hook in group["hooks"]]
            self.assertIn("node spill-stop.js", stop_commands)

    def test_runtime_setup_dry_run_reports_roles_without_creating_them(self) -> None:
        from support.setup_agent_hooks_impl import configure_codex

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                results = configure_codex(True, root=ROOT)
            roles = [row for row in results if row["hook"].startswith("agents.")]
            self.assertEqual(3, len(roles))
            self.assertTrue(all(row["status"] == "missing" for row in roles))
            self.assertFalse((home / ".codex").exists())

    def test_runtime_setup_missing_templates_stops_before_config_writes(self) -> None:
        from support.setup_agent_hooks_impl import configure_codex

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                with self.assertRaises(FileNotFoundError):
                    configure_codex(False, root=Path(directory) / "missing-root")
            self.assertFalse(home.exists())

    def test_check_rejects_conflicting_role_when_other_setup_is_current(self) -> None:
        from support.setup_agent_hooks_impl import configure_codex, fail_if_setup_incomplete

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                configure_codex(False, root=ROOT)
                target = home / ".codex" / "agents" / "tao_worker.toml"
                user_role = 'name = "tao_worker"\n# user-owned role\n'
                target.write_text(user_role, encoding="utf-8")
                results = configure_codex(True, root=ROOT)
            self.assertFalse(any(row["status"] == "missing" for row in results))
            self.assertIn("conflict", [row["status"] for row in results])
            for check in (True, False):
                with self.subTest(check=check):
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exit_result:
                        fail_if_setup_incomplete(SimpleNamespace(check=check), results)
                    self.assertEqual(1, exit_result.exception.code)
            self.assertEqual(user_role, target.read_text())

    def test_check_rejects_stale_managed_role_without_refreshing_it(self) -> None:
        from support.codex_agent_setup import MANAGED_MARKER
        from support.setup_agent_hooks_impl import configure_codex, fail_if_setup_incomplete

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                configure_codex(False, root=ROOT)
                target = home / ".codex" / "agents" / "tao_worker.toml"
                stale = MANAGED_MARKER + '\nname = "tao_worker"\n'
                target.write_text(stale, encoding="utf-8")
                results = configure_codex(True, root=ROOT)
            self.assertFalse(any(row["status"] == "missing" for row in results))
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exit_result:
                fail_if_setup_incomplete(SimpleNamespace(check=True), results)
            self.assertEqual(1, exit_result.exception.code)
            self.assertEqual(stale, target.read_text())


if __name__ == "__main__":
    unittest.main()
