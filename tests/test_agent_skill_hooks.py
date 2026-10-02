from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_skill_hooks import skill_maintenance_hook


class AgentSkillHooksTests(unittest.TestCase):
    def _invoke(self, root: Path, result: dict):
        output = root / "result.json"
        args = Namespace(
            project=root, rules=root, evidence=root / "preflight.json",
            feedback_candidate_id="1234567890abcdef",
            skill_maintenance_outcome="applied",
            verification_kind="workflow_validate", maintenance_target="SKILL.md",
            maintenance_test_selector="", output=output,
        )
        stream = io.StringIO()
        with patch(
            "agent_skill_hooks.record_skill_maintenance",
            return_value=(result, ["maintenance result"]),
        ) as maintenance, contextlib.redirect_stdout(stream):
            code = skill_maintenance_hook(args)
        maintenance.assert_called_once()
        return code, stream.getvalue(), json.loads(output.read_text())

    def test_failed_verifier_is_failed_and_reports_diagnostics_in_same_call(self):
        with tempfile.TemporaryDirectory() as temp:
            result = {
                "updated": False, "reason": "maintenance_verification_failed",
                "verification": {
                    "kind": "workflow_validate", "returncode": 7,
                    "stdout": "Reading budget exceeded",
                    "stderr": "Detailed validator failure",
                },
            }
            code, printed, output = self._invoke(Path(temp), result)
            self.assertEqual(1, code)
            self.assertIn("FAIL skill-maintenance", printed)
            self.assertIn("workflow_validate exited 7", printed)
            self.assertIn("Reading budget exceeded", printed)
            self.assertIn("Detailed validator failure", printed)
            self.assertNotIn("repair-verify hook", printed)
            self.assertEqual("FAIL", output["status"])
            self.assertEqual(result, output["skill_maintenance"])

    def test_unfinished_maintenance_is_not_reported_as_success(self):
        for reason in ("invalid_candidate_id", "candidate_not_staged", "write_failed"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                code, _, output = self._invoke(
                    Path(temp), {"updated": False, "reason": reason}
                )
                self.assertEqual(1, code)
                self.assertEqual("FAIL", output["status"])

    def test_applied_and_explicitly_rejected_maintenance_stay_successful(self):
        for status in ("applied", "rejected"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                code, printed, output = self._invoke(
                    Path(temp), {"updated": True, "status": status}
                )
                self.assertEqual(0, code)
                self.assertIn("SUCCESS skill-maintenance", printed)
                self.assertEqual("SUCCESS", output["status"])


if __name__ == "__main__":
    unittest.main()
