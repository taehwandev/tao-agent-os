"""Boundary evidence must survive recording without duplicating it in scope."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_finish_gate_policy import validate_gate_evidence
from agent_gate_evidence import (
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    reset_gate_evidence_ledger,
    synthesize_gate_evidence,
)


class BoundaryEvidenceTests(unittest.TestCase):
    gate = "boundary plan"
    fields = {"scope": "Panel/MenuBar/Preferences", "verification": "swift test"}
    decision = "Review budget: one top-level owner per runtime file."

    def test_structure_decision_in_evidence_survives_ledger_round_trip(self) -> None:
        route = {"command": "product", "gates": [self.gate]}
        preflight = {"route": route}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.json"
            path.write_text(json.dumps(preflight), encoding="utf-8")
            reset_gate_evidence_ledger(path, preflight)
            record_gate_evidence(
                evidence_path=path, preflight=preflight, gate=self.gate,
                evidence=self.decision, fields=self.fields,
            )
            merged, diagnostics = merge_gate_evidence_from_ledger(
                route=route, evidence_path=path,
            )
            self.assertTrue(diagnostics["used"])
            self.assertIn(self.decision, merged[self.gate])
            self.assertEqual([], validate_gate_evidence(merged, [self.gate]))

    def test_existing_scope_decision_still_passes_without_extra_prose(self) -> None:
        rendered, missing = synthesize_gate_evidence(
            self.gate, "", {**self.fields, "scope": "Panel; " + self.decision},
        )
        self.assertEqual([], missing)
        self.assertEqual([], validate_gate_evidence({self.gate: rendered}, [self.gate]))

    def test_missing_structure_decision_is_still_rejected(self) -> None:
        rendered, missing = synthesize_gate_evidence(
            self.gate, "Panel cleanup", self.fields,
        )
        self.assertEqual([], missing)
        self.assertTrue(validate_gate_evidence({self.gate: rendered}, [self.gate]))

    def test_prose_does_not_replace_missing_required_fields(self) -> None:
        _, missing = synthesize_gate_evidence(self.gate, self.decision, {})
        self.assertEqual(["scope", "verification"], missing)


if __name__ == "__main__":
    unittest.main()
