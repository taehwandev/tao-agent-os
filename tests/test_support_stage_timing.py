"""Recording where a hook's time went, without recording what it was doing.

Local checks measure under a second while whole tasks run for minutes, so the
next reduction should start from evidence rather than another guess. These
tests hold the recording to the two things that make it usable: the numbers
survive a hook that was asked for no result file -- which is how the lifecycle
invokes review and finish -- and nothing but stage names and durations goes
with them.
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

# A run directory is named by an opaque run id; start refuses any other name,
# because a packet binds to that name and a readable one silently loses it.
RUN_ID = "0123456789abcdef0123456789abcdef"

from agent_hook_runtime import finish_with_result
from support.stage_timing import (
    append_recorded_stages,
    recorded_stages,
    reset_stages,
    set_timing_sink,
    stage,
    timing_sink,
)


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
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
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


class DiscoveryStagesTests(unittest.TestCase):
    """Routing is most of a start, and search is most of routing.

    A single `preflight` number said a start was slow without saying which
    part: profiling put 63% of it in document discovery, split between a
    wikimap index refresh and a graph build. Recording them separately is
    what lets the next reduction pick between those two rather than guess.
    """

    def setUp(self) -> None:
        from support.stage_timing import reset_stages

        import workflow_doc_graph_build
        from workflow_wikimap import clear_wikimap_cache

        # Both caches are per process, which is why every hook pays them once
        # and why a test that does not clear them measures the second call.
        reset_stages()
        workflow_doc_graph_build.clear_doc_graph_cache()
        clear_wikimap_cache()
        self.addCleanup(reset_stages)
        self.addCleanup(workflow_doc_graph_build.clear_doc_graph_cache)
        self.addCleanup(clear_wikimap_cache)

    def test_a_cold_route_records_search_and_graph_separately(self) -> None:
        from workflow_route import resolve_docs

        resolve_docs(
            "task", None, [],
            request_text="bound every local git read",
            project_root=ROOT,
        )
        timings = recorded_stages()

        for expected in ("doc_search", "doc_graph_build", "wikimap_index"):
            with self.subTest(stage=expected):
                self.assertIn(expected, timings)

    def test_the_parts_of_a_search_are_reported_separately(self) -> None:
        """One number for a stage cannot say which half to look at.

        Profiling a start put 384 ms in document search, 196 of it refreshing
        the wikimap index and most of the rest querying it -- two subprocesses
        with different reasons to be slow. Required-document resolution added
        another 88 ms that no stage reported at all.
        """

        from workflow_route import resolve_docs

        resolve_docs(
            "task", None, [],
            request_text="bound every local git read",
            project_root=ROOT,
        )
        timings = recorded_stages()

        for expected in ("wikimap_index", "wikimap_search", "required_docs",
                         "doc_graph_expand"):
            with self.subTest(stage=expected):
                self.assertIn(expected, timings)

    def test_search_covers_the_index_refresh_inside_it(self) -> None:
        """Nested stages must nest, or the numbers cannot be read as parts."""

        from workflow_route import resolve_docs

        resolve_docs(
            "task", None, [],
            request_text="bound every local git read",
            project_root=ROOT,
        )
        timings = recorded_stages()

        self.assertGreaterEqual(timings["doc_search"], timings["wikimap_index"])



class TimingsSurviveAHookWithNoResultFileTests(unittest.TestCase):
    """`--output` is optional, and the lifecycle's own hooks do not pass it.

    Recording the durations into the hook result measured everything and kept
    nothing: `review` and `finish` are invoked with no output path, so their
    numbers were computed and dropped. The run-local file is what makes the
    measurement outlive the invocation that took it.
    """

    def setUp(self) -> None:
        reset_stages()
        self.addCleanup(reset_stages)

    def _lines(self, sink: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in sink.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def test_an_invocation_leaves_its_numbers_where_the_run_is(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "runs" / "one" / "timings.jsonl"
            set_timing_sink(sink)
            with stage("vibeguard"):
                time.sleep(0.01)

            append_recorded_stages("review", "SUCCESS")

            record = self._lines(sink)[0]

        self.assertEqual("review", record["hook"])
        self.assertEqual("SUCCESS", record["status"])
        self.assertGreaterEqual(record["timings"]["vibeguard"], 5)

    def test_a_failing_hook_records_the_time_it_spent_failing(self) -> None:
        """The slow hooks worth tuning are often the ones that refuse."""

        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "timings.jsonl"
            set_timing_sink(sink)
            with stage("preflight"):
                pass

            append_recorded_stages("finish", "FAIL")

            record = self._lines(sink)[0]

        self.assertEqual("FAIL", record["status"])

    def test_the_shared_result_writer_records_nothing_by_itself(self) -> None:
        """Any direct caller of a hook function reaches that writer.

        A test process that had already resolved a live run kept appending
        through it, which is how run directories collected records for hooks
        nobody invoked.
        """

        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "timings.jsonl"
            set_timing_sink(sink)
            with stage("preflight"):
                pass

            finish_with_result("review", True, ["detail"], None, {}, 0)

            self.assertFalse(sink.exists())

    def test_every_hook_in_one_run_is_kept_not_overwritten(self) -> None:
        """A run is a lifecycle; one hook's numbers do not answer the question."""

        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "timings.jsonl"
            set_timing_sink(sink)
            for name in ("start", "gate-batch", "review", "finish"):
                with stage("preflight"):
                    pass
                append_recorded_stages(name, "SUCCESS")

            recorded = [line["hook"] for line in self._lines(sink)]

        self.assertEqual(["start", "gate-batch", "review", "finish"], recorded)

    def test_nothing_is_written_when_no_sink_was_named(self) -> None:
        """Hooks that never resolve a run directory have nowhere to put them."""

        with tempfile.TemporaryDirectory() as directory:
            with stage("preflight"):
                pass

            append_recorded_stages("resume", "SUCCESS")

            self.assertEqual([], list(Path(directory).iterdir()))

    def test_a_hook_that_named_no_stage_still_reports_its_total(self) -> None:
        """An unmeasured hook is not a free one, and a lifecycle is its sum.

        `gate-batch` names no stage and spends seconds anyway; skipping it
        would make the run-local numbers add up to less than the wait.
        """

        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "timings.jsonl"
            set_timing_sink(sink)

            append_recorded_stages("gate-batch", "SUCCESS")

            record = self._lines(sink)[0]

        self.assertEqual(["hook_total"], list(record["timings"]))
        self.assertGreater(record["timings"]["hook_total"], 0)

    def test_an_unwritable_sink_does_not_raise(self) -> None:
        """Measurement must never be the reason a lifecycle hook refuses."""

        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "blocker"
            blocker.write_text("not a directory\n", encoding="utf-8")
            set_timing_sink(blocker / "runs" / "timings.jsonl")
            with stage("preflight"):
                pass

            self.assertIsNone(append_recorded_stages("review", "SUCCESS"))

    def test_the_line_carries_names_and_numbers_and_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "timings.jsonl"
            set_timing_sink(sink)
            with stage("preflight"):
                pass
            append_recorded_stages("start", "SUCCESS")

            record = self._lines(sink)[0]

        self.assertEqual(
            {"hook", "status", "recorded_at", "timings"}, set(record)
        )
        self.assertTrue(all(isinstance(value, int) for value in record["timings"].values()))


