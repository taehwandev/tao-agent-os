"""Regression tests for complete React/RN external skill source coverage."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


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

    def _synthetic_snapshot(
        self, temp_root: Path
    ) -> tuple[Path, Path, dict[str, str]]:
        payload = copy.deepcopy(self.payload)
        source_root = temp_root / "source"
        expected: dict[str, str] = {}
        for index, entry in enumerate(payload["skills"]):
            content = f"synthetic skill {index}\n".encode()
            source_path = source_root / entry["path"]
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            entry["sha256"] = digest
            expected[entry["path"]] = digest
        (source_root / "README.md").write_text("ignored\n", encoding="utf-8")
        manifest = temp_root / "source-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return manifest, source_root, expected

    def test_source_paths_recurses_and_hashes_only_skill_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            top_level = source_root / "react" / "SKILL.md"
            nested = source_root / "react-native" / "nested" / "SKILL.md"
            top_level.parent.mkdir(parents=True)
            nested.parent.mkdir(parents=True)
            top_level.write_bytes(b"")
            nested.write_bytes(b"abc")
            (nested.parent / "README.md").write_text("ignored", encoding="utf-8")

            self.assertEqual(
                {
                    "react-native/nested/SKILL.md": (
                        "ba7816bf8f01cfea414140de5dae2223"
                        "b00361a396177a9cb410ff61f20015ad"
                    ),
                    "react/SKILL.md": (
                        "e3b0c44298fc1c149afbf4c8996fb924"
                        "27ae41e4649b934ca495991b7852b855"
                    ),
                },
                checker._source_paths(source_root),
            )

    def test_checker_accepts_manifest_and_exact_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest, source_root, expected = self._synthetic_snapshot(Path(temp_dir))
            output = io.StringIO()
            with redirect_stdout(output):
                result = checker.main(
                    ["--manifest", str(manifest), "--source-root", str(source_root)]
                )
            self.assertEqual(expected, checker._source_paths(source_root))

        self.assertEqual(41, len(expected))
        self.assertEqual(0, result)
        self.assertIn("41 SKILL.md files (32 installable, 9 nested)", output.getvalue())

    def test_checker_rejects_missing_unexpected_and_changed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest, source_root, expected = self._synthetic_snapshot(Path(temp_dir))
            missing_path = next(iter(expected))
            changed_path = next(path for path in expected if path != missing_path)
            (source_root / missing_path).unlink()
            (source_root / changed_path).write_text("changed\n", encoding="utf-8")
            unexpected = source_root / "react-native" / "unknown" / "SKILL.md"
            unexpected.parent.mkdir(parents=True)
            unexpected.write_text("unexpected\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = checker.main(
                    ["--manifest", str(manifest), "--source-root", str(source_root)]
                )

        self.assertEqual(1, result)
        self.assertIn(f"missing source skill: {missing_path}", output.getvalue())
        self.assertIn(f"source skill hash changed: {changed_path}", output.getvalue())
        self.assertIn(
            "unexpected source skill: react-native/unknown/SKILL.md",
            output.getvalue(),
        )

    def test_manifest_contract_rejects_each_invalid_variant(self) -> None:
        cases = (
            (
                "entry missing",
                lambda payload: payload["skills"].pop(),
                "manifest must contain 41 unique SKILL.md paths",
            ),
            (
                "duplicate path",
                lambda payload: payload["skills"][1].update(
                    path=payload["skills"][0]["path"]
                ),
                "manifest must contain 41 unique SKILL.md paths",
            ),
            (
                "sort order",
                lambda payload: payload["skills"].reverse(),
                "manifest SKILL.md paths must stay sorted",
            ),
            (
                "installable count",
                lambda payload: payload["skills"][0].update(
                    installable=not payload["skills"][0]["installable"]
                ),
                "manifest must identify exactly 32 installable skills",
            ),
            (
                "known provider replacement",
                lambda payload: payload["skills"][0].update(provider="expo"),
                "installable provider counts must remain",
            ),
            (
                "unknown provider",
                lambda payload: payload["skills"][0].update(provider="unknown"),
                "unknown provider for",
            ),
            (
                "invalid disposition",
                lambda payload: payload["skills"][0].update(disposition="copied"),
                "invalid disposition for",
            ),
            (
                "empty surface",
                lambda payload: payload["skills"][0].update(surface=""),
                "missing surface for",
            ),
            (
                "short sha256",
                lambda payload: payload["skills"][0].update(sha256="0" * 63),
                "invalid sha256 for",
            ),
            (
                "uppercase sha256",
                lambda payload: payload["skills"][0].update(sha256="A" * 64),
                "invalid sha256 for",
            ),
            (
                "empty owners",
                lambda payload: payload["skills"][0].update(owners=[]),
                "missing owners for",
            ),
            (
                "missing owner",
                lambda payload: payload["skills"][0].update(
                    owners=["missing/owner/SKILL.md"]
                ),
                "missing owner for",
            ),
            (
                "path traversal",
                lambda payload: payload["skills"][0].update(path="../escape/SKILL.md"),
                "invalid skill path:",
            ),
            (
                "snapshot drift",
                lambda payload: payload["snapshot"].update(skill_files=40),
                "snapshot counts must declare",
            ),
            (
                "schema version",
                lambda payload: payload.update(schema_version=2),
                "manifest must use schema_version 1",
            ),
        )

        for name, mutate, expected_failure in cases:
            with self.subTest(name=name):
                payload = copy.deepcopy(self.payload)
                mutate(payload)
                failures = checker._manifest_failures(payload, ROOT)
                self.assertTrue(
                    any(expected_failure in failure for failure in failures),
                    failures,
                )


if __name__ == "__main__":
    unittest.main()
