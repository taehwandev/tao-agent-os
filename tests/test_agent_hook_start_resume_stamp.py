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


if __name__ == "__main__":
    unittest.main()
