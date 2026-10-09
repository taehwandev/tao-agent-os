"""A refreshed start must preserve a resumed run's session generation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("agent_hook_resume_stamp_test", SCRIPTS / "agent-hook.py")
assert spec and spec.loader
agent_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_hook)


class StartResumeStampTests(unittest.TestCase):
    def test_refreshed_start_stamps_claimed_resume_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / ("a" * 32) / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({
                "runtime_session": {"runtime": "codex", "session_id": "session"},
                "route": {"command": "bugfix"},
                "request_intake": {"request": "repair"},
            }), encoding="utf-8")
            args = Namespace(project=project, rules=ROOT, evidence=evidence)
            claim = {"run_id": "a" * 32, "resume_generation": 1}

            with (
                patch.object(agent_hook, "resync_gate_evidence_ledger"),
                patch.object(agent_hook, "register_run", return_value={"run_id": "a" * 32, "state": "running"}),
                patch.object(agent_hook, "settle_superseded_session_runs", return_value=[]),
            ):
                self.assertTrue(agent_hook._register_started_run(args, [], claim))

            recorded = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(1, recorded["runtime_session"]["resume_generation"])

    def test_settling_superseded_runs_is_reported_but_not_counted_as_a_block(self) -> None:
        # The start succeeded; recording it as a block put 55 successful
        # starts a week into the recurring-block report.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / ("a" * 32) / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({"route": {"command": "bugfix"}}), encoding="utf-8")
            args = Namespace(project=project, rules=ROOT, evidence=evidence)
            details: list[str] = []

            with (
                patch.object(agent_hook, "resync_gate_evidence_ledger"),
                patch.object(agent_hook, "register_run", return_value={"run_id": "a" * 32, "state": "running"}),
                patch.object(agent_hook, "settle_superseded_session_runs", return_value=["b" * 32]),
                patch.object(agent_hook, "_learn_start_block") as learned,
            ):
                self.assertTrue(agent_hook._register_started_run(args, details, {"run_id": "a" * 32}))

            learned.assert_not_called()
            self.assertIn("agent run registry: settled 1 superseded run(s) from this runtime session", details)


if __name__ == "__main__":
    unittest.main()