class OnlyTheHookProcessNamesTheSinkTests(unittest.TestCase):
    """Naming the sink from a path resolver made every caller a recorder.

    The resolver knows the run directory, which is why it was the tempting
    place. But anything that resolves an evidence path would then be naming a
    sink, and the test suite resolves plenty of them against this repository
    with no hook running: live runs collected 22-27 second records for hooks
    that were never invoked, which is the process lifetime of the test run.
    Those numbers were then read as a performance finding.
    """

    def setUp(self) -> None:
        reset_stages()
        self.addCleanup(reset_stages)

    def _args(self, project: Path, hook: str = "review"):
        import types

        return types.SimpleNamespace(
            project=project,
            evidence=project / ".tao" / "runs" / RUN_ID / "preflight.json",
            hook=hook,
        )

    def test_resolving_an_evidence_path_names_nothing(self) -> None:
        from agent_hook_gate_records import preflight_evidence_path

        with tempfile.TemporaryDirectory() as directory:
            args = self._args(Path(directory))

            resolved = preflight_evidence_path(args)

        self.assertEqual(args.evidence, resolved)
        self.assertIsNone(timing_sink())

    def test_the_hook_entry_points_the_timings_at_that_run(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agent_hook_for_timing_sink", ROOT / "scripts" / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            args = self._args(Path(directory))

            module._name_timing_sink(args)

            self.assertEqual(args.evidence.parent / "timings.jsonl", timing_sink())

    def test_a_listing_hook_adopts_no_run(self) -> None:
        """`resume` promises to leave the registry byte-identical."""

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agent_hook_for_timing_sink_resume", ROOT / "scripts" / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            module._name_timing_sink(self._args(Path(directory), hook="resume"))

        self.assertIsNone(timing_sink())


class TheHooksLeaveTheirNumbersInTheRunTests(unittest.TestCase):
    """The end the numbers are for: a real hook, no --output, a readable file."""

    def test_a_real_start_without_an_output_path_still_records(self) -> None:
        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            evidence.parent.mkdir(parents=True)

            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "probe the timing wiring",
                    "--read-only", "--evidence", str(evidence),
                ],
                cwd=project, capture_output=True, text=True,
                env={**os.environ, "TAO_STATE_HOME": state},
            )
            sink = evidence.parent / "timings.jsonl"
            recorded = json.loads(sink.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual("start", recorded["hook"])
        self.assertIn("preflight", recorded["timings"])


if __name__ == "__main__":
    unittest.main()
