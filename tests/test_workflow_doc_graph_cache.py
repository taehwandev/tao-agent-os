"""The document graph is rebuilt only when the documents change.

Every hook that validates a workflow builds this graph, and each hook is its
own process, so the per-process ``lru_cache`` never helped the next one: a
lifecycle paid the build once in ``start`` and again in ``review``.

The key is the documents themselves -- their paths, sizes and modification
times -- and deliberately not a worktree signature. Between a start and the
review that follows it an agent has edited source, so a worktree key would miss
every time it mattered.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import workflow_doc_graph_build as build


class DocGraphCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        build.clear_doc_graph_cache()
        self.addCleanup(build.clear_doc_graph_cache)

    def _project(self, directory: str, *, state: bool = True) -> Path:
        project = Path(directory)
        (project / ".tao").mkdir() if state else None
        (project / "AGENTS.md").write_text("# guide\n\nsee [other](other.md)\n", encoding="utf-8")
        (project / "other.md").write_text("# other\n", encoding="utf-8")
        return project

    def _cache(self, project: Path) -> Path:
        return project / ".tao" / "cache" / "doc-graph"

    def test_a_second_build_of_unchanged_documents_does_not_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)

            first = build.build_doc_graph(project)
            build.clear_doc_graph_cache()
            with patch.object(build, "_graph_for", side_effect=AssertionError("rebuilt")):
                second = build.build_doc_graph(project)

        self.assertEqual(first, second)

    def test_a_changed_document_is_rebuilt(self) -> None:
        """Size and modification time are what the key reads."""

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            build.build_doc_graph(project)
            build.clear_doc_graph_cache()
            (project / "other.md").write_text(
                "# other\n\nsee [guide](AGENTS.md)\n", encoding="utf-8"
            )

            rebuilt = build.build_doc_graph(project)

        self.assertTrue(rebuilt["other.md"], "the new link should be an edge")


    def test_an_edit_that_keeps_the_size_is_still_a_change(self) -> None:
        """Size alone would serve a stale graph for a same-length edit.

        `alpha.md` and `omega.md` are the same length, so the two versions of
        the document are byte-for-byte the same size and differ only in where
        the link points.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            (project / "alpha.md").write_text("# alpha\n", encoding="utf-8")
            (project / "omega.md").write_text("# omega\n", encoding="utf-8")
            (project / "other.md").write_text("[x](alpha.md)\n", encoding="utf-8")
            first = build.build_doc_graph(project)
            build.clear_doc_graph_cache()

            rewritten = "[x](omega.md)\n"
            self.assertEqual(
                len(rewritten.encode()), (project / "other.md").stat().st_size
            )
            (project / "other.md").write_text(rewritten, encoding="utf-8")
            second = build.build_doc_graph(project)

        self.assertEqual({"alpha.md"}, {edge["target"] for edge in first["other.md"]})
        self.assertEqual({"omega.md"}, {edge["target"] for edge in second["other.md"]})

    def test_a_new_document_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            build.build_doc_graph(project)
            build.clear_doc_graph_cache()
            (project / "third.md").write_text("# third\n", encoding="utf-8")

            rebuilt = build.build_doc_graph(project)

        self.assertIn("third.md", rebuilt)


    def test_a_changed_surface_rule_is_rebuilt(self) -> None:
        """The graph is built from the rules file too, not only the documents.

        `doc_set`, request-intent and path-surface rules all add edges. Keying
        on the documents alone served a stale graph: the rules changed, the
        graph changed, and the key did not.
        """

        from workflow_doc_surfaces import RULES_FILE

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            (project / "alpha.md").write_text("# alpha\n", encoding="utf-8")
            (project / "omega.md").write_text("# omega\n", encoding="utf-8")
            rules = project / RULES_FILE
            rules.write_text(
                json.dumps({"schema_version": 1, "doc_sets": {}}), encoding="utf-8"
            )
            before = build.build_doc_graph(project)
            build.clear_doc_graph_cache()

            rules.write_text(
                json.dumps(
                    {"schema_version": 1, "doc_sets": {"pair": ["alpha.md", "omega.md"]}}
                ),
                encoding="utf-8",
            )
            after = build.build_doc_graph(project)

        # The pair rule adds an edge in each direction, on top of whatever the
        # fixture's own document links contribute.
        self.assertEqual(
            sum(len(edges) for edges in before.values()) + 2,
            sum(len(edges) for edges in after.values()),
        )
        self.assertEqual({"omega.md"}, {edge["target"] for edge in after["alpha.md"]})

    def test_a_project_with_no_surface_rules_still_caches(self) -> None:
        """Having none is a state, not a reason to stop caching."""

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)

            first = build.build_doc_graph(project)
            build.clear_doc_graph_cache()
            with patch.object(build, "_graph_for", side_effect=AssertionError("rebuilt")):
                second = build.build_doc_graph(project)

        self.assertEqual(first, second)

    def test_a_project_with_no_run_state_stores_nothing(self) -> None:
        """`.tao` carries the ignore file; creating one here could be committed."""

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory, state=False)

            graph = build.build_doc_graph(project)

            self.assertIn("AGENTS.md", graph)
            self.assertFalse((project / ".tao").exists())

    def test_an_unreadable_generation_is_built_instead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            expected = build.build_doc_graph(project)
            build.clear_doc_graph_cache()
            for stored in self._cache(project).glob("*.json"):
                stored.write_text("{not json", encoding="utf-8")

            self.assertEqual(expected, build.build_doc_graph(project))

    def test_the_stored_graph_is_the_graph_that_was_built(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)

            graph = build.build_doc_graph(project)
            stored = json.loads(
                next(self._cache(project).glob("*.json")).read_text(encoding="utf-8")
            )

        self.assertEqual(graph, stored)

    def test_the_cache_does_not_grow_without_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)
            for generation in range(build.CACHE_GENERATIONS + 3):
                (project / "other.md").write_text(f"# {generation}\n", encoding="utf-8")
                build.clear_doc_graph_cache()
                build.build_doc_graph(project)

            kept = list(self._cache(project).glob("*.json"))

        self.assertEqual(build.CACHE_GENERATIONS, len(kept))

    def test_no_temporary_file_is_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(directory)

            build.build_doc_graph(project)

            self.assertEqual([], list(self._cache(project).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
