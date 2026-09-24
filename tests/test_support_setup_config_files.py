from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import json
from unittest.mock import patch

from support import setup_config_files
from support.claude_setup import _merge_claude_statusline
from support.setup_config_files import (
    SetupConfigError,
    merge_codex_prefix_rules,
    merge_permissions_allow,
    read_json,
)


class JsonConfigSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Path(temporary.name) / "home" / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True)
        backed_up = patch.object(setup_config_files, "_backed_up", set())
        backed_up.start()
        self.addCleanup(backed_up.stop)

    def test_malformed_settings_stop_setup_and_stay_byte_identical(self) -> None:
        original = b'{"permissions": {"allow": ["Bash(ls)"]},, "model": "opus"\n'
        self.settings.write_bytes(original)
        for merge in (
            lambda: merge_permissions_allow(self.settings, ["Bash(tao-hook)"], dry_run=False),
            lambda: _merge_claude_statusline(self.settings, "tao-statusline", dry_run=False),
        ):
            with self.assertRaisesRegex(SetupConfigError, "not valid JSON"):
                merge()
        self.assertEqual(original, self.settings.read_bytes())
        self.assertFalse(self.settings.with_name("settings.json.tao-backup").exists())

    def test_non_object_settings_are_refused(self) -> None:
        self.settings.write_text("[1, 2]\n")
        with self.assertRaisesRegex(SetupConfigError, "JSON object"):
            read_json(self.settings)
        self.assertEqual({}, read_json(self.settings.with_name("absent.json")))

    def test_valid_settings_keep_user_keys_with_one_backup_and_atomic_replace(self) -> None:
        original = {"model": "opus", "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(.env)"]}}
        original_bytes = (json.dumps(original, indent=4) + "\n").encode()
        self.settings.write_bytes(original_bytes)
        replaced = []
        real_replace = setup_config_files.os.replace

        def spy(source, destination):
            replaced.append((Path(source).parent, Path(destination).name))
            return real_replace(source, destination)

        with patch.object(setup_config_files.os, "replace", side_effect=spy):
            merge_permissions_allow(self.settings, ["Bash(tao-hook)"], dry_run=False)
            _merge_claude_statusline(self.settings, "tao-statusline", dry_run=False)

        updated = json.loads(self.settings.read_text())
        self.assertEqual("opus", updated["model"])
        self.assertEqual(["Read(.env)"], updated["permissions"]["deny"])
        self.assertEqual(["Bash(ls)", "Bash(tao-hook)"], updated["permissions"]["allow"])
        self.assertEqual("command", updated["statusLine"]["type"])
        backup = self.settings.with_name("settings.json.tao-backup")
        self.assertEqual(original_bytes, backup.read_bytes())
        self.assertEqual(
            [(self.settings.parent, "settings.json.tao-backup"),
             (self.settings.parent, "settings.json"),
             (self.settings.parent, "settings.json")],
            replaced,
        )
        self.assertEqual([], list(self.settings.parent.glob("*.tmp")))

    def test_a_linked_settings_file_keeps_its_link(self) -> None:
        real = self.settings.parent.parent / "dotfiles-settings.json"
        real.write_text('{"model": "opus"}\n')
        self.settings.symlink_to(real)
        merge_permissions_allow(self.settings, ["Bash(tao-hook)"], dry_run=False)
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual("opus", json.loads(real.read_text())["model"])
        self.assertIn("Bash(tao-hook)", json.loads(real.read_text())["permissions"]["allow"])


class CodexPrefixRulesTests(unittest.TestCase):
    RULE = 'prefix_rule(pattern=["tao-hook"], decision="allow")'
    USER_RULE = 'prefix_rule(pattern=["user-tool"], decision="allow")'
    STALE_RULE = 'prefix_rule(pattern=["old-hook"], decision="allow")'

    def test_real_damage_is_repaired_without_moving_user_rules(self) -> None:
        for damage in ("missing_entry", "stale_entry", "duplicate_block", "outside_copy"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "default.rules"
                merge_codex_prefix_rules(target, [self.RULE], dry_run=False)
                block = target.read_text()
                damaged = {
                    "missing_entry": block.replace(self.RULE + "\n", ""),
                    "stale_entry": block.replace(self.RULE, self.STALE_RULE),
                    "duplicate_block": block + block,
                    "outside_copy": block + self.RULE + "\n" + self.STALE_RULE + "\n",
                }[damage]
                original = "# user prefix\n" + damaged + self.USER_RULE + "\n"
                target.write_text(original)
                options = {"cleanup_entries": [self.STALE_RULE]}

                self.assertEqual("missing", merge_codex_prefix_rules(
                    target, [self.RULE], dry_run=True, **options))
                self.assertEqual(original, target.read_text())
                self.assertEqual("installed", merge_codex_prefix_rules(
                    target, [self.RULE], dry_run=False, **options))
                self.assertEqual("# user prefix\n" + block + self.USER_RULE + "\n",
                                 target.read_text())
                self.assertEqual("ok", merge_codex_prefix_rules(
                    target, [self.RULE], dry_run=True, **options))

    def test_absent_block_is_added_after_unterminated_user_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "default.rules"
            target.write_text(self.USER_RULE)

            self.assertEqual("missing", merge_codex_prefix_rules(
                target, [self.RULE], dry_run=True))
            self.assertEqual(self.USER_RULE, target.read_text())
            self.assertEqual("installed", merge_codex_prefix_rules(
                target, [self.RULE], dry_run=False))
            self.assertTrue(target.read_text().startswith(self.USER_RULE + "\n"))
            self.assertEqual("ok", merge_codex_prefix_rules(
                target, [self.RULE], dry_run=True))
