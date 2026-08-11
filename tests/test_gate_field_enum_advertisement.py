"""Advertised gate field values must be exactly the accepted ones.

Naming the required fields removed most of the round trip, but not all of it:
`retrospective check` still had to be failed twice to learn that `outcome` and
`observation` are closed vocabularies. `start` now states them, which only helps
while the advertised set and the validator agree.

These tests drive the real validators rather than restating any value, so adding
or renaming an accepted value on one side fails here instead of silently
reintroducing the round trip. Fields validated only by phrase matching or open
prose must stay out of the registry. A prose-compatible gate may still advertise
the individual fields that its structured path validates by exact membership.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_finish_gate_learning_validators import (
    RETROSPECTIVE_OBSERVATION_STATES,
    RETROSPECTIVE_OUTCOMES,
    validate_retrospective_check,
)
import agent_finish_gate_policy
import agent_gate_evidence
from agent_gate_evidence import (
    FIELD_REQUIREMENTS,
    GRAPHIFY_READINESS_STATUS,
    gate_field_enums,
    synthesize_gate_evidence,
)


def _retrospective_evidence(outcome, observation, skills="retrospective_learning"):
    return (
        "retrospective check; "
        f"skills checked: {skills}; outcome: {outcome}; observation: {observation}"
    )


def _accepts_retrospective(outcome, observation):
    # The validator lowercases and strips, so this helper must too or a
    # case-varied `no_skill_used` would silently be paired with the wrong
    # skills value and look rejected for the wrong reason.
    skills = (
        "none"
        if str(outcome).strip().lower() == "no_skill_used"
        else "retrospective_learning"
    )
    failures = validate_retrospective_check(
        _retrospective_evidence(outcome, observation, skills)
    )
    return not failures


class RegistryShape(unittest.TestCase):
    def test_unknown_gate_has_no_enums(self):
        self.assertEqual(gate_field_enums("not-a-real-gate"), {})

    def test_gates_without_closed_structured_fields_are_not_registered(self):
        # These gates have only open fields or prose markers, so a closed-set
        # advertisement would misstate the contract.
        for gate in (
            "agentic run state",
            "documentation",
            "documentation impact",
            "multi-agent split decision",
            "tests",
            "cycle contract",
            "boundary plan",
            "side-effect audit",
            "source docs",
        ):
            with self.subTest(gate=gate):
                self.assertEqual(gate_field_enums(gate), {})

    def test_registered_fields_are_declared_requirements(self):
        for gate, fields in (
            ("ambiguity check", gate_field_enums("ambiguity check")),
            ("alignment brief", gate_field_enums("alignment brief")),
            ("retrospective check", gate_field_enums("retrospective check")),
            ("graphify readiness", gate_field_enums("graphify readiness")),
        ):
            for field in fields:
                with self.subTest(gate=gate, field=field):
                    self.assertIn(field, FIELD_REQUIREMENTS[gate])

    def test_every_registered_field_offers_values(self):
        for gate in (
            "ambiguity check",
            "alignment brief",
            "retrospective check",
            "graphify readiness",
        ):
            for field, values in gate_field_enums(gate).items():
                with self.subTest(gate=gate, field=field):
                    self.assertTrue(values)
                    self.assertEqual(len(values), len(set(values)))

    def test_prose_compatible_gates_advertise_only_exact_structured_values(self):
        self.assertEqual(
            gate_field_enums("ambiguity check"),
            {
                "blocker_status": ("none", "resolved"),
                "decision": ("proceed",),
            },
        )
        self.assertEqual(
            gate_field_enums("alignment brief"),
            {"checkpoint": ("user_visible_before_edits",)},
        )


class RetrospectiveEnumsMatchTheValidator(unittest.TestCase):
    def setUp(self):
        self.enums = gate_field_enums("retrospective check")

    def test_advertised_set_is_exactly_the_validated_set(self):
        """Pin the linkage, because the sampled cases cannot carry this.

        The reject cases below cannot isolate the membership check: the
        outcome/observation pairing rule refuses most values on its own, so an
        out-of-set value looks rejected either way. This assertion is what
        actually ties the advertisement to the set the validator tests. A
        validator clause that bypasses its own constant remains invisible from
        here and belongs to that validator's own tests.
        """
        self.assertEqual(set(self.enums["outcome"]), set(RETROSPECTIVE_OUTCOMES))
        self.assertEqual(
            set(self.enums["observation"]), set(RETROSPECTIVE_OBSERVATION_STATES)
        )

    def test_every_advertised_outcome_is_accepted_by_some_observation(self):
        for outcome in self.enums["outcome"]:
            with self.subTest(outcome=outcome):
                self.assertTrue(
                    any(
                        _accepts_retrospective(outcome, observation)
                        for observation in self.enums["observation"]
                    ),
                    f"advertised outcome {outcome} is accepted by no advertised observation",
                )

    def test_every_advertised_observation_is_accepted_by_some_outcome(self):
        for observation in self.enums["observation"]:
            with self.subTest(observation=observation):
                self.assertTrue(
                    any(
                        _accepts_retrospective(outcome, observation)
                        for outcome in self.enums["outcome"]
                    ),
                    f"advertised observation {observation} is accepted by no advertised outcome",
                )

    def test_unadvertised_outcome_is_rejected(self):
        # Coarse: the pairing rule also refuses these, so this guards the gate
        # as a whole rather than the membership check alone.
        for bogus in ("no_gap", "reusable", "gap_found", "reusable-gap", ""):
            with self.subTest(bogus=bogus):
                self.assertFalse(
                    any(
                        _accepts_retrospective(bogus, observation)
                        for observation in self.enums["observation"]
                    ),
                    f"unadvertised outcome {bogus!r} was accepted",
                )

    def test_unadvertised_observation_is_rejected(self):
        for bogus in ("noted", "none", "not needed", ""):
            with self.subTest(bogus=bogus):
                self.assertFalse(
                    any(
                        _accepts_retrospective(outcome, bogus)
                        for outcome in self.enums["outcome"]
                    ),
                    f"unadvertised observation {bogus!r} was accepted",
                )

    def test_advertised_values_are_case_and_space_insensitive(self):
        """Pinned deliberately: the validator lowercases and strips, so an
        advertised value must keep working when a caller varies its case."""
        for outcome in self.enums["outcome"]:
            for observation in self.enums["observation"]:
                if not _accepts_retrospective(outcome, observation):
                    continue
                self.assertTrue(
                    _accepts_retrospective(f" {outcome.upper()} ", f" {observation.upper()} "),
                    f"{outcome}/{observation} rejected when upper-cased and padded",
                )


    def test_out_of_set_value_is_refused_on_membership_grounds(self):
        """Isolate the membership check from the pairing rule.

        A value outside the set must be refused even when it is paired the way
        its nearest in-set neighbour would be, which is the only way to see the
        membership check on its own.
        """
        for observation in self.enums["observation"]:
            failures = validate_retrospective_check(
                _retrospective_evidence("brand_new_outcome", observation)
            )
            self.assertTrue(failures, "out-of-set outcome accepted")
            self.assertTrue(
                any("outcome must be" in failure for failure in failures),
                f"outcome membership not the stated reason: {failures}",
            )
        for outcome in self.enums["outcome"]:
            skills = "none" if outcome == "no_skill_used" else "retrospective_learning"
            failures = validate_retrospective_check(
                _retrospective_evidence(outcome, "brand_new_state", skills)
            )
            self.assertTrue(failures, "out-of-set observation accepted")
            self.assertTrue(
                any("observation must be" in failure for failure in failures),
                f"observation membership not the stated reason: {failures}",
            )


class GraphifyEnumsMatchTheValidator(unittest.TestCase):
    GATE = "graphify readiness"

    def _synthesize(self, value):
        fields = {field: value for field in FIELD_REQUIREMENTS[self.GATE]}
        return synthesize_gate_evidence(self.GATE, "", fields)

    def test_every_required_field_is_advertised(self):
        self.assertEqual(
            sorted(gate_field_enums(self.GATE)),
            sorted(FIELD_REQUIREMENTS[self.GATE]),
        )

    def test_advertised_value_is_accepted(self):
        _, failures = self._synthesize(GRAPHIFY_READINESS_STATUS)
        self.assertEqual(failures, [])

    def test_unadvertised_value_is_rejected(self):
        for bogus in ("ok", "pass", "SUCCESSFUL", "ready"):
            with self.subTest(bogus=bogus):
                _, failures = self._synthesize(bogus)
                self.assertTrue(failures, f"unadvertised value {bogus!r} was accepted")

    def test_final_validator_reads_the_same_runtime_status_constant(self):
        probe = "runtime_probe"
        fields = {field: probe for field in FIELD_REQUIREMENTS[self.GATE]}

        with patch.object(agent_gate_evidence, "GRAPHIFY_READINESS_STATUS", probe):
            evidence, failures = synthesize_gate_evidence(self.GATE, "", fields)

            self.assertEqual(failures, [])
            self.assertEqual(
                gate_field_enums(self.GATE),
                {field: (probe,) for field in FIELD_REQUIREMENTS[self.GATE]},
            )
            self.assertEqual(
                agent_finish_gate_policy.validate_gate_evidence(
                    {self.GATE: evidence}, [self.GATE]
                ),
                [],
            )


class StructuredFieldEnumsMatchTheSynthesizer(unittest.TestCase):
    def test_ambiguity_values_are_accepted_and_near_misses_are_rejected(self):
        valid = {
            "blocker_status": "none",
            "assumptions": "bounded reversible assumptions",
            "decision": "proceed",
        }
        evidence, failures = synthesize_gate_evidence("ambiguity check", "", valid)
        self.assertTrue(evidence)
        self.assertEqual(failures, [])

        for field, bogus in (("blocker_status", "open"), ("decision", "continue")):
            with self.subTest(field=field, bogus=bogus):
                values = {**valid, field: bogus}
                _, failures = synthesize_gate_evidence("ambiguity check", "", values)
                self.assertTrue(failures)

    def test_alignment_checkpoint_is_accepted_and_near_miss_is_rejected(self):
        valid = {
            "shared_understanding": "same bounded fix",
            "possible_differences": "none",
            "assumptions": "existing prose compatibility remains",
            "checkpoint": "user_visible_before_edits",
        }
        evidence, failures = synthesize_gate_evidence("alignment brief", "", valid)
        self.assertTrue(evidence)
        self.assertEqual(failures, [])

        _, failures = synthesize_gate_evidence(
            "alignment brief", "", {**valid, "checkpoint": "before_edits"}
        )
        self.assertTrue(failures)


class RenderedAdvertisement(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "agent_hook_main_enums", SCRIPTS / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.lines = module._structured_gate_field_lines

    def _line_for(self, gate):
        rendered = self.lines([gate])
        body = [line for line in rendered[1:] if line.strip().startswith(f"{gate}:")]
        self.assertEqual(len(body), 1)
        return body[0]

    def test_closed_set_fields_show_their_values(self):
        line = self._line_for("retrospective check")
        for field, values in gate_field_enums("retrospective check").items():
            self.assertIn(f"{field} ({'|'.join(values)})", line)

    def test_open_fields_show_no_parenthetical(self):
        line = self._line_for("retrospective check")
        # skills_checked is a format rule, not a closed set.
        self.assertIn("skills_checked,", line)
        self.assertNotIn("skills_checked (", line)

    def test_prose_compatible_structured_fields_show_only_their_closed_values(self):
        ambiguity = self._line_for("ambiguity check")
        self.assertIn("blocker_status (none|resolved)", ambiguity)
        self.assertIn("decision (proceed)", ambiguity)
        self.assertIn("assumptions", ambiguity)
        self.assertNotIn("assumptions (", ambiguity)

        alignment = self._line_for("alignment brief")
        self.assertIn("checkpoint (user_visible_before_edits)", alignment)
        for field in ("shared_understanding", "possible_differences", "assumptions"):
            self.assertIn(field, alignment)
            self.assertNotIn(f"{field} (", alignment)

    def test_gate_without_enums_renders_plain_field_names(self):
        line = self._line_for("tests")
        self.assertNotIn("(", line)
        for field in FIELD_REQUIREMENTS["tests"]:
            self.assertIn(field, line)


if __name__ == "__main__":
    unittest.main()
