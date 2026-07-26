from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_run_registry import (
    active_run_conflict,
    active_runs,
    recover_stale_runs,
    register_run,
    resume_run,
    transition_run,
)


class AgentRunRegistryTests(unittest.TestCase):
    def test_register_and_transition_run_without_content_or_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            run = register_run(
                project,
                evidence,
                {"command": "task", "gates": [], "required_docs": []},
                {"request": "private request text", "request_classified": True},
            )

            self.assertEqual("running", run["state"])
            self.assertNotIn("private request text", json.dumps(run))
            self.assertNotIn(str(project), json.dumps(run))
            self.assertEqual([run["run_id"]], [item["run_id"] for item in active_runs(project)])

            completed = transition_run(project, evidence, "completed")
            self.assertEqual("completed", completed["state"])
            self.assertEqual([], active_runs(project))

    def test_unknown_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                transition_run(Path(directory), Path(directory) / "preflight.json", "unknown")

    def test_run_id_transition_avoids_same_evidence_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / "preflight.json"
            first = register_run(project, evidence, {"command": "task"}, {})
            second = register_run(project, evidence, {"command": "task"}, {})
            completed = transition_run(project, evidence, "completed", run_id=first["run_id"])
            self.assertEqual(first["run_id"], completed["run_id"])
            self.assertEqual("running", [run for run in active_runs(project) if run["run_id"] == second["run_id"]][0]["state"])

    def test_stale_run_is_recovered_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = register_run(project, project / "preflight.json", {"command": "task"}, {})
            registry = project / ".tao" / "run-registry.json"
            payload = json.loads(registry.read_text())
            old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            payload["runs"][-1]["updated_at"] = old
            registry.write_text(json.dumps(payload), encoding="utf-8")

            recovered = recover_stale_runs(project, stale_after_seconds=60)
            self.assertEqual([run["run_id"]], [item["run_id"] for item in recovered])
            self.assertEqual("failed", recovered[0]["state"])
            self.assertEqual("running", resume_run(project, run["run_id"])["state"])

    def test_active_request_cannot_overwrite_the_same_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "preflight.json"
            register_run(
                project,
                evidence,
                {"command": "task"},
                {"request": "first", "request_classified": False},
            )

            self.assertTrue(
                active_run_conflict(
                    project,
                    evidence,
                    command="task",
                    request_intake={"request": "second", "request_classified": False},
                )
            )
            self.assertFalse(
                active_run_conflict(
                    project,
                    project / ".tao" / "runs" / "second" / "preflight.json",
                    command="task",
                    request_intake={"request": "second", "request_classified": False},
                )
            )

            persisted = (project / ".tao" / "run-registry.json").read_text()
            self.assertNotIn("first", persisted)
            self.assertNotIn("second", persisted)


if __name__ == "__main__":
    unittest.main()
