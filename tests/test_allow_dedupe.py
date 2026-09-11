from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.setup_config_files import merge_permissions_allow


class AllowListKeepsOneCopyOfAnEntryTests(unittest.TestCase):
    """A repeated allow entry grants nothing and setup never removed it."""

    def _settings(self, allow: list[str]) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: [p.unlink() for p in directory.iterdir()] and directory.rmdir()
        )
        settings = directory / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": allow}}) + "\n")
        return settings

    def test_a_duplicated_entry_is_collapsed(self) -> None:
        # Another tool appending an entry the installer already owns leaves two
        # identical strings. Matching is set-like, so the copy grants nothing,
        # and the merge only ever appended what was absent -- so it stayed.
        managed = "Bash(tao-hook *)"
        settings = self._settings([managed, "Bash(custom-tool *)", managed])

        status = merge_permissions_allow(settings, [managed], dry_run=False)

        allow = json.loads(settings.read_text())["permissions"]["allow"]
        self.assertEqual(allow.count(managed), 1)
        self.assertIn("Bash(custom-tool *)", allow)
        self.assertEqual(status, "installed")

    def test_the_first_position_survives(self) -> None:
        # Order is how a reader finds an entry, so collapsing must not move the
        # surviving copy past entries that were already above it.
        managed = "Bash(tao-hook *)"
        settings = self._settings([managed, "Bash(a)", managed, "Bash(b)"])

        merge_permissions_allow(settings, [managed], dry_run=False)

        allow = json.loads(settings.read_text())["permissions"]["allow"]
        self.assertEqual(allow, [managed, "Bash(a)", "Bash(b)"])

    def test_a_duplicate_is_reported_without_writing_on_a_dry_run(self) -> None:
        managed = "Bash(tao-hook *)"
        settings = self._settings([managed, managed])
        before = settings.read_text()

        status = merge_permissions_allow(settings, [managed], dry_run=True)

        self.assertEqual(status, "would_update")
        self.assertEqual(settings.read_text(), before)

    def test_a_clean_list_is_still_reported_as_ok(self) -> None:
        managed = "Bash(tao-hook *)"
        settings = self._settings([managed, "Bash(custom-tool *)"])

        self.assertEqual(merge_permissions_allow(settings, [managed], dry_run=False), "ok")


if __name__ == "__main__":
    unittest.main()
