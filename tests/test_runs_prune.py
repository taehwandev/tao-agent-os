"""Retention removes evidence, so every rule is stated from the keeping side.

The expensive mistake is not keeping too much. It is removing a run someone
could still resume, which is why an unreadable packet counts as unfinished and
why the name has to look like a run id before anything is touched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("runs_prune", SCRIPTS / "runs-prune.py")
runs_prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runs_prune)

# The rules live in an importable module; the script above only prints them.
# That split is what let the maintenance pass call this policy at all -- a
# hyphen in a filename is why nothing could.
from agent_os_maintenance import run_maintenance  # noqa: E402
from agent_run_evidence import prune_run_evidence  # noqa: E402


def _run_id(index: int) -> str:
    return f"{index:032x}"


class RunsPruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.runs = runs_prune.runs_dir(self.project)
        self.runs.mkdir(parents=True)
        self.clock = 1_700_000_000

    def _run(self, index: int, phase: str | None, *, packet: bool = True) -> Path:
        path = self.runs / _run_id(index)
        path.mkdir()
        (path / "preflight.json").write_text("{}", encoding="utf-8")
        if packet:
            body = "{" if phase is None else json.dumps({"phase": phase})
            (path / "continuation.json").write_text(body, encoding="utf-8")
        # Ordering is by mtime, so it is set rather than inferred from creation.
        self.clock += 60
        os.utime(path, (self.clock, self.clock))
        return path

    def _names(self, paths: list[Path]) -> set[str]:
        return {path.name for path in paths}

    def _plan(self, **arguments) -> dict:
        """Plan as of just after the last run was touched.

        The fixture sets mtimes on an artificial clock in the past, so without
        a stated `now` every run in it would read as abandoned. Age is a rule
        worth testing on purpose, not one worth tripping over everywhere.
        """

        arguments.setdefault("now", self.clock + 1)
        return runs_prune.plan(self.project, **arguments)

    def test_the_newest_finished_runs_are_kept(self) -> None:
        for index in range(5):
            self._run(index, "done")

        report = self._plan(keep=2)

        self.assertEqual({_run_id(4), _run_id(3)}, self._names(report["kept"]))
        self.assertEqual(
            {_run_id(0), _run_id(1), _run_id(2)}, self._names(report["removable"])
        )

    def test_an_unfinished_run_that_could_still_resume_is_not_removable(self) -> None:
        # Its packet is the only record of where it stopped.
        for phase in ("reviewing", "acting", "blocked", "scoped"):
            with self.subTest(phase=phase):
                path = self._run(hash(phase) % 1000, phase)
                report = self._plan(keep=0)

                self.assertIn(path.name, self._names(report["unfinished"]))
                self.assertNotIn(path.name, self._names(report["removable"]))

    def test_an_unfinished_run_left_for_the_window_is_abandoned(self) -> None:
        """Unfinished is not immortal, or retention reclaims almost nothing.

        On the reference machine 34 of 58 runs were unfinished, some three
        weeks old, and the rule that kept every one of them forever is why the
        pass could free 1.2 MB of 28.8 -- 4%. A run nobody has touched for the
        retention window was abandoned, not paused.
        """

        path = self._run(1, "reviewing")

        report = self._plan(keep=0, now=self.clock + runs_prune.DEFAULT_ABANDONED_AFTER_SECONDS + 1)

        self.assertIn(path.name, self._names(report["abandoned"]))
        self.assertIn(path.name, self._names(report["removable"]))
        self.assertNotIn(path.name, self._names(report["unfinished"]))

    def test_the_abandonment_window_is_the_callers_to_set(self) -> None:
        """Maintenance passes the same window the registry prunes records on."""

        path = self._run(1, "acting")

        report = self._plan(keep=0, abandoned_after_seconds=30, now=self.clock + 31)

        self.assertIn(path.name, self._names(report["removable"]))

    def test_a_human_named_directory_is_never_abandoned(self) -> None:
        """Age does not authorise removing evidence a person named."""

        named = self.runs / "ship-discovery-20260819"
        named.mkdir()
        os.utime(named, (self.clock, self.clock))

        report = self._plan(keep=0, now=self.clock + runs_prune.DEFAULT_ABANDONED_AFTER_SECONDS + 1)

        self.assertEqual({named.name}, self._names(report["unclassified"]))
        self.assertEqual([], report["removable"])

    def test_an_unreadable_packet_counts_as_unfinished(self) -> None:
        """Retention fails towards keeping a run whose state it cannot read."""

        broken = self._run(1, None)
        absent = self._run(2, None, packet=False)

        report = self._plan(keep=0)

        self.assertEqual({broken.name, absent.name}, self._names(report["unfinished"]))
        self.assertEqual(set(), self._names(report["removable"]))

    def test_a_directory_that_is_not_a_run_id_is_kept_and_reported(self) -> None:
        """Left alone is right; left out of the report is not.

        This directory also holds evidence under human-chosen names -- 45 of
        them on the reference machine against 51 opaque ids. Counting only the
        ids reads as a total when it is not one.
        """

        names = {"ship-discovery-20260819", "0" * 31, "0" * 33, "z" * 32}
        for name in names:
            (self.runs / name).mkdir()

        report = self._plan(keep=0)

        self.assertEqual([], report["finished"])
        self.assertEqual([], report["unfinished"])
        self.assertEqual([], report["removable"])
        self.assertEqual(names, self._names(report["unclassified"]))

    def test_apply_removes_only_what_the_plan_named(self) -> None:
        kept = self._run(1, "done")
        open_run = self._run(2, "reviewing")
        stale = self._run(3, "done")
        # `stale` is newest by mtime, so make `kept` the newest instead.
        self.clock += 60
        os.utime(kept, (self.clock, self.clock))

        report = self._plan(keep=1)
        removed = runs_prune.apply_plan(report["removable"])

        self.assertEqual(1, removed)
        self.assertFalse(stale.exists())
        self.assertTrue(kept.exists())
        self.assertTrue(open_run.exists())

    def test_a_report_removes_nothing(self) -> None:
        for index in range(3):
            self._run(index, "done")

        code = runs_prune.main(["--project", str(self.project), "--keep", "0"])

        self.assertEqual(0, code)
        self.assertEqual(3, len(list(self.runs.iterdir())))

    def test_apply_removes_and_reports_success(self) -> None:
        for index in range(3):
            self._run(index, "done")

        code = runs_prune.main(
            ["--project", str(self.project), "--keep", "1", "--apply"]
        )

        self.assertEqual(0, code)
        self.assertEqual(1, len(list(self.runs.iterdir())))

    def test_a_missing_run_directory_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(0, runs_prune.main(["--project", empty]))


class MaintenanceRunsThisPolicyTests(unittest.TestCase):
    """The policy existed and nothing called it, which is the whole defect.

    `prune_runtime_state` had pruned the registry's *records* on a thirty-day
    window since the first day; the directories those records pointed at were
    pruned by nothing, because the only file that knew how to do it has a
    hyphen in its name and cannot be imported.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.runs = runs_prune.runs_dir(self.project)
        self.runs.mkdir(parents=True)

    def _run(self, index: int, phase: str, age_seconds: int) -> Path:
        path = self.runs / _run_id(index)
        path.mkdir()
        (path / "continuation.json").write_text(
            json.dumps({"phase": phase}), encoding="utf-8"
        )
        (path / "preflight.json").write_text("x" * 100, encoding="utf-8")
        when = time.time() - age_seconds
        os.utime(path, (when, when))
        return path

    def test_the_maintenance_pass_removes_what_nothing_can_resume(self) -> None:
        abandoned = self._run(1, "reviewing", age_seconds=60 * 60 * 24 * 40)
        live = self._run(2, "reviewing", age_seconds=60)

        summary = run_maintenance(self.project)["pruned_run_evidence"]

        self.assertFalse(abandoned.exists())
        self.assertTrue(live.exists())
        self.assertEqual(1, summary["removed"])
        self.assertEqual(1, summary["abandoned"])
        self.assertEqual(1, summary["unfinished"])

    def test_what_it_will_not_remove_is_counted_rather_than_hidden(self) -> None:
        named = self.runs / "ship-discovery-20260819"
        named.mkdir()
        (named / "preflight.json").write_text("x" * 100, encoding="utf-8")

        summary = prune_run_evidence(self.project)

        self.assertTrue(named.exists())
        self.assertEqual(1, summary["unclassified"])
        self.assertEqual(100, summary["unclassified_bytes"])

    def test_a_report_only_pass_removes_nothing(self) -> None:
        abandoned = self._run(1, "acting", age_seconds=60 * 60 * 24 * 40)

        summary = prune_run_evidence(self.project, apply=False)

        self.assertTrue(abandoned.exists())
        self.assertEqual(0, summary["removed"])
        self.assertEqual(0, summary["freed_bytes"])
        # Reported anyway: what a report is for is knowing the size before
        # agreeing to lose it.
        self.assertGreater(summary["removable_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
