"""The review hook must demand exactly the evidence that `start` advertises.

The `review_hook` missed-gate lesson recurred because the required evidence
paths were only discoverable by failing the review hook. `start` now advertises
them, which is only useful while the advertisement and the enforcement stay
identical. These tests derive the enforced set from
`record_review_input_evidence` itself rather than restating it, so adding a new
gate-conditional evidence flag on one side fails here instead of silently
reintroducing the round trip.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_review_hook import (
    ALWAYS_REQUIRED_REVIEW_EVIDENCE,
    GATE_REQUIRED_REVIEW_EVIDENCE,
    record_review_input_evidence,
    required_review_evidence_flags,
)


# argparse dest for each advertised flag, so a blank value can be forced.
FLAG_TO_ATTR = {
    "--code-review-evidence": "code_review_evidence",
    "--docs-freshness-evidence": "docs_freshness_evidence",
    "--boundary-plan-evidence": "boundary_plan_evidence",
    "--side-effect-audit-evidence": "side_effect_audit_evidence",
}

ALL_GATES = sorted(GATE_REQUIRED_REVIEW_EVIDENCE)


def _args(project: Path, **overrides):
    values = {
        "review_outcome": "pass",
        "code_review_evidence": "cr.md",
        "docs_freshness_evidence": "df.md",
        "structure_review_evidence": "",
        "boundary_plan_evidence": "bp.md",
        "side_effect_audit_evidence": "se.md",
        "project": project,
        "evidence": None,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class RequiredReviewEvidenceFlags(unittest.TestCase):
    def test_always_required_flags_need_no_gate(self):
        self.assertEqual(
            required_review_evidence_flags([]), list(ALWAYS_REQUIRED_REVIEW_EVIDENCE)
        )

    def test_each_gate_adds_exactly_its_own_flag(self):
        for gate, flag in GATE_REQUIRED_REVIEW_EVIDENCE.items():
            with self.subTest(gate=gate):
                flags = required_review_evidence_flags([gate])
                self.assertIn(flag, flags)
                others = set(GATE_REQUIRED_REVIEW_EVIDENCE.values()) - {flag}
                self.assertFalse(others & set(flags))

    def test_unrelated_gates_add_nothing(self):
        self.assertEqual(
            required_review_evidence_flags(["orient", "act", "verify"]),
            list(ALWAYS_REQUIRED_REVIEW_EVIDENCE),
        )

    def test_flags_are_unique(self):
        flags = required_review_evidence_flags(ALL_GATES)
        self.assertEqual(len(flags), len(set(flags)))


class AdvertisementMatchesEnforcement(unittest.TestCase):
    """Blank each advertised flag in turn; enforcement must object every time."""

    def setUp(self):
        # review_route_gates() reads a missing preflight and returns [], so the
        # gate list is supplied through a patched lookup instead of a fixture.
        import agent_review_hook

        self._original = agent_review_hook.review_route_gates
        self._gates: list[str] = []
        agent_review_hook.review_route_gates = lambda project, evidence: list(self._gates)
        self.addCleanup(self._restore)

    def _restore(self):
        import agent_review_hook

        agent_review_hook.review_route_gates = self._original

    def _enforced_flags(self, gates):
        """Flags whose absence makes record_review_input_evidence fail."""
        self._gates = list(gates)
        enforced = []
        for flag, attr in FLAG_TO_ATTR.items():
            failures: list[str] = []
            record_review_input_evidence(
                _args(ROOT, **{attr: ""}), {}, failures
            )
            if failures:
                enforced.append(flag)
        return enforced

    def test_matches_with_no_conditional_gates(self):
        self.assertEqual(
            sorted(self._enforced_flags([])),
            sorted(required_review_evidence_flags([])),
        )

    def test_matches_with_every_conditional_gate(self):
        self.assertEqual(
            sorted(self._enforced_flags(ALL_GATES)),
            sorted(required_review_evidence_flags(ALL_GATES)),
        )

    def test_matches_for_each_gate_alone(self):
        for gate in ALL_GATES:
            with self.subTest(gate=gate):
                self.assertEqual(
                    sorted(self._enforced_flags([gate])),
                    sorted(required_review_evidence_flags([gate])),
                )

    def test_complete_evidence_raises_no_failure(self):
        self._gates = list(ALL_GATES)
        failures: list[str] = []
        record_review_input_evidence(_args(ROOT), {}, failures)
        self.assertEqual(failures, [])



class StructuredGateFieldAdvertisement(unittest.TestCase):
    """The same discoverability fix, applied to gates that reject prose.

    Several gates demand an exact field set and reject a sentence, which was
    only learnable by failing finish. `retrospective check` alone is the largest
    recurring lesson class in the store, so the advertised list must stay derived
    from FIELD_REQUIREMENTS rather than restated.
    """

    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agent_hook_main", SCRIPTS / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.lines = module._structured_gate_field_lines
        from agent_gate_evidence import FIELD_REQUIREMENTS

        self.requirements = FIELD_REQUIREMENTS

    def test_gates_without_field_requirements_are_silent(self):
        bare = [gate for gate in ("request intake", "act", "verify", "edit")
                if not self.requirements.get(gate)]
        self.assertTrue(bare, "expected at least one field-free gate to test")
        self.assertEqual(self.lines(bare), [])

    def test_unknown_gates_are_silent(self):
        self.assertEqual(self.lines(["not-a-real-gate"]), [])

    def test_named_fields_are_listed_verbatim_from_the_requirement(self):
        gate = "retrospective check"
        rendered = self.lines([gate])
        self.assertTrue(rendered[0].startswith("Gates requiring named fields"))
        body = [line for line in rendered[1:] if line.strip().startswith(gate)]
        self.assertEqual(len(body), 1)
        for field in self.requirements[gate]:
            self.assertIn(field, body[0])

    def test_every_field_carrying_gate_in_the_route_is_listed(self):
        gates = sorted(gate for gate, fields in self.requirements.items() if fields)
        rendered = self.lines(gates)
        self.assertEqual(len(rendered), len(gates) + 1)
        for gate in gates:
            self.assertTrue(
                any(line.strip().startswith(f"{gate}:") for line in rendered[1:]),
                f"{gate} missing from the advertisement",
            )

    def test_sub_lines_are_indented_not_dashed(self):
        # The harness prefixes each detail with "- "; a leading dash here
        # rendered as "- - gate: ...".
        for line in self.lines(["retrospective check", "tests"])[1:]:
            self.assertFalse(line.lstrip().startswith("-"))
            self.assertTrue(line.startswith("  "))


if __name__ == "__main__":
    unittest.main()
