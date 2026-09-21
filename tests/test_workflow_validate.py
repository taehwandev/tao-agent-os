"""Required reading growth must fail the validator used by review, not just tests."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import workflow_validate


class ReadingBudgetTests(unittest.TestCase):
    def test_review_validator_rejects_required_reading_growth(self):
        # A shared mandatory card grows; the real review validator must reject it.
        with patch("workflow_validate.doc_size", return_value=100_000):
            failures = workflow_validate.validate_route_contracts()
        self.assertTrue(any("required reading budget" in item for item in failures))
        self.assertTrue(any("agent-operating-skill" in item for item in failures))

    def test_budget_boundary_is_strict_and_reports_contributors(self):
        for size, rejected in ((99_999, False), (100_000, True), (100_001, True)):
            with self.subTest(size=size):
                failures = workflow_validate.reading_budget_failures({"card.md": size})
                self.assertEqual(rejected, bool(failures))
                if rejected:
                    self.assertIn("card.md", failures[0])


if __name__ == "__main__":
    unittest.main()
