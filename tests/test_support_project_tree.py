"""What a repository-wide walk may enter, and what it must skip."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_skill_catalog
from agent_skill_catalog import canonical_skill_ids
from support.project_tree import (
    PRUNED_DIRECTORIES,
    PRUNED_RUN_STATE,
    iter_project_files,
)
import workflow_doc_graph_build
from workflow_doc_graph_build import _markdown_docs, clear_doc_graph_cache
from workflow_route import resolve_docs
from workflow_validate import MARKDOWN_VALIDATE_IGNORED_DIRS, markdown_files_to_validate


def build(base: Path, *relatives: str) -> None:
    for relative in relatives:
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# doc\n", encoding="utf-8")


class PrunedWalkTests(unittest.TestCase):
    def test_a_pruned_directory_is_not_entered_at_any_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(
                base,
                "guide.md",
                "nested/guide.md",
                ".tao/runs/abc/guide.md",
                "nested/.tao/guide.md",
                ".git/guide.md",
            )

            found = {
                path.relative_to(base).as_posix()
                for path in iter_project_files(base, "*.md")
            }

            self.assertEqual({"guide.md", "nested/guide.md"}, found)

    def test_a_path_entry_prunes_only_that_place(self) -> None:
        """`.tao` is not uniformly disposable; its skills are tracked content."""

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(
                base,
                ".tao/skills/graphify/SKILL.md",
                ".tao/runs/abc/integration/skills/other/SKILL.md",
                "runs/keep/SKILL.md",
            )

            found = {
                path.relative_to(base).as_posix()
                for path in iter_project_files(base, "SKILL.md", pruned=PRUNED_RUN_STATE)
            }

            self.assertEqual(
                {".tao/skills/graphify/SKILL.md", "runs/keep/SKILL.md"},
                found,
                "a bare `runs` directory elsewhere is not project state",
            )

    def test_a_symlinked_directory_is_not_followed(self) -> None:
        """Matching rglob: a link must not walk a caller out of its tree."""

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "project"
            outside = Path(directory) / "outside"
            build(base, "guide.md")
            build(outside, "elsewhere.md")
            (base / "link").symlink_to(outside, target_is_directory=True)

            found = {
                path.relative_to(base).as_posix()
                for path in iter_project_files(base, "*.md")
            }

            self.assertEqual({"guide.md"}, found)

    def test_a_directory_named_like_a_document_is_not_yielded(self) -> None:
        """The one deliberate difference from rglob, pinned so it stays one.

        `rglob("*.md")` also returns a directory whose name matches, so a
        directory called `notes.md` entered the document graph as a node whose
        contents could never be read. Callers here want documents.
        """

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(base, "notes.md/inside.md", "real.md")

            found = {
                path.relative_to(base).as_posix()
                for path in iter_project_files(base, "*.md")
            }

            self.assertEqual({"notes.md/inside.md", "real.md"}, found)
            self.assertIn(
                "notes.md",
                {path.relative_to(base).as_posix() for path in base.rglob("*.md")},
                "rglob returns the directory itself; this walk deliberately does not",
            )

    def test_an_unreadable_directory_is_skipped_by_both_walks(self) -> None:
        """Neither walk may turn a permission wall into a raised error."""

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(base, "open.md", "locked/hidden.md")
            locked = base / "locked"
            os.chmod(locked, 0o000)
            try:
                if os.access(locked, os.R_OK):
                    self.skipTest("this filesystem still reads a 0o000 directory")
                found = {
                    path.relative_to(base).as_posix()
                    for path in iter_project_files(base, "*.md")
                }
                rglobbed = {
                    path.relative_to(base).as_posix() for path in base.rglob("*.md")
                }
            finally:
                os.chmod(locked, 0o755)

        self.assertEqual({"open.md"}, found)
        self.assertEqual(rglobbed, found)

    def test_an_empty_name_yields_every_file_outside_the_pruned_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(base, "guide.md", "code.py", ".tao/runs/abc/state.json")

            found = {path.relative_to(base).as_posix() for path in iter_project_files(base)}

            self.assertEqual({"guide.md", "code.py"}, found)


def scanned_directories(walk) -> list[str]:
    """Record every directory a walk actually reads, through either layer.

    Results alone cannot tell pruning from filtering: a walk that enters the
    state directory and discards what it finds returns exactly the same files
    as one that never enters it, so the whole saving could be undone with
    every test still passing. `os.walk` reaches `os.scandir` at call time,
    while `pathlib` binds its own reference on older interpreters, so both are
    recorded and a reimplementation through either is visible.
    """

    visited: list[str] = []
    real = os.scandir

    def recorder(path="."):
        visited.append(str(path))
        return real(path)

    accessor = getattr(pathlib, "_NormalAccessor", None)
    patches = [patch("os.scandir", recorder)]
    if accessor is not None and hasattr(accessor, "scandir"):
        patches.append(patch.object(accessor, "scandir", staticmethod(recorder)))
    for item in patches:
        item.start()
    try:
        walk()
    finally:
        for item in patches:
            item.stop()
    return visited


class PrunedTraversalTests(unittest.TestCase):
    """The saving is in what is never entered, so that is what is pinned."""

    def _tree(self, base: Path) -> None:
        build(
            base,
            "guide.md",
            ".tao/runs/one/copy.md",
            ".tao/runs/one/deeper/copy.md",
            ".tao/runs/two/copy.md",
        )

    def test_a_pruned_directory_is_never_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._tree(base)

            visited = scanned_directories(
                lambda: list(iter_project_files(base, "*.md"))
            )

            self.assertEqual(
                [], [path for path in visited if ".tao" in path], visited
            )

    def test_the_recorder_does_see_a_walk_that_enters_it(self) -> None:
        """A control: without it, an instrument that sees nothing proves nothing."""

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._tree(base)

            visited = scanned_directories(lambda: list(base.rglob("*.md")))

            self.assertTrue([path for path in visited if ".tao" in path])

    def test_no_caller_walks_the_state_it_excludes(self) -> None:
        """Pinned per caller, because each one can regress on its own.

        Reverting a single caller to walk-then-filter returns exactly the
        files it returned before, so only what it entered can tell.
        """

        callers = (
            ("document graph", _markdown_docs, ".tao"),
            ("markdown validator", markdown_files_to_validate, ".tao"),
            ("skill catalogue", agent_skill_catalog._skill_ids_under, ".tao/runs"),
        )
        for name, caller, excluded in callers:
            with self.subTest(caller=name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                self._tree(base)
                build(base, ".tao/skills/graphify/SKILL.md", "skills/local/SKILL.md")

                visited = scanned_directories(lambda: caller(base))

                entered = [
                    path
                    for path in visited
                    if f"/{excluded}/" in path or path.endswith(f"/{excluded}")
                ]
                self.assertEqual([], entered, f"{name} entered {excluded}: {entered}")

    def test_the_skill_catalogue_still_enters_the_state_it_needs(self) -> None:
        """Its exclusion is narrower, and a wider one would lose a real skill."""

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build(base, ".tao/skills/graphify/SKILL.md", ".tao/runs/one/copy/SKILL.md")

            visited = scanned_directories(
                lambda: agent_skill_catalog._skill_ids_under(base)
            )

            self.assertTrue([path for path in visited if "/.tao/skills" in path])


class DocumentGraphCostTests(unittest.TestCase):
    """One graph per process, however many route contracts ask for it.

    `resolve_docs` runs once per route contract -- twenty-six of them in
    workflow validation -- and each asks the graph to expand its matches. The
    build walks and reads every guidance document, so losing the cache would
    multiply the review hook's cost by the number of routes without changing
    any answer.
    """

    @staticmethod
    def _clear_cache() -> None:
        """Clear it if there is a cache, so the count is what fails without one."""

        try:
            clear_doc_graph_cache()
        except AttributeError:
            pass

    def test_the_graph_is_built_once_for_many_route_contracts(self) -> None:
        self._clear_cache()
        self.addCleanup(self._clear_cache)
        builds: list[int] = []
        real = workflow_doc_graph_build._markdown_docs

        def counted(root):
            builds.append(1)
            return real(root)

        with patch.object(workflow_doc_graph_build, "_markdown_docs", counted):
            for command in ("task", "bugfix", "review", "ship"):
                resolve_docs(command, None, [], ())

        self.assertEqual(1, len(builds))


class CallerResultsAreUnchangedTests(unittest.TestCase):
    """Pruning is only a saving while it is also the same answer.

    Each caller previously discarded these directories after walking them, so
    the check is against this repository, where the state directory holds one
    directory per recorded run and a second copy of the tree.
    """

    def test_the_document_graph_keeps_exactly_the_documents_it_kept(self) -> None:
        expected = {
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.md")
            if not (
                path.relative_to(ROOT).as_posix().startswith(".tao/")
                or "/.tao/" in path.relative_to(ROOT).as_posix()
            )
        }

        self.assertEqual(expected, _markdown_docs(ROOT))

    def test_the_validator_keeps_exactly_the_files_it_kept(self) -> None:
        expected = sorted(
            path
            for path in ROOT.rglob("*.md")
            if not MARKDOWN_VALIDATE_IGNORED_DIRS.intersection(
                path.relative_to(ROOT).parts
            )
        )

        self.assertEqual(expected, markdown_files_to_validate(ROOT))

    def test_the_skill_catalogue_keeps_the_skills_stored_under_project_state(self) -> None:
        """Pruning all of `.tao` would have dropped a tracked skill id."""

        self.assertIn("graphify", canonical_skill_ids(ROOT, ROOT))
        self.assertIn(".tao", PRUNED_DIRECTORIES)
        self.assertNotIn(".tao", PRUNED_RUN_STATE)


if __name__ == "__main__":
    unittest.main()
