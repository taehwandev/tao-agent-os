"""Test-subject ownership guidance, wherever in the bundle it now lives.

The rule moved from `current-guidance.md` into `references/unit-size.md` when
that reference was split. Pinning one file made this fail on a move that changed
no text, so it now asks the bundle rather than a path -- and a second assertion
keeps it from passing if the rule is duplicated into two pieces.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = (
    ROOT / "common" / "skills" / "code-structure-ownership" / "references"
)
ANCHORS = (
    "### Test Subject Ownership",
    "`<Subject>Test`",
    "broad feature or category bucket",
    "mirrored test location",
)


class CodeStructureOwnershipGuidanceTests(unittest.TestCase):
    def _pieces(self) -> dict[str, str]:
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(REFERENCES.glob("*.md"))
        }

    def test_subject_specific_tests_mirror_the_production_owner(self) -> None:
        bundle = "\n".join(self._pieces().values())

        for anchor in ANCHORS:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, bundle)

    def test_the_rule_lives_in_exactly_one_piece(self) -> None:
        # Two copies drift, and the one nobody edits is the one a route loads.
        homes = [
            name
            for name, text in self._pieces().items()
            if "### Test Subject Ownership" in text
        ]

        self.assertEqual(1, len(homes), homes)


if __name__ == "__main__":
    unittest.main()
