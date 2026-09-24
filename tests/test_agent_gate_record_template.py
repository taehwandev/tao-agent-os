"""Rejected gate records answer with a fill-in template; acceptance is unchanged."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_gate_evidence import read_gate_evidence_ledger, reset_gate_evidence_ledger
from agent_gate_record_template import gate_record_template
from agent_hook_gate_records import gate_batch_hook, gate_hook


GATES = ["tests", "retrospective check"]
REQUIRED_DOCS = ["common/skills/agent-operating-skill/SKILL.md"]


def _run(hook_name: str, **overrides: object) -> tuple[int, str, dict]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        evidence = project / ".tao" / "preflight.json"
        evidence.parent.mkdir()
        preflight = {
            "project": str(project),
            "rules": str(ROOT),
            "route": {"command": "bugfix", "gates": GATES, "required_docs": REQUIRED_DOCS},
        }
        evidence.write_text(json.dumps(preflight), encoding="utf-8")
        reset_gate_evidence_ledger(evidence, preflight)
        args = SimpleNamespace(
            project=project, rules=ROOT, evidence=evidence, output=None, repair_cycle=0,
            hook=hook_name, gate_json=None, gate_record=[], field=[], gate_name="",
            gate_evidence="", source="manual", status="SUCCESS",
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        output = io.StringIO()
        with redirect_stdout(output):
            result = (gate_hook if hook_name == "gate" else gate_batch_hook)(args)
        return result, output.getvalue(), read_gate_evidence_ledger(evidence)


def _batch(record: dict) -> tuple[int, str, dict]:
    return _run("gate-batch", gate_record=[json.dumps(record)])


class RejectedGateRecordTemplateTests(unittest.TestCase):
    def test_tests_record_missing_fields_prints_a_template_with_check_and_result(self) -> None:
        result, output, _ledger = _batch({"gate": "tests", "fields": {"check": "unittest"}})

        self.assertEqual(1, result)
        self.assertIn("missing required fields: result", output)
        self.assertIn(
            'fill-in template for tests: {"gate":"tests","status":"SUCCESS",'
            '"fields":{"check":"<command run>","result":"<observed result>"}}',
            output,
        )

    def test_template_lists_enum_values_from_the_validator_schema(self) -> None:
        template = gate_record_template("retrospective check")

        self.assertIn('"outcome":"<no_reusable_gap|no_skill_used|reusable_gap>"', template)
        self.assertIn('"observation":"<not_needed|recorded>"', template)
        self.assertIn('"skills_checked":', template)

    def test_single_gate_hook_gets_the_field_flag_form(self) -> None:
        result, output, _ledger = _run(
            "gate", gate_name="tests", field=["check=unittest discover"]
        )

        self.assertEqual(1, result)
        self.assertIn(
            'fill-in template for tests: --gate-name "tests" '
            '--field "check=<command run>" --field "result=<observed result>"',
            output,
        )

    def test_unfalsifiable_tests_result_names_the_field_and_a_valid_shape(self) -> None:
        result, output, ledger = _batch(
            {"gate": "tests", "fields": {"check": "the tests", "result": "passed"}}
        )

        self.assertEqual(1, result)
        self.assertIn("not falsifiable", output)
        self.assertIn("fields.result", output)
        self.assertIn('"result":"1163 tests passed, 0 failures"', output)
        self.assertFalse(ledger.get("entries"))

    def test_retrospective_pairing_rejection_names_outcome_and_observation(self) -> None:
        result, output, _ledger = _batch({
            "gate": "retrospective check",
            "fields": {
                "skills_checked": "agent_operating_skill",
                "outcome": "no_reusable_gap",
                "observation": "recorded",
            },
        })

        self.assertEqual(1, result)
        self.assertIn("fields.outcome and fields.observation pair as", output)
        self.assertIn("fill-in template for retrospective check:", output)

    def test_retrospective_skill_rejection_suggests_the_loaded_slugs(self) -> None:
        result, output, _ledger = _batch({
            "gate": "retrospective check",
            "fields": {
                "skills_checked": "common/skills/testing/SKILL.md",
                "outcome": "no_reusable_gap",
                "observation": "not_needed",
            },
        })

        self.assertEqual(1, result)
        self.assertIn('"skills_checked":"agent_operating_skill"', output)

    def test_valid_record_is_still_accepted_without_templates(self) -> None:
        result, output, _ledger = _batch({
            "gate": "tests",
            "fields": {"check": "unittest discover -s tests", "result": "12 tests passed"},
        })

        self.assertEqual(0, result)
        self.assertNotIn("fill-in template", output)


if __name__ == "__main__":
    unittest.main()
