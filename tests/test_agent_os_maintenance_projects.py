"""Retention runs for every managed checkout, with one set of rules.

The pass used to visit the Tao checkout alone, so every other project kept its
unfinished runs and evidence forever. These tests build whole projects in temp
directories; nothing here reads or writes a real checkout or the real home.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from importlib import util as importlib_util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_os_maintenance  # noqa: E402
from agent_continuation_resume import session_resume_summaries  # noqa: E402
from agent_os_maintenance import (  # noqa: E402
    managed_projects,
    run_all_maintenance,
    run_maintenance,
)
from agent_run_owner import process_owner  # noqa: E402

_spec = importlib_util.spec_from_file_location(
    "agent_os_maintenance_cli", SCRIPTS / "agent-os-maintenance.py"
)
maintenance_cli = importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(maintenance_cli)

DAY = 24 * 60 * 60


def _run_id(index: int) -> str:
    return f"{index:032x}"


def _iso(age_seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()


class ProjectFixture:
    """A checkout with a run registry and run directories of chosen ages."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs = root / ".tao" / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        self.records: list[dict] = []

    def record(self, index: int, state: str, *, age: float, owner: dict | None = None) -> str:
        run = {
            "run_id": _run_id(index),
            "state": state,
            "updated_at": _iso(age),
            "resume_generation": 0,
            "command": "bugfix",
        }
        if owner is not None:
            run["owner"] = owner
        self.records.append(run)
        self._write_registry()
        return run["run_id"]

    def directory(self, index: int, phase: str, *, age: float) -> Path:
        path = self.runs / _run_id(index)
        path.mkdir(exist_ok=True)
        (path / "continuation.json").write_text(json.dumps({"phase": phase}), encoding="utf-8")
        (path / "preflight.json").write_text("{}", encoding="utf-8")
        when = time.time() - age
        os.utime(path, (when, when))
        return path

    def registry(self) -> dict[str, str]:
        payload = json.loads((self.root / ".tao" / "run-registry.json").read_text())
        return {run["run_id"]: run["state"] for run in payload["runs"]}

    def _write_registry(self) -> None:
        (self.root / ".tao" / "run-registry.json").write_text(
            json.dumps({"schema_version": 1, "runs": self.records}), encoding="utf-8"
        )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else b"<dir>"
        for path in sorted(root.rglob("*"))
    }


class MaintenanceProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        # Neither the real search roots nor the real skill state may be touched.
        for name, value in (
            ("default_search_roots", []),
            ("env_search_roots", []),
            ("record_skill_curation", ({"status": "skipped"}, [])),
        ):
            patcher = patch.object(agent_os_maintenance, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tao_root = self.base / "tao-agent-os"
        (self.tao_root / ".tao").mkdir(parents=True)
        self.registry_file = self.base / "projects.json"

    def _register(self, *roots: Path, search_roots: list[Path] | None = None) -> None:
        self.registry_file.write_text(
            json.dumps(
                {
                    "projects": [{"root": str(root), "aliases": []} for root in roots],
                    "search_roots": [str(root) for root in search_roots or []],
                    "workspace_groups": [],
                }
            ),
            encoding="utf-8",
        )

    def test_every_managed_checkout_and_its_worktrees_are_visited(self) -> None:
        listed = ProjectFixture(self.base / "listed").root
        worktree = ProjectFixture(listed / ".tao" / "worktrees" / "task").root
        search = self.base / "src"
        found = ProjectFixture(search / "found").root
        (search / "plain").mkdir(parents=True)  # no Tao state: not visited
        missing = self.base / "gone"
        self._register(listed, missing, search_roots=[search])

        checkouts = managed_projects(self.tao_root, projects_registry=self.registry_file)

        self.assertEqual(
            [self.tao_root, listed, worktree, found],
            checkouts,
        )

    def test_a_pass_applies_retention_in_every_checkout(self) -> None:
        first = ProjectFixture(self.base / "first")
        second = ProjectFixture(self.base / "second")
        worktree = ProjectFixture(second.root / ".tao" / "worktrees" / "task")
        for fixture in (first, second, worktree):
            fixture.record(99, "completed", age=60)
            fixture.directory(1, "acting", age=20 * DAY)  # orphan past 14 days
        self._register(first.root, second.root)

        summary = run_all_maintenance(self.tao_root, projects_registry=self.registry_file)

        for fixture in (first, second, worktree):
            with self.subTest(checkout=fixture.root.name):
                self.assertFalse((fixture.runs / _run_id(1)).exists())
                result = summary["projects"][str(fixture.root)]
                self.assertEqual(1, result["pruned_run_evidence"]["removed"])

    def test_an_orphan_packet_is_removed_only_after_its_window(self) -> None:
        project = ProjectFixture(self.base / "project")
        project.record(99, "completed", age=60)
        old = project.directory(1, "acting", age=15 * DAY)
        recent = project.directory(2, "acting", age=2 * DAY)
        recorded = project.directory(99, "done", age=15 * DAY)

        evidence = run_maintenance(project.root)["pruned_run_evidence"]

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(recorded.exists())
        self.assertEqual(2, evidence["orphaned"])
        self.assertEqual(1, evidence["removed"])

    def test_a_failed_run_past_the_window_is_settled_and_leaves_resume(self) -> None:
        project = ProjectFixture(self.base / "project")
        stale = project.record(1, "failed", age=40 * DAY)
        fresh = project.record(2, "failed", age=DAY)
        stale_dir = project.directory(1, "acting", age=40 * DAY)
        project.directory(2, "acting", age=DAY)
        self.assertEqual(
            {stale, fresh}, {entry["run_id"] for entry in session_resume_summaries(project.root)}
        )

        result = run_maintenance(project.root)

        self.assertEqual(1, result["settled_runs"])
        self.assertEqual(
            [fresh], [entry["run_id"] for entry in session_resume_summaries(project.root)]
        )
        # Settled, then pruned on the same window, then its directory went too:
        # registry and run directory agree instead of leaving an orphan behind.
        self.assertNotIn(stale, project.registry())
        self.assertFalse(stale_dir.exists())
        self.assertEqual("failed", project.registry()[fresh])

    def test_a_live_owner_active_moments_ago_is_never_touched(self) -> None:
        project = ProjectFixture(self.base / "project")
        owner = process_owner()
        held = project.record(1, "failed", age=5 * 60, owner=owner)
        running = project.record(2, "running", age=5 * 60, owner=owner)
        finished = project.record(3, "completed", age=5 * 60, owner=owner)
        held_dir = project.directory(1, "acting", age=40 * DAY)
        running_dir = project.directory(2, "acting", age=40 * DAY)
        finished_dir = project.directory(3, "done", age=40 * DAY)

        result = run_maintenance(project.root, retention_seconds=60)

        self.assertEqual(0, result["settled_runs"])
        registry = project.registry()
        self.assertEqual("failed", registry[held])
        self.assertEqual("running", registry[running])
        for path in (held_dir, running_dir, finished_dir):
            self.assertTrue(path.exists(), path.name)
        self.assertIn(finished, registry)

    def test_a_dry_run_prints_counts_and_changes_nothing(self) -> None:
        project = ProjectFixture(self.base / "project")
        project.record(1, "failed", age=40 * DAY)
        project.record(99, "completed", age=60)
        project.directory(1, "acting", age=40 * DAY)
        project.directory(2, "acting", age=20 * DAY)
        self._register(project.root)
        before = _snapshot(self.base)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = maintenance_cli.main(
                [
                    "--all-projects",
                    "--dry-run",
                    "--project",
                    str(self.tao_root),
                    "--projects-registry",
                    str(self.registry_file),
                ]
            )

        self.assertEqual(0, code)
        self.assertEqual(before, _snapshot(self.base))
        lines = output.getvalue().splitlines()
        line = next(item for item in lines if item.startswith(f"{project.root}:"))
        self.assertIn("settle_runs=1", line)
        self.assertIn("registry_prune=1", line)
        self.assertIn("run_dirs removable=2", line)
        self.assertIn("orphaned=1", line)
        self.assertTrue(any(item.startswith(f"{self.tao_root}:") for item in lines))
        self.assertIn("dry run, nothing changed", lines[-1])

    def test_an_unreadable_registry_never_makes_every_run_an_orphan(self) -> None:
        project = ProjectFixture(self.base / "project")
        (project.root / ".tao" / "run-registry.json").write_text("{", encoding="utf-8")
        path = project.directory(1, "acting", age=20 * DAY)

        evidence = run_maintenance(project.root, dry_run=True)["pruned_run_evidence"]

        self.assertEqual(0, evidence["orphaned"])
        self.assertEqual(0, evidence["removable"])
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
