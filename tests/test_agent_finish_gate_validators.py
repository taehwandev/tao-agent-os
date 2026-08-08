"""Focused regression tests for finish-gate evidence validators."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_finish_gate_validators import validate_platform_selection_evidence


class PlatformSelectionEvidenceValidatorTests(unittest.TestCase):
    def test_rejects_python_prose_without_platform_card_evidence(self) -> None:
        for evidence in (
            "Python code was read before architecture",
            "selected platform: python; python-only code before architecture",
        ):
            with self.subTest(evidence=evidence):
                self.assertTrue(validate_platform_selection_evidence(evidence))

    def test_accepts_explicit_python_platform_card_evidence(self) -> None:
        evidence = (
            "selected platform: python; loaded "
            "platforms/python/skills/python-web-service/SKILL.md "
            "before architecture"
        )

        self.assertEqual([], validate_platform_selection_evidence(evidence))


if __name__ == "__main__":
    unittest.main()
