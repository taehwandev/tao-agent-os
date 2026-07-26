from __future__ import annotations

import tempfile
import unittest
import multiprocessing as mp
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_context_store import (
    context_snapshot_failures_are_replaceable,
    refresh_and_validate_context_snapshot,
    refresh_context_snapshot,
    validate_context_snapshot,
)


def _refresh_context_worker(args: tuple[str, str, int]) -> list[str]:
    project, rules, index = args
    route = {"required_docs": ["AGENTS.md"], "gates": [], "request_classified": True}
    intake = {"request_classified": True, "request": f"parallel-{index}"}
    return refresh_and_validate_context_snapshot(Path(project), Path(rules), route, intake)[1]


class AgentContextStoreTests(unittest.TestCase):
    def test_snapshot_refresh_and_validation_follow_route_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            rules = ROOT
            route = {"required_docs": ["AGENTS.md"], "gates": []}
            intake = {"request_classified": True, "request_fingerprint": "opaque"}
            snapshot = refresh_context_snapshot(project, rules, route, intake)
            self.assertEqual("AGENTS.md", snapshot["required_docs"][0]["path"])
            self.assertEqual([], validate_context_snapshot(project, rules, route, intake))

    def test_route_change_invalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            refresh_context_snapshot(project, ROOT, {"required_docs": ["AGENTS.md"], "gates": []})
            failures = validate_context_snapshot(project, ROOT, {"required_docs": [], "gates": []})
            self.assertTrue(failures)

    def test_request_change_invalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            route = {"required_docs": ["AGENTS.md"], "gates": []}
            refresh_context_snapshot(project, ROOT, route, {"request_classified": True, "request": "one"})
            failures = validate_context_snapshot(project, ROOT, route, {"request_classified": True, "request": "two"})
            self.assertIn("request fingerprint", failures[0])

    def test_required_doc_change_is_replaceable_at_a_fresh_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            rules = root / "rules"
            project.mkdir()
            rules.mkdir()
            agents = rules / "AGENTS.md"
            agents.write_text("first\n", encoding="utf-8")
            route = {"required_docs": ["AGENTS.md"], "gates": []}

            refresh_context_snapshot(project, rules, route)
            agents.write_text("second version\n", encoding="utf-8")
            failures = validate_context_snapshot(project, rules, route)

            self.assertTrue(failures)
            self.assertTrue(context_snapshot_failures_are_replaceable(failures))

    def test_unavailable_required_doc_is_not_replaceable(self) -> None:
        failures = ["execution capsule required doc is unavailable: AGENTS.md"]

        self.assertFalse(context_snapshot_failures_are_replaceable(failures))

    def test_parallel_refresh_and_validation_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".tao").mkdir()
            args = [(str(project), str(ROOT), index) for index in range(12)]
            with mp.get_context("fork").Pool(4) as pool:
                failures = pool.map(_refresh_context_worker, args)
            self.assertEqual([], [failure for result in failures for failure in result])


if __name__ == "__main__":
    unittest.main()
