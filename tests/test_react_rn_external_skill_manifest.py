"""Regression tests for complete React/RN external skill source coverage."""

from __future__ import annotations

import copy
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


class ReactRnRepositoryProvenanceTests(unittest.TestCase):
    """The snapshot must say which upstream commit it was proven against.

    Before this, `repositories` held bare URLs, so a refresh could not tell an
    upstream that moved on apart from a snapshot someone edited locally.
    """

    def setUp(self) -> None:
        self.payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.repositories = self.payload["repositories"]

    def _mutated(self, provider, **overrides):
        repositories = copy.deepcopy(self.repositories)
        repositories[provider].update(overrides)
        return repositories

    def test_every_provider_records_a_checkable_provenance(self) -> None:
        self.assertEqual([], checker._repository_failures(self.repositories))
        for provider, record in self.repositories.items():
            with self.subTest(provider=provider):
                self.assertIn(record["provenance"], checker.ALLOWED_PROVENANCE)
                if record["provenance"] == "content_verified":
                    self.assertTrue(checker._is_sha(record["commit"], 40))
                else:
                    self.assertEqual(checker.UNPINNED_COMMIT, record["commit"])

    def test_repository_contract_rejects_each_invalid_variant(self) -> None:
        cases = (
            ("bare url string", {"vercel": "https://example.test/repo"}, "must be an object"),
            (
                "non-https url",
                self._mutated("vercel", url="git@example.test:repo.git"),
                "needs an https url",
            ),
            (
                "unknown provenance",
                self._mutated("vercel", provenance="trust_me"),
                "provenance must be content_verified or unpinned",
            ),
            (
                "unpinned with a commit",
                self._mutated("callstack", commit="a" * 40),
                "is unpinned and must record commit unknown",
            ),
            (
                "short pinned commit",
                self._mutated("vercel", commit="abc123"),
                "must pin a full 40-character commit sha",
            ),
            (
                "uppercase pinned commit",
                self._mutated("vercel", commit="A" * 40),
                "must pin a full 40-character commit sha",
            ),
            (
                "missing verified_at",
                self._mutated("vercel", verified_at="  "),
                "needs a verified_at date",
            ),
        )

        for name, repositories, expected_failure in cases:
            with self.subTest(name=name):
                failures = checker._repository_failures(repositories)
                self.assertTrue(
                    any(expected_failure in failure for failure in failures),
                    failures,
                )

    def test_manifest_failures_surface_repository_defects(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["repositories"]["expo"]["provenance"] = "trust_me"

        failures = checker._manifest_failures(payload, ROOT)

        self.assertTrue(
            any("provenance must be" in failure for failure in failures), failures
        )

    def test_remote_check_reports_movement_without_failing(self) -> None:
        repositories = {
            "expo": dict(self.repositories["expo"], commit="b" * 40),
        }
        output = io.StringIO()
        with patch.object(checker, "_remote_head", return_value="c" * 40):
            with redirect_stdout(output):
                failures = checker._remote_failures(repositories)

        self.assertEqual([], failures)
        self.assertIn("MOVED: expo", output.getvalue())
        self.assertIn("b" * 40, output.getvalue())

    def test_remote_check_reports_a_matching_head_as_current(self) -> None:
        repositories = {"expo": dict(self.repositories["expo"], commit="d" * 40)}
        output = io.StringIO()
        with patch.object(checker, "_remote_head", return_value="d" * 40):
            with redirect_stdout(output):
                failures = checker._remote_failures(repositories)

        self.assertEqual([], failures)
        self.assertIn("CURRENT: expo", output.getvalue())

    def test_remote_check_fails_when_provenance_cannot_be_answered(self) -> None:
        unreachable = {"expo": dict(self.repositories["expo"], commit="e" * 40)}
        with patch.object(checker, "_remote_head", return_value=None):
            unreachable_failures = checker._remote_failures(unreachable)
        unpinned_failures = checker._remote_failures(
            {"callstack": self.repositories["callstack"]}
        )

        self.assertTrue(
            any("could not reach expo" in failure for failure in unreachable_failures),
            unreachable_failures,
        )
        self.assertTrue(
            any("cannot prove callstack" in failure for failure in unpinned_failures),
            unpinned_failures,
        )

    def test_default_run_never_touches_the_network(self) -> None:
        with patch.object(checker, "_remote_head") as remote_head:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, checker.main(["--manifest", str(MANIFEST)]))

        remote_head.assert_not_called()


if __name__ == "__main__":
    unittest.main()
