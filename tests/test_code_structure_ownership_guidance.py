from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDANCE = (
    ROOT
    / "common"
    / "skills"
    / "code-structure-ownership"
    / "references"
    / "current-guidance.md"
)


class CodeStructureOwnershipGuidanceTests(unittest.TestCase):
    def test_subject_specific_tests_mirror_the_production_owner(self) -> None:
        guidance = GUIDANCE.read_text(encoding="utf-8")

        self.assertIn("### Test Subject Ownership", guidance)
        self.assertIn("`<Subject>Test`", guidance)
        self.assertIn("broad feature or category bucket", guidance)
        self.assertIn("mirrored test location", guidance)


if __name__ == "__main__":
    unittest.main()
