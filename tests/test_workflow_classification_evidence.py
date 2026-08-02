"""Classification evidence is diagnostic state, not work authorization."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_request import (
    classification_evidence_allows_command_work,
    classification_evidence_blocks_work,
    classification_evidence_requires_clarification,
    classified_route_block_reason,
)


class ClassificationEvidencePolicyTests(unittest.TestCase):
    def test_empty_or_unresolved_evidence_blocks_finish_reuse(self) -> None:
        for evidence in (
            "",
            "classified",
            "vague-action",
            "open questions remain",
            "not clarified",
            "blockers unresolved",
        ):
            with self.subTest(evidence=evidence):
                self.assertTrue(classification_evidence_blocks_work(evidence))
                self.assertTrue(classified_route_block_reason("bugfix", evidence))

    def test_named_resolution_can_satisfy_non_authorization_state_checks(self) -> None:
        for evidence in (
            "clear-exact target confirmed",
            "clear-scoped parser repair",
            "ambiguity resolved for the parser target",
            "answered the user; separate actionable request remains",
        ):
            with self.subTest(evidence=evidence):
                self.assertFalse(classification_evidence_blocks_work(evidence))
                self.assertTrue(classification_evidence_allows_command_work("bugfix", evidence))

    def test_release_and_commit_words_alone_no_longer_count_as_resolution(self) -> None:
        for command, evidence in (
            ("git_commit", "커밋해줘"),
            ("commit", "commit and push"),
            ("release", "v1.2.3 태그를 배포해줘"),
            ("ship", "publish the release"),
        ):
            with self.subTest(command=command, evidence=evidence):
                self.assertFalse(
                    classification_evidence_allows_command_work(command, evidence)
                )
                self.assertTrue(classified_route_block_reason(command, evidence))

    def test_unresolved_signal_beats_a_generic_resolution_word(self) -> None:
        evidence = "clear-scoped but open questions remain"

        self.assertTrue(classification_evidence_blocks_work(evidence))
        self.assertTrue(classification_evidence_requires_clarification(evidence))


class ClassifiedFlagCliTests(unittest.TestCase):
    def test_free_text_evidence_and_the_flag_cannot_replace_an_envelope(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/workflow.py",
                "route",
                "release",
                "--request",
                "commit and push",
                "--request-classified",
                "--classification-evidence",
                "clear-scoped release target confirmed",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("intent envelope", result.stderr)

    def test_a_missing_envelope_wins_before_parent_capsule_reuse(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/workflow.py",
                "route",
                "bugfix",
                "--request",
                "응",
                "--request-classified",
                "--classification-evidence",
                "clear-scoped parser repair",
                "--project",
                str(ROOT),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("intent envelope", result.stderr)


if __name__ == "__main__":
    unittest.main()
