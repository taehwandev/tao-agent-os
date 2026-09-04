from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDANCE = ROOT / "common/skills/branch-cleanup/references/current-guidance.md"


class BranchCleanupGuidanceTests(unittest.TestCase):
    def test_merged_pr_fast_path_avoids_redundant_content_checks(self) -> None:
        text = GUIDANCE.read_text(encoding="utf-8")
        collapsed = " ".join(text.split())

        self.assertIn("query the forge once for all candidates", text)
        self.assertIn("recorded head SHA equals the fetched remote branch tip", collapsed)
        self.assertIn("without an ancestry check, `git cherry`, content diff", collapsed)
        self.assertIn("batch the approved deletes into one push", text)
        self.assertIn("--force-with-lease=refs/heads/<branch>:<sha>", text)

    def test_unmerged_or_moved_pr_tip_is_preserved_without_heuristics(self) -> None:
        text = GUIDANCE.read_text(encoding="utf-8")
        collapsed = " ".join(text.split())

        self.assertIn("closed without merge", text)
        self.assertIn("head SHA no longer matches", collapsed)
        self.assertIn("Preserve it and stop", text)
        self.assertIn("do not run content-equivalence heuristics", text)


if __name__ == "__main__":
    unittest.main()
