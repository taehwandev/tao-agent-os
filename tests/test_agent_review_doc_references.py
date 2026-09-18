from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_doc_references import doc_reference_failures
from agent_review_hook import documentation_reference_failures
from agent_review_structure import changed_source_paths

FRONTMATTER = "---\nkeyflow_id: sys_x\nstatus: stable\ntype: human-reviewed-needed\n---\n\n"


class DocReferenceCheckTests(unittest.TestCase):
    """The check the `link/path check` gate used to take on trust."""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / "common" / "skills" / "a").mkdir(parents=True)
        (self.project / "workflows" / "skills").mkdir(parents=True)

    def write(self, relative: str, body: str, *, frontmatter: bool = True) -> str:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((FRONTMATTER if frontmatter else "") + body, encoding="utf-8")
        return relative

    def test_a_resolving_document_passes(self) -> None:
        self.write("common/skills/a/SKILL.md", "# A\n")
        changed = self.write(
            "workflows/skills/b.md",
            "See `common/skills/a/SKILL.md` and [A](../../common/skills/a/SKILL.md).\n",
        )

        self.assertEqual([], doc_reference_failures(self.project, [changed], []))

    def test_a_backtick_path_that_resolves_nowhere_fails(self) -> None:
        changed = self.write("workflows/skills/b.md", "See `common/skills/gone/SKILL.md`.\n")

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertEqual(1, len(failures))
        self.assertIn("common/skills/gone/SKILL.md", failures[0])

    def test_a_broken_relative_markdown_link_fails(self) -> None:
        changed = self.write("workflows/skills/b.md", "[A](../../common/skills/gone.md)\n")

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertEqual(1, len(failures))
        self.assertIn("gone.md", failures[0])

    def test_a_vendored_skill_is_not_held_to_this_repositorys_paths(self) -> None:
        """Its example paths name the repository the skill is pointed at."""
        changed = self.write(
            ".tao/skills/graphify/references/extraction-spec.md",
            "A node id looks like `docs/v1/api/README.md`.\n",
            frontmatter=False,
        )

        self.assertEqual([], doc_reference_failures(self.project, [changed], []))

    def test_a_vendored_skill_still_has_its_own_links_checked(self) -> None:
        """Exempting its foreign example paths exempted its real links too."""
        changed = self.write(
            ".tao/skills/vendor/guide.md", "[gone](missing.md)\n", frontmatter=False
        )

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertTrue(any("missing.md" in failure for failure in failures))

    def test_a_mention_is_not_a_reference(self) -> None:
        """Only repository-rooted paths are references; `...` is a pattern.

        Measured on the real tree before these rules were chosen: every
        backtick path that resolved nowhere was one of these two shapes.
        """
        changed = self.write(
            "workflows/skills/b.md",
            "Each card has a `SKILL.md`; a target repo may hold `README.md`.\n"
            "Entrypoints such as `common/skills/.../SKILL.md` are patterns.\n",
        )

        self.assertEqual([], doc_reference_failures(self.project, [changed], []))

    def test_missing_frontmatter_fails(self) -> None:
        changed = self.write("workflows/skills/b.md", "# B\n", frontmatter=False)

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertEqual(1, len(failures))
        self.assertIn("no frontmatter block", failures[0])

    def test_an_incomplete_frontmatter_names_the_absent_keys(self) -> None:
        path = self.project / "workflows" / "skills" / "b.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nkeyflow_id: sys_x\n---\n\n# B\n", encoding="utf-8")

        failures = doc_reference_failures(self.project, ["workflows/skills/b.md"], [])

        self.assertEqual(1, len(failures))
        self.assertIn("status", failures[0])
        self.assertIn("type", failures[0])

    def test_a_removed_document_that_others_still_reference_fails(self) -> None:
        """The rule the changed file cannot show: the evidence is elsewhere."""
        self.write("workflows/skills/keeper.md", "Follow `common/skills/a/moved.md`.\n")

        failures = doc_reference_failures(
            self.project, [], ["common/skills/a/moved.md"]
        )

        self.assertEqual(1, len(failures))
        self.assertIn("keeper.md still references", failures[0])

    def test_a_relative_link_to_a_removed_document_fails(self) -> None:
        """A sibling link shares no substring with the repository-relative path.

        `../alpha/old.md` and `common/skills/alpha/old.md` have no substring in
        common, so matching the repository-relative string alone missed the
        reference; resolving the link from the referring file finds it. Written
        with a sibling link rather than `../../common/...`, which happens to
        contain the target string and would have passed either way -- the first
        version of this test proved nothing for that reason.
        """
        keeper = self.write(
            "common/skills/beta/keeper.md", "See [old](../alpha/old.md).\n"
        )
        target = "common/skills/alpha/old.md"
        self.assertNotIn(target, (self.project / keeper).read_text(encoding="utf-8"))

        failures = doc_reference_failures(self.project, [], [target])

        self.assertEqual(1, len(failures))
        self.assertIn("keeper.md still references", failures[0])

    def test_a_top_level_document_is_scanned(self) -> None:
        """A reference from README.md breaks exactly like one from a skill card."""
        self.write("README.md", "Start at `common/a/old.md`.\n")

        failures = doc_reference_failures(self.project, [], ["common/a/old.md"])

        self.assertEqual(1, len(failures))
        self.assertIn("README.md still references", failures[0])

    def test_a_link_carrying_a_title_is_still_parsed(self) -> None:
        """`[doc](missing.md "title")` is valid Markdown, and was ignored."""
        changed = self.write(
            "workflows/skills/b.md", '[doc](../../common/skills/gone.md "Title")\n'
        )

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertEqual(1, len(failures))
        self.assertIn("gone.md", failures[0])

    def test_an_empty_frontmatter_value_fails(self) -> None:
        """Presence of the key told the reader nothing; the value has to be there."""
        path = self.project / "workflows" / "skills" / "b.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nkeyflow_id: sys_x\nstatus:\ntype: \n---\n\n# B\n", encoding="utf-8"
        )

        failures = doc_reference_failures(self.project, ["workflows/skills/b.md"], [])

        self.assertEqual(1, len(failures))
        self.assertIn("status", failures[0])
        self.assertIn("type", failures[0])

    def test_an_unreadable_document_fails_rather_than_passing(self) -> None:
        """An automatic check that skips what it cannot read reports a false pass."""
        changed = self.write("workflows/skills/b.md", "# B\n")
        (self.project / changed).chmod(0o000)
        self.addCleanup((self.project / changed).chmod, 0o600)

        failures = doc_reference_failures(self.project, [changed], [])

        self.assertTrue(failures)
        self.assertTrue(any("could not be read" in failure for failure in failures))

    def test_removing_a_document_nobody_references_passes(self) -> None:
        self.write("workflows/skills/keeper.md", "Unrelated.\n")

        self.assertEqual(
            [], doc_reference_failures(self.project, [], ["common/skills/a/moved.md"])
        )


