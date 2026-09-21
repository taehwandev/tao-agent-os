from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import migrate_skill_bundles as migration


class SkillBundleMigrationTests(unittest.TestCase):
    def test_compact_entrypoint_keeps_detailed_rules_and_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "common/testing.md"
            source.parent.mkdir()
            related = root / "example.txt"
            related.write_text("fixture", encoding="utf-8")
            source.write_text(
                "---\nstatus: stable\ntype: human-reviewed\n---\n\n"
                "# Testing\n\nStop on a failed required check.\n\n"
                "[Fixture](../example.txt)\n",
                encoding="utf-8",
            )
            with patch.object(migration, "ROOT", root):
                migration.migrate_doc(source)
            skill = root / "common/skills/testing/SKILL.md"
            reference = skill.parent / "references/current-guidance.md"
            text = skill.read_text(encoding="utf-8")
            self.assertFalse(source.exists())
            self.assertLessEqual(len(text.encode()), 650)
            self.assertIn("references/current-guidance.md", text)
            self.assertIn("stop", text)
            self.assertIn("verification before acting", text)
            self.assertIn("in-scope", text)
            detailed = reference.read_text(encoding="utf-8")
            self.assertIn("status: stable", detailed)
            self.assertIn("Stop on a failed required check.", detailed)
            self.assertIn("[Fixture](../../../../example.txt)", detailed)

    def test_named_compatibility_stub_still_resolves_to_preserved_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "common/testing.md"
            source.parent.mkdir()
            original = "# Testing\n\nDo not report an unobserved check as passed.\n"
            source.write_text(original, encoding="utf-8")
            with patch.object(migration, "ROOT", root):
                migration.migrate_doc(source, keep_stub=True)
                migration.migrate_doc(source, keep_stub=True)
            self.assertIn(migration.STUB_MARKER, source.read_text())
            reference = root / "common/skills/testing/references/current-guidance.md"
            self.assertEqual(original, reference.read_text())


if __name__ == "__main__":
    unittest.main()
