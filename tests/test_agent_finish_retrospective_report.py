"""Finish must distinguish recorded reflection from an absent or failed check."""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("finish_report", SCRIPTS / "agent-finish-check.py")
finish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finish)


class FinishRetrospectiveReportTests(unittest.TestCase):
    def report(self, required, signals):
        output = io.StringIO()
        result = {"retrospective_required": False,
                  "gate_signals": [{"status": "executed", **signal} for signal in signals],
                  "failures": []}
        with redirect_stdout(output), patch.object(finish, "skill_backlog_summary", return_value={}):
            finish.print_result(Path("unused.json"), required, "Ready", result)
        return output.getvalue()

    def test_legacy_or_commit_route_does_not_claim_a_check(self):
        output = self.report(["tests", "review hook"], [])
        self.assertIn("not required by this run", output)
        self.assertNotIn("recorded by", output)

    def test_missing_or_failed_check_is_not_reported_as_recorded(self):
        for signals in ([], [{"gate": "retrospective check", "signal": "FAIL"}]):
            with self.subTest(signals=signals):
                output = self.report(["retrospective check"], signals)
                self.assertIn("no successful check", output)
                self.assertNotIn("recorded by", output)

    def test_successful_check_is_reported(self):
        output = self.report(["retrospective check"],
                             [{"gate": "retrospective check", "signal": "SUCCESS"}])
        self.assertIn("recorded by", output)

    def test_unvalidated_evidence_is_not_reported_as_success(self):
        output = self.report(["retrospective check"], [
            {"gate": "retrospective check", "signal": "SUCCESS"},
            {"gate": "gate evidence policy", "signal": "FAIL"},
        ])
        self.assertIn("no successful check", output)


if __name__ == "__main__":
    unittest.main()