def _tracked(*paths: str):
    """Stand in for the hook's tracked Markdown discovery command."""

    def run(command, project):  # noqa: ANN001 - mirrors CommandRunner
        return {"returncode": 0, "stdout": "\0".join(paths)}

    return run


class HookPassesTheRightPathsTests(unittest.TestCase):
    """The adapter between the diff and the checker, which the rules never see.

    Both defects here were invisible to the rule tests: the rules were correct
    and were handed the wrong input.
    """

    def test_a_renamed_document_is_reported_as_removed(self) -> None:
        """Git reports a move as R with previous_path, not as D.

        Reading `D` alone meant the most common way a document moves -- renaming
        it -- left every reference to the old name unchecked.
        """
        structure = {
            "discovery": {
                "path_metadata": {
                    "common/skills/a/new.md": {
                        "status": "R",
                        "previous_path": "common/skills/a/old.md",
                    }
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "common" / "skills" / "a").mkdir(parents=True)
            (project / "common" / "skills" / "a" / "new.md").write_text(
                FRONTMATTER + "# New\n", encoding="utf-8"
            )
            (project / "keeper.md").write_text(
                FRONTMATTER + "See `common/skills/a/old.md`.\n", encoding="utf-8"
            )

            failures = documentation_reference_failures(
                project, structure, _tracked("keeper.md")
            )

        self.assertTrue(failures)
        self.assertTrue(
            any("still references common/skills/a/old.md" in f for f in failures)
        )

    def test_a_plain_deletion_is_still_reported(self) -> None:
        structure = {
            "discovery": {"path_metadata": {"common/skills/a/old.md": {"status": "D"}}}
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "common").mkdir()
            (project / "keeper.md").write_text(
                FRONTMATTER + "See `common/skills/a/old.md`.\n", encoding="utf-8"
            )

            failures = documentation_reference_failures(
                project, structure, _tracked("keeper.md")
            )

        self.assertTrue(failures)

    def test_the_checker_reads_the_project_it_is_given(self) -> None:
        """A commit-range review reads a snapshot, not the working tree.

        The hook builds that snapshot and must hand it to this check; passing
        the live checkout would pass or fail on documents the review is not
        about. This pins that the project argument is what is read.
        """
        structure = {
            "discovery": {
                "path_metadata": {"workflows/skills/b.md": {"status": "M"}}
            }
        }

        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot = Path(snapshot_dir)
            (snapshot / "workflows" / "skills").mkdir(parents=True)
            (snapshot / "workflows" / "skills" / "b.md").write_text(
                FRONTMATTER + "See `common/skills/gone/SKILL.md`.\n", encoding="utf-8"
            )

            failures = documentation_reference_failures(
                snapshot, structure, _tracked()
            )

        self.assertTrue(failures)
        self.assertTrue(any("gone/SKILL.md" in failure for failure in failures))

    def test_generated_output_is_not_searched_for_references(self) -> None:
        """A reference inside a regenerated artifact is not a break to fix.

        Widening the scan to reach a top-level README also reached
        `.agents/local/graphify-out/` and `graphify-out/`, which are gitignored
        and rebuilt. Failing review on one would be a check that starts red.
        """
        structure = {
            "discovery": {"path_metadata": {"common/a/old.md": {"status": "D"}}}
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "graphify-out").mkdir(parents=True)
            (project / "graphify-out" / "GRAPH_REPORT.md").write_text(
                FRONTMATTER + "See `common/a/old.md`.\n", encoding="utf-8"
            )
            (project / "keeper.md").write_text(
                FRONTMATTER + "Unrelated.\n", encoding="utf-8"
            )

            failures = documentation_reference_failures(
                project, structure, _tracked("keeper.md")
            )

        self.assertEqual([], failures)

    def test_external_repository_does_not_require_tao_frontmatter(self) -> None:
        structure = {
            "discovery": {"path_metadata": {"README.md": {"status": "M"}}}
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")

            failures = documentation_reference_failures(
                project, structure, _tracked("README.md")
            )

        self.assertEqual([], failures)

    def test_external_repository_still_checks_broken_links(self) -> None:
        structure = {
            "discovery": {"path_metadata": {"README.md": {"status": "M"}}}
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "README.md").write_text("[missing](missing.md)\n", encoding="utf-8")

            failures = documentation_reference_failures(
                project, structure, _tracked("README.md")
            )

        self.assertTrue(any("missing.md" in failure for failure in failures))

    def test_tao_repository_keeps_its_frontmatter_contract(self) -> None:
        structure = {
            "discovery": {"path_metadata": {"README.md": {"status": "M"}}}
        }

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for marker in (
                "index.md",
                "scripts/workflow.py",
                "common/skills/agent-operating-skill/SKILL.md",
            ):
                path = project / marker
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("marker\n", encoding="utf-8")
            (project / "README.md").write_text("# Tao\n", encoding="utf-8")

            failures = documentation_reference_failures(
                project, structure, _tracked("README.md")
            )

        self.assertTrue(any("frontmatter" in failure for failure in failures))


class RealRepositoryTests(unittest.TestCase):
    """Drive the adapter through git, not through a constructed metadata dict.

    The stubbed deletion test in this file passed while the check was blind to
    deletions because it supplied deleted metadata by hand. These tests build a
    real repository so the shared discovery must produce that metadata itself.
    """

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.project), *args],
            capture_output=True, text=True, check=False,
        )

    def run_command(self, command, project):  # noqa: ANN001 - mirrors CommandRunner
        result = subprocess.run(
            command, cwd=str(project), capture_output=True, text=True, check=False
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def write(self, relative: str, body: str) -> None:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FRONTMATTER + body, encoding="utf-8")

    def commit_initial(self) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", "initial")

    def check(self) -> list[str]:
        discovery, _checked = changed_source_paths(self.project, self.run_command)
        return documentation_reference_failures(
            self.project, {"discovery": discovery}, self.run_command
        )

    def test_deleting_a_tracked_document_is_discovered_from_git(self) -> None:
        self.write("common/a/old.md", "# Old\n")
        self.write("keeper.md", "See `common/a/old.md`.\n")
        self.commit_initial()
        self.git("rm", "-q", "common/a/old.md")

        failures = self.check()

        self.assertTrue(failures)
        self.assertTrue(any("keeper.md still references" in f for f in failures))

    def test_deleting_a_document_nobody_references_passes(self) -> None:
        self.write("common/a/old.md", "# Old\n")
        self.write("keeper.md", "Unrelated.\n")
        self.commit_initial()
        self.git("rm", "-q", "common/a/old.md")

        self.assertEqual([], self.check())

    def test_a_renamed_document_is_discovered_from_git(self) -> None:
        self.write("common/a/old.md", "# Old\n")
        self.write("keeper.md", "See `common/a/old.md`.\n")
        self.commit_initial()
        self.git("mv", "common/a/old.md", "common/a/new.md")

        failures = self.check()

        self.assertTrue(failures)
        self.assertTrue(any("keeper.md still references" in f for f in failures))

    def test_an_ignored_artifact_is_not_searched(self) -> None:
        """A regenerated report holding a stale path is not a break to fix."""
        self.write("common/a/old.md", "# Old\n")
        self.write("keeper.md", "Unrelated.\n")
        (self.project / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
        self.write("graphify-out/GRAPH_REPORT.md", "See `common/a/old.md`.\n")
        self.commit_initial()
        self.git("rm", "-q", "common/a/old.md")

        self.assertEqual([], self.check())


if __name__ == "__main__":
    unittest.main()
