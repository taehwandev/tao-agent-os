"""Tao setup must edit only what Tao installed, and prove it rather than infer it.

Two products can configure the same runtime. Claude reads one `settings.json`
and Codex one config file, so every installer writes into a space it shares
with tools it knows nothing about. The rule these tests hold is narrow: an
entry may be rewritten or removed only when its provenance is readable -- a Tao
alias inside the command, or a marker block Tao emitted -- never because it
resembles something Tao would have written.

Resemblance is the specific trap. Tao's label bridge and a companion metering
tool's own hook can both carry the same environment prefix, sit on the same
event, and use a similar timeout. A predicate matching any of those signals
alone would delete a working install of the other product.

Fixtures here stay deliberately generic. Pinning another product's real binary
names or install paths would make these tests a stale mirror of something this
repository does not own, and would break them whenever that product moves.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support import claude_setup
from support.claude_setup import (
    _is_managed_claude_pre_tool_gate_command,
    _is_managed_claude_spill_bridge_command,
    _is_managed_claude_stop_gate_command,
    _merge_claude_stop_gate,
    _remove_claude_env,
    _set_claude_env,
)
from support.setup_config_files import merge_codex_prefix_rules

# Foreign hooks in the shapes that actually collide with Tao's predicates.
# FOREIGN_SHARED_PREFIX is the hard one: it carries the very environment prefix
# Tao also writes, so only the command after it distinguishes the two.
FOREIGN_SHARED_PREFIX = "SPILL_AI_TOOL=claude python3 '/opt/vendor-a/adapters/hook.py'"
FOREIGN_IMPORTER = "node /opt/vendor-a/adapters/importer.mjs --since-hours 6"
FOREIGN_STOP = "/opt/vendor-b/bin/tool hook --event Stop"
UNKNOWN_STOP = "/opt/vendor-c/bin/whatever --event Stop --flag"
TAO_STOP_GATE = "TAO_HOOK_SOFT_FAIL=1 '/Users/x/.tao/bin/tao-hook' claude-stop-gate"
TAO_LABEL_BRIDGE = "SPILL_AI_TOOL=claude tao-hook workflow route triage --advisory"


def _hook(command: str, timeout: int = 10) -> dict:
    return {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def _commands(settings: Path, event: str) -> list[str]:
    config = json.loads(settings.read_text(encoding="utf-8"))
    return [
        hook.get("command", "")
        for group in config.get("hooks", {}).get(event, [])
        for hook in group.get("hooks", [])
    ]


class OwnershipPredicateTests(unittest.TestCase):
    def test_no_predicate_claims_another_product(self) -> None:
        predicates = (
            _is_managed_claude_stop_gate_command,
            _is_managed_claude_pre_tool_gate_command,
            _is_managed_claude_spill_bridge_command,
        )
        for command in (FOREIGN_SHARED_PREFIX, FOREIGN_IMPORTER, FOREIGN_STOP, UNKNOWN_STOP):
            for predicate in predicates:
                with self.subTest(command=command[:40], predicate=predicate.__name__):
                    self.assertFalse(predicate(command))

    def test_the_label_bridge_needs_more_than_the_shared_env_prefix(self) -> None:
        # A companion tool's hook carries the same prefix. Ownership rests on the
        # Tao route command that follows it, not on the prefix.
        self.assertTrue(_is_managed_claude_spill_bridge_command(TAO_LABEL_BRIDGE))
        self.assertFalse(_is_managed_claude_spill_bridge_command(FOREIGN_SHARED_PREFIX))


class _SettingsFixture:
    """Shared fixture only. Kept off `TestCase` so subclasses do not re-run it."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        home = Path(self._temp.name)
        self.settings = home / "settings.json"
        self.state = home / "tao-state"
        patcher = patch.object(claude_setup, "global_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, config: dict) -> None:
        self.settings.write_text(json.dumps(config, indent=2), encoding="utf-8")


class ClaudeSettingsMergeTests(_SettingsFixture, unittest.TestCase):
    def test_installing_preserves_every_foreign_stop_hook(self) -> None:
        self._write({
            "hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5), _hook(FOREIGN_STOP, 5),
                               _hook(UNKNOWN_STOP)]},
            "model": "opus",
        })
        _merge_claude_stop_gate(self.settings, TAO_STOP_GATE, dry_run=False)
        after = _commands(self.settings, "Stop")
        for command in (FOREIGN_SHARED_PREFIX, FOREIGN_STOP, UNKNOWN_STOP):
            self.assertIn(command, after)
        self.assertIn(TAO_STOP_GATE, after)

    def test_unrelated_keys_and_user_settings_survive(self) -> None:
        self._write({
            "hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5)]},
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
            "statusLine": {"type": "command", "command": "mine"},
        })
        _merge_claude_stop_gate(self.settings, TAO_STOP_GATE, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("opus", config["model"])
        self.assertEqual(["Bash(ls:*)"], config["permissions"]["allow"])
        self.assertEqual("mine", config["statusLine"]["command"])

    def test_repeated_setup_does_not_duplicate(self) -> None:
        self._write({"hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5)]}})
        for _ in range(3):
            _merge_claude_stop_gate(self.settings, TAO_STOP_GATE, dry_run=False)
        after = _commands(self.settings, "Stop")
        self.assertEqual(1, after.count(TAO_STOP_GATE))
        self.assertEqual(1, after.count(FOREIGN_SHARED_PREFIX))

    def test_a_tao_hook_sharing_a_group_with_a_foreign_hook_is_removed_alone(self) -> None:
        # Removal is per hook object. Dropping the enclosing group would take a
        # neighbouring product's hook with it.
        self._write({"hooks": {"Stop": [{
            "matcher": "",
            "hooks": [
                {"type": "command", "command": TAO_STOP_GATE, "timeout": 10},
                {"type": "command", "command": FOREIGN_SHARED_PREFIX, "timeout": 5},
            ],
        }]}})
        _merge_claude_stop_gate(self.settings, TAO_STOP_GATE + " --updated", dry_run=False)
        after = _commands(self.settings, "Stop")
        self.assertIn(FOREIGN_SHARED_PREFIX, after)
        self.assertNotIn(TAO_STOP_GATE, after)


class RuntimeEnvOwnershipTests(_SettingsFixture, unittest.TestCase):
    def test_env_written_by_another_product_is_not_removed(self) -> None:
        # The removal path fires when Tao cannot find the companion tool's
        # setup helper, which is weaker than that tool being gone -- a moved or
        # restructured install looks identical. With no record that Tao wrote
        # these keys, a matching value is a resemblance, not a receipt.
        self._write({"env": {"SPILL_AI_TOOL": "claude", "SPILL_TOKEN_USAGE_AI_TOOL": "claude"}})
        status = _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("ok", status)
        self.assertEqual("claude", config["env"]["SPILL_AI_TOOL"])

    def test_env_this_installer_wrote_is_removed(self) -> None:
        self._write({"env": {"EDITOR": "vim"}})
        _set_claude_env(self.settings, dry_run=False)
        _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("SPILL_AI_TOOL", config.get("env", {}))
        self.assertEqual("vim", config["env"]["EDITOR"])

    def test_a_key_that_already_existed_is_left_behind(self) -> None:
        # Tao refreshes the pair, but only the key it introduced is its own.
        self._write({"env": {"SPILL_AI_TOOL": "claude"}})
        _set_claude_env(self.settings, dry_run=False)
        _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("claude", config["env"]["SPILL_AI_TOOL"])


class CodexMarkerBlockTests(unittest.TestCase):
    def test_foreign_config_outside_the_marker_block_survives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                'model = "gpt-5"\n'
                '[hooks]\n'
                f'stop = "{FOREIGN_IMPORTER}"\n',
                encoding="utf-8",
            )
            for _ in range(3):
                merge_codex_prefix_rules(config, ['"tao-hook"'], dry_run=False)
            text = config.read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5"', text)
            self.assertIn(FOREIGN_IMPORTER, text)
            self.assertEqual(1, text.count("# tao-hooks:begin"))
            self.assertEqual(1, text.count('"tao-hook"'))


if __name__ == "__main__":
    unittest.main()
