from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_gate_surface_validators import (
    _labeled_values,
    validate_work_surface_resolution,
)
from agent_finish_gate_policy import validate_gate_evidence
from agent_gate_evidence import gate_field_enums, synthesize_gate_evidence


def resolved_evidence(*, result: str = "resolved", hops: int = 3) -> str:
    return (
        f"work surface resolution: result={result}; owner=workflow surface matcher; "
        "anchors=visible copy; evidence chain=visible copy -> resource key -> route owner; "
        "verified surface paths=scripts/workflow_doc_surfaces.py; concerns=discovery; "
        f"search hops={hops}; nearest falsifying verification=focused routing regression"
    )


class WorkSurfaceResolutionValidatorTests(unittest.TestCase):
    def test_parser_preserves_case_sensitive_evidence_values(self) -> None:
        evidence = resolved_evidence().replace(
            "scripts/workflow_doc_surfaces.py",
            "Feature/LoginScreen.kt",
        )

        values, missing = _labeled_values(evidence)

        self.assertEqual([], missing)
        self.assertEqual(
            "Feature/LoginScreen.kt",
            values["verified surface paths="],
        )

    def test_resolved_evidence_accepts_bounded_chain_and_verification(self) -> None:
        self.assertEqual([], validate_work_surface_resolution(resolved_evidence()))

    def test_fast_path_accepts_one_hop(self) -> None:
        self.assertEqual([], validate_work_surface_resolution(resolved_evidence(hops=1)))

    def test_terminal_non_resolved_results_do_not_pass_completion(self) -> None:
        for result in ("ambiguous", "not_found"):
            with self.subTest(result=result):
                failures = validate_work_surface_resolution(
                    resolved_evidence(result=result)
                )
                self.assertTrue(any("result" in failure for failure in failures))

    def test_search_budget_is_one_to_four_hops(self) -> None:
        for hops in (0, 5):
            with self.subTest(hops=hops):
                failures = validate_work_surface_resolution(
                    resolved_evidence(hops=hops)
                )
                self.assertTrue(any("one to four" in failure for failure in failures))

    def test_owner_chain_and_falsifying_check_are_required(self) -> None:
        evidence = resolved_evidence().replace(
            "visible copy -> resource key -> route owner", "none"
        ).replace("focused routing regression", "none")

        failures = validate_work_surface_resolution(evidence)

        self.assertTrue(any("evidence chain" in failure for failure in failures))
        self.assertTrue(any("falsifying verification" in failure for failure in failures))

    def test_structured_gate_fields_synthesize_finish_valid_evidence(self) -> None:
        evidence, failures = synthesize_gate_evidence(
            "work surface resolution",
            "",
            {
                "result": "resolved",
                "owner": "workflow surface matcher",
                "anchors": "request path candidate",
                "evidence": "request path -> matcher definition -> route owner",
                "surface_paths": "scripts/workflow_doc_surfaces.py",
                "concerns": "discovery",
                "search_hops": "3",
                "verification": "focused routing regression",
            },
        )

        self.assertEqual([], failures)
        self.assertEqual(
            [],
            validate_gate_evidence(
                {"work surface resolution": evidence},
                ["work surface resolution"],
            ),
        )
        self.assertEqual(
            {"result": ("resolved",)},
            gate_field_enums("work surface resolution"),
        )

    def test_structured_gate_rejects_non_resolved_result_before_recording(self) -> None:
        _, failures = synthesize_gate_evidence(
            "work surface resolution",
            "",
            {
                "result": "ambiguous",
                "owner": "two candidates",
                "anchors": "visible copy",
                "evidence": "copy -> candidate one -> candidate two",
                "surface_paths": "one.py,two.py",
                "concerns": "ui",
                "search_hops": "4",
                "verification": "component test",
            },
        )

        self.assertTrue(any("result" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
