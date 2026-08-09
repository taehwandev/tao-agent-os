"""Regression tests for complete React/RN external skill source coverage."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_react_rn_external_skill_manifest as checker


MANIFEST = (
    ROOT
    / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
)


class ReactRnExternalSkillManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_tracks_all_installable_and_nested_skills(self) -> None:
        entries = self.payload["skills"]
        paths = [entry["path"] for entry in entries]

        self.assertEqual(41, len(entries))
        self.assertEqual(41, len(set(paths)))
        self.assertEqual(32, sum(entry["installable"] for entry in entries))
        self.assertEqual(9, sum(not entry["installable"] for entry in entries))
        self.assertEqual(
            {"callstack", "expo", "software_mansion", "vercel"},
            {entry["provider"] for entry in entries},
        )

    def test_same_named_best_practices_sources_remain_provider_qualified(self) -> None:
        paths = {entry["path"] for entry in self.payload["skills"]}

        self.assertIn(
            "react-native/callstack/react-native-best-practices/SKILL.md",
            paths,
        )
        self.assertIn(
            "react-native/software-mansion/react-native-best-practices/SKILL.md",
            paths,
        )

    def test_checker_accepts_manifest_and_exact_source_inventory(self) -> None:
        expected = {
            entry["path"]: entry["sha256"] for entry in self.payload["skills"]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(checker, "_source_paths", return_value=expected):
                self.assertEqual(
                    0,
                    checker.main(
                        ["--manifest", str(MANIFEST), "--source-root", temp_dir]
                    ),
                )

    def test_checker_rejects_missing_unexpected_and_changed_sources(self) -> None:
        expected = {
            entry["path"]: entry["sha256"] for entry in self.payload["skills"]
        }
        missing_path = next(iter(expected))
        changed_path = next(path for path in expected if path != missing_path)
        actual = dict(expected)
        actual.pop(missing_path)
        actual[changed_path] = "0" * 64
        actual["react-native/unknown/SKILL.md"] = "1" * 64

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with patch.object(checker, "_source_paths", return_value=actual):
                with redirect_stdout(output):
                    result = checker.main(
                        ["--manifest", str(MANIFEST), "--source-root", temp_dir]
                    )

        self.assertEqual(1, result)
        self.assertIn(f"missing source skill: {missing_path}", output.getvalue())
        self.assertIn(f"source skill hash changed: {changed_path}", output.getvalue())
        self.assertIn(
            "unexpected source skill: react-native/unknown/SKILL.md",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
