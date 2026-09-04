"""One definition, and the one difference that must not be collapsed."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import agent_finish_common  # noqa: E402
import agent_hook_runtime  # noqa: E402
from agent_command_runtime import (  # noqa: E402
    clean_output,
    parse_overall,
    parse_overall_record,
    run_command,
    vibeguard_command,
)

SHARING_MODULES = (
    "agent_hook_runtime.py",
    "agent_finish_common.py",
    "agent-preflight.py",
)


class OneDefinitionTests(unittest.TestCase):
    """Three copies is where `parse_overall` drifted into two functions."""

    def test_no_module_defines_these_again(self) -> None:
        for name in SHARING_MODULES:
            tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
            defined = {
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
            }
            for shared in ("clean_output", "run_command", "vibeguard_command"):
                with self.subTest(module=name, function=shared):
                    self.assertNotIn(shared, defined)

    def test_the_importing_modules_still_offer_the_same_names(self) -> None:
        """Their callers import these from them, so re-export is the contract."""

        for module in (agent_hook_runtime, agent_finish_common):
            with self.subTest(module=module.__name__):
                self.assertIs(run_command, module.run_command)
                self.assertIs(vibeguard_command, module.vibeguard_command)


class TheTwoOverallReadersStayApartTests(unittest.TestCase):
    """The review gate compares its result to "Ready".

    Handing it the `{status, line}` record instead would fail every audit that
    passed, so these are two functions and not one with two callers.
    """

    AUDIT = "Scanned 12 files\nOverall: \x1b[32mReady\x1b[0m\nDone\n"

    def test_the_review_gate_gets_a_bare_verdict(self) -> None:
        self.assertEqual("Ready", parse_overall(self.AUDIT))
        self.assertIs(parse_overall, agent_hook_runtime.parse_overall)

    def test_the_evidence_files_get_the_line_as_well(self) -> None:
        record = parse_overall_record(self.AUDIT)

        self.assertEqual("Ready", record["status"])
        self.assertEqual("Overall: Ready", record["line"])
        self.assertIs(parse_overall_record, agent_finish_common.parse_overall)

    def test_an_audit_with_no_verdict_is_unknown_either_way(self) -> None:
        self.assertEqual("unknown", parse_overall("nothing to report\n"))
        self.assertEqual(
            {"status": "unknown", "line": ""}, parse_overall_record("nothing to report\n")
        )

    def test_every_verdict_survives_colour(self) -> None:
        for verdict in ("Ready", "Needs review", "Blocked"):
            with self.subTest(verdict=verdict):
                coloured = f"Overall: \x1b[31m{verdict}\x1b[0m\n"

                self.assertEqual(verdict, parse_overall(coloured))


class CommandResultShapeTests(unittest.TestCase):
    def test_a_result_reports_the_command_its_directory_and_clean_output(self) -> None:
        result = run_command([sys.executable, "-c", "print('hi')"], ROOT)

        self.assertEqual(0, result["returncode"])
        self.assertEqual("hi\n", result["stdout"])
        self.assertEqual(str(ROOT), result["cwd"])

    def test_escape_sequences_are_stripped(self) -> None:
        self.assertEqual("plain", clean_output("\x1b[1mplain\x1b[0m"))

    def test_the_audit_command_names_the_project_and_the_rules(self) -> None:
        command = vibeguard_command(Path("/tmp/project"), Path("/tmp/rules"))

        self.assertEqual("audit", command[command.index("audit")])
        self.assertIn("/tmp/project", command)
        self.assertIn("/tmp/rules", command)


if __name__ == "__main__":
    unittest.main()
