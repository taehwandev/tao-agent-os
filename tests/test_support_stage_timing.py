"""Recording where a hook's time went, without recording what it was doing.

Local checks measure under a second while whole tasks run for minutes, so the
next reduction should start from evidence rather than another guess. These
tests hold the recording to the two things that make it usable: the numbers
reach the evidence every hook already writes, and nothing but stage names and
durations goes with them.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_hook_runtime import finish_with_result
from support.stage_timing import recorded_stages, reset_stages, stage


class StageTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_stages()
        self.addCleanup(reset_stages)

    def test_a_stage_that_runs_twice_reports_one_accumulated_cost(self) -> None:
        """Two status checks in one review are one wait for the person."""

        for _ in range(2):
            with stage("repeated"):
                time.sleep(0.01)

        timings = recorded_stages()

        self.assertGreaterEqual(timings["repeated"], 15)

    def test_nothing_is_reported_when_no_stage_ran(self) -> None:
        self.assertEqual({}, recorded_stages())

    def test_the_total_covers_the_process_not_just_the_stages(self) -> None:
        with stage("part"):
            time.sleep(0.01)

        timings = recorded_stages()

        self.assertGreaterEqual(timings["hook_total"], timings["part"])


class TimingsReachTheEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_stages()
        self.addCleanup(reset_stages)

    def _written(self, name: str = "review") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hook.json"
            finish_with_result(name, True, ["detail"], output, {}, 0)
            return json.loads(output.read_text(encoding="utf-8"))

    def test_the_hook_record_carries_what_each_stage_cost(self) -> None:
        with stage("workflow_validate"):
            time.sleep(0.01)

        record = self._written()

        self.assertIn("workflow_validate", record["timings"])
        self.assertGreaterEqual(record["timings"]["workflow_validate"], 5)

    def test_a_hook_that_timed_nothing_adds_no_key(self) -> None:
        """Absent rather than empty, so an untimed hook reads as untimed."""

        self.assertNotIn("timings", self._written())

    def test_only_names_and_numbers_are_recorded(self) -> None:
        """The record is content-free evidence; timings must not change that."""

        with stage("preflight"):
            pass

        timings = self._written()["timings"]

        self.assertTrue(all(isinstance(key, str) for key in timings))
        self.assertTrue(all(isinstance(value, int) for value in timings.values()))


class TheHooksAreActuallyInstrumentedTests(unittest.TestCase):
    """The mechanism working proves nothing about the hooks using it.

    A wrapper can be removed from a call site without breaking any test of
    the timer itself, which is exactly how instrumentation rots. This runs a
    real hook and reads its own record back.
    """

    def test_a_real_start_records_the_stage_it_spent_its_time_in(self) -> None:
        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            evidence = project / ".tao" / "runs" / "probe" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            output = project / ".tao" / "start.json"

            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "probe the timing wiring",
                    "--read-only", "--evidence", str(evidence), "--output", str(output),
                ],
                cwd=project, capture_output=True, text=True,
                env={**os.environ, "TAO_STATE_HOME": state},
            )
            record = json.loads(output.read_text(encoding="utf-8"))

        self.assertIn("preflight", record.get("timings", {}))
        self.assertGreater(record["timings"]["hook_total"], 0)


if __name__ == "__main__":
    unittest.main()
