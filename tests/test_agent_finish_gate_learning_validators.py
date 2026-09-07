"""Causal efficiency assessments reuse the existing retrospective gate."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_gate_evidence import synthesize_gate_evidence


class EfficiencyAssessmentTests(unittest.TestCase):
    def render(self, **extra):
        fields = dict(skills_checked="retrospective_learning",
                      outcome="no_reusable_gap", observation="not_needed")
        fields.update(extra)
        text, missing = synthesize_gate_evidence("retrospective check", "", fields)
        self.assertEqual([], missing)
        return text

    def test_historical_and_unmeasured_records_remain_valid(self):
        for fields in ({}, {"efficiency": "unmeasured", "efficiency_evidence": "No comparable timing available"},
                       {"efficiency": "no_waste", "efficiency_evidence": "No unchanged-result requery observed"}):
            with self.subTest(fields=fields):
                self.assertEqual([], validate_retrospective_check(self.render(**fields)))

    def test_improvement_survives_rendering_and_requires_causal_chain(self):
        fields = dict(efficiency="improvement_needed", outcome="reusable_gap", observation="recorded",
                      efficiency_evidence="One unchanged ledger query followed its snapshot",
                      efficiency_cause="Snapshot reuse decision was absent",
                      efficiency_reduction="Reuse unchanged batch snapshot",
                      efficiency_verification="Regression checks snapshot and failed-ledger counterexample")
        self.assertEqual([], validate_retrospective_check(self.render(**fields)))
        for name in ("efficiency_evidence", "efficiency_cause", "efficiency_reduction", "efficiency_verification"):
            with self.subTest(name=name):
                incomplete = dict(fields)
                del incomplete[name]
                self.assertTrue(validate_retrospective_check(self.render(**incomplete)))

    def test_improvement_cannot_bypass_existing_maintenance(self):
        text = self.render(efficiency="improvement_needed", efficiency_evidence="Observed redundant read",
                           efficiency_cause="Optional link treated as mandatory", efficiency_reduction="Narrow selection",
                           efficiency_verification="Selection regression with required dependency preserved")
        self.assertTrue(any("same-closeout" in error for error in validate_retrospective_check(text)))

    def test_unknown_or_orphan_fields_are_rejected(self):
        for fields in ({"efficiency": "fast"}, {"efficiency_cause": "Missing assessment"},
                       {"efficiency": "no_waste"}):
            with self.subTest(fields=fields):
                self.assertTrue(validate_retrospective_check(self.render(**fields)))


if __name__ == "__main__":
    unittest.main()
