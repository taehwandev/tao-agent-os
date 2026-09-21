from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("repair_hook_test", ROOT / "scripts" / "agent-hook.py")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class RepairVerifyCliTests(unittest.TestCase):
    def test_review_gate_alias_is_canonical_for_verification_and_resume(self):
        for command in ("repair-verify", "review"):
            args = HOOK.build_parser().parse_args([command, "--resume-checkpoint", "review hook"])
            self.assertEqual("review", args.resume_checkpoint)

    def test_other_checkpoint_names_are_not_guessed(self):
        for checkpoint in ("tests", "review", "unknown hook"):
            args = HOOK.build_parser().parse_args(["repair-verify", "--resume-checkpoint", checkpoint])
            self.assertEqual(checkpoint, args.resume_checkpoint)

    def test_failed_verification_prints_diagnostic_and_remains_failed(self):
        args = HOOK.build_parser().parse_args(["repair-verify"])
        result = {"created": True, "status": "FAIL", "returncode": 1,
                  "diagnostic": "unittest could not import the selected module"}
        with patch.object(HOOK, "preflight_evidence_path", return_value=Path("/nonexistent/preflight.json")), \
             patch.object(HOOK, "create_repair_receipt", return_value=result), \
             patch.object(HOOK, "finish_with_result", return_value=1) as finish:
            code = HOOK._run_repair_verify_hook(args)
        self.assertEqual(1, code)
        self.assertFalse(finish.call_args.args[1])
        self.assertIn(result["diagnostic"], "\n".join(finish.call_args.args[2]))


if __name__ == "__main__":
    unittest.main()
