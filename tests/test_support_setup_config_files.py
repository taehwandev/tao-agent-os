from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from support.setup_config_files import merge_codex_prefix_rules


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
