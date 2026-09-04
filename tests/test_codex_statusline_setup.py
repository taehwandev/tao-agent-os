from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.codex_statusline_setup import merge_codex_status_line
from support.setup_agent_hooks_impl import configure_codex


class CodexStatusLineSetupTests(unittest.TestCase):
    def test_unset_status_line_keeps_codex_defaults_and_adds_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"

            first = merge_codex_status_line(target, dry_run=False)
            first_bytes = target.read_bytes()
            second = merge_codex_status_line(target, dry_run=False)
            second_bytes = target.read_bytes()

        self.assertEqual("installed", first)
        self.assertEqual("ok", second)
        self.assertEqual(first_bytes, second_bytes)
        self.assertIn(
            'status_line = ["model-with-reasoning", "current-dir", '
            '"five-hour-limit", "weekly-limit"]',
            first_bytes.decode(),
        )

    def test_existing_items_keep_order_and_are_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                '[tui]\nstatus_line = ["git-branch", "five-hour-limit"]\n'
                "status_line_use_colors = false\n\n[features]\nhooks = true\n",
                encoding="utf-8",
            )

            status = merge_codex_status_line(target, dry_run=False)
            written = target.read_text(encoding="utf-8")

        self.assertEqual("installed", status)
        self.assertIn(
            'status_line = ["git-branch", "five-hour-limit", "weekly-limit"]',
            written,
        )
        self.assertEqual(1, written.count('"five-hour-limit"'))
        self.assertEqual(1, written.count('"weekly-limit"'))
        self.assertIn("status_line_use_colors = false", written)
        self.assertIn("[features]\nhooks = true", written)

    def test_multiline_array_and_comments_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                "[tui]\nstatus_line = [\n"
                '  "model-with-reasoning" # keep the model visible\n'
                "]\n",
                encoding="utf-8",
            )

            status = merge_codex_status_line(target, dry_run=False)
            written = target.read_text(encoding="utf-8")

        self.assertEqual("installed", status)
        self.assertIn('"model-with-reasoning", # keep the model visible', written)
        self.assertIn('  "five-hour-limit", "weekly-limit"\n]', written)

    def test_dry_run_does_not_create_or_change_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"

            status = merge_codex_status_line(target, dry_run=True)

            self.assertEqual("would_update", status)
            self.assertFalse(target.exists())

    def test_existing_tui_subtable_receives_top_level_dotted_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                'model = "gpt-5"\n\n'
                "[tui.model_availability_nux]\n"
                '"gpt-5" = 3\n',
                encoding="utf-8",
            )

            status = merge_codex_status_line(target, dry_run=False)
            written = target.read_text(encoding="utf-8")

        self.assertEqual("installed", status)
        self.assertIn(
            'tui.status_line = ["model-with-reasoning", "current-dir", '
            '"five-hour-limit", "weekly-limit"]\n',
            written,
        )
        self.assertIn('[tui.model_availability_nux]\n"gpt-5" = 3\n', written)

    def test_unprovable_status_line_shape_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            original = '[tui]\nstatus_line = "model-with-reasoning"\n'
            target.write_text(original, encoding="utf-8")

            status = merge_codex_status_line(target, dry_run=False)

            self.assertEqual("missing", status)
            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_non_string_array_item_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            original = '[tui]\nstatus_line = ["model-with-reasoning", 7]\n'
            target.write_text(original, encoding="utf-8")

            status = merge_codex_status_line(target, dry_run=False)

            self.assertEqual("missing", status)
            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_codex_setup_reports_and_installs_the_quota_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch(
                "support.setup_agent_hooks_impl.Path.home",
                return_value=home,
            ):
                results = configure_codex(dry_run=False, root=ROOT)
            config = (home / ".codex" / "config.toml").read_text(encoding="utf-8")

        quota_result = next(
            result
            for result in results
            if result["hook"] == "statusLine"
        )
        self.assertEqual("installed", quota_result["status"])
        self.assertIn('"five-hour-limit"', config)
        self.assertIn('"weekly-limit"', config)


if __name__ == "__main__":
    unittest.main()
