from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.claude_setup import _merge_claude_mailbox_delivery
from support.codex_setup import merge_codex_mailbox_delivery, merge_codex_stop_gate


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


if __name__ == "__main__":
    unittest.main()
