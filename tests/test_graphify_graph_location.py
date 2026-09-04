"""The graph is where it is, not where the contract wishes it were.

Setup asks graphify to write under `.agents/local/graphify-out`. The commit
hooks are installed by graphify's own installer, carry no such assignment, and
write to the CLI default at the repository root. Asserting only the first path
left this repository's agents reading an empty directory while the only graph
on disk -- rebuilt on every branch switch -- sat in the second.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.graphify_contract import (  # noqa: E402
    FALLBACK_GRAPH_DIR,
    PROJECT_GRAPH_DIR,
    resolve_graph_path,
)


class ResolveGraphPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)

    def _write(self, relative: Path, *, age_seconds: int = 0) -> Path:
        path = self.project / relative / "graph.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"nodes": []}', encoding="utf-8")
        if age_seconds:
            when = path.stat().st_mtime - age_seconds
            os.utime(path, (when, when))
        return path

    def test_a_project_with_no_graph_answers_none(self) -> None:
        self.assertIsNone(resolve_graph_path(self.project))

    def test_the_redirected_location_is_found(self) -> None:
        expected = self._write(PROJECT_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_cli_default_is_found_when_nothing_redirected_it(self) -> None:
        """This is the ordinary case, and the one that used to read as absent."""

        expected = self._write(FALLBACK_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_newer_graph_wins_when_both_exist(self) -> None:
        self._write(PROJECT_GRAPH_DIR, age_seconds=3600)
        expected = self._write(FALLBACK_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_redirected_graph_wins_when_it_is_not_older(self) -> None:
        expected = self._write(PROJECT_GRAPH_DIR)
        self._write(FALLBACK_GRAPH_DIR, age_seconds=3600)

        self.assertEqual(expected, resolve_graph_path(self.project))


if __name__ == "__main__":
    unittest.main()
