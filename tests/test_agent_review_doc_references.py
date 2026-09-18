from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_doc_references import doc_reference_failures

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

    def test_removing_a_document_nobody_references_passes(self) -> None:
        self.write("workflows/skills/keeper.md", "Unrelated.\n")

        self.assertEqual(
            [], doc_reference_failures(self.project, [], ["common/skills/a/moved.md"])
        )


if __name__ == "__main__":
    unittest.main()
