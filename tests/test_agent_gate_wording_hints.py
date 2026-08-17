"""Advice a gate gives before the work must be advice that passes it.

Gate evidence is judged by substring match, and a truthful sentence the
matcher does not recognise is refused after the work is already done -- the
largest recurring failure class in the lesson store. `start` now states the
wording, so these tests hold that statement to the same standard as the rule:
every worked example must satisfy its own validator, and every advertised
phrase must be one the validator actually accepts.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_gate_boundary_validators import (
    BOUNDARY_PLAN_PHRASES,
    validate_boundary_plan,
)
from agent_finish_gate_collaboration_validators import (
    SERIAL_REASON_PHRASES,
    validate_multi_agent,
)
from agent_finish_gate_doc_test_validators import (
    TEST_PASSED_PHRASES,
    TEST_SIGNAL_PHRASES,
    validate_documentation,
    validate_tests,
)
from agent_finish_gate_validators import gate_wording_examples, gate_wording_hints


VALIDATORS = {
    "boundary plan": validate_boundary_plan,
    "multi-agent split decision": validate_multi_agent,
    "tests": validate_tests,
    "documentation": validate_documentation,
    "documentation impact": validate_documentation,
}


def _hook_module():
    spec = importlib.util.spec_from_file_location(
        "agent_hook_wording_test", ROOT / "scripts" / "agent-hook.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WordingExampleTests(unittest.TestCase):
    def test_every_worked_example_satisfies_its_own_gate(self) -> None:
        """Advice that does not pass is worse than none: it is trusted."""

        for gate, example in gate_wording_examples().items():
            with self.subTest(gate=gate):
                self.assertEqual([], VALIDATORS[gate](example))

    def test_every_gate_with_hints_has_a_validator_here(self) -> None:
        """A new hint without a checked example would go unverified."""

        self.assertEqual(sorted(VALIDATORS), sorted(gate_wording_examples()))


class WordingPhraseTests(unittest.TestCase):
    """The advertised phrases are the validators' own, not a second copy."""

    def test_advertised_phrases_come_from_the_validator_constants(self) -> None:
        advertised = "\n".join(
            line
            for gate in VALIDATORS
            for line in gate_wording_hints(gate)
            if not line.startswith(("example --", "and "))
        )

        for phrases in (
            TEST_SIGNAL_PHRASES[:1],
            TEST_PASSED_PHRASES[:1],
            SERIAL_REASON_PHRASES[:1],
            BOUNDARY_PLAN_PHRASES["runtime structure decision"][:1],
        ):
            with self.subTest(phrase=phrases[0]):
                self.assertIn(phrases[0], advertised)

    def test_the_tests_gate_states_the_requirement_no_phrase_covers(self) -> None:
        """Phrases alone do not pass this gate, and the hint has to say so.

        `test` and `passed` satisfy both phrase groups and are still refused,
        because a pass word is equally true of a suite that never ran.
        """

        self.assertTrue(validate_tests("test; passed"))
        self.assertTrue(
            any(line.startswith("and ") for line in gate_wording_hints("tests"))
        )

    def test_the_documentation_gate_states_that_the_path_is_required(self) -> None:
        self.assertTrue(validate_documentation("decision: unchanged; inspected; already covered"))
        self.assertTrue(
            any("doc path" in line for line in gate_wording_hints("documentation"))
        )


class StartOutputTests(unittest.TestCase):
    def test_start_prints_the_wording_beside_the_fields_it_belongs_to(self) -> None:
        lines = _hook_module()._structured_gate_field_lines(["tests", "boundary plan"])

        rendered = "\n".join(lines)
        self.assertIn("  tests: check, result", rendered)
        self.assertIn("    wording -- the check run:", rendered)
        self.assertIn("    wording -- example -- check: unittest", rendered)
        self.assertLess(
            rendered.index("wording -- the check run"),
            rendered.index("  boundary plan:"),
            "each gate's wording must sit under that gate",
        )

    def test_a_gate_without_wording_requirements_prints_none(self) -> None:
        lines = _hook_module()._structured_gate_field_lines(["retrospective check"])

        self.assertTrue(any("retrospective check:" in line for line in lines))
        self.assertFalse(any("wording --" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
