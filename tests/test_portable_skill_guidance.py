from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def guidance(path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    return " ".join(text.split())


class PortableSkillGuidanceTests(unittest.TestCase):
    def test_bulk_change_recovery_preserves_user_changes(self) -> None:
        text = guidance(
            "common/skills/bulk-change-verification/references/current-guidance.md"
        )

        self.assertNotIn("git checkout HEAD -- <file>", text)
        self.assertIn("targeted reverse patch", text)
        self.assertIn("pre-existing user changes", text)

    def test_alias_import_rule_is_kotlin_scoped(self) -> None:
        text = guidance("common/skills/code-conventions/references/current-guidance.md")

        self.assertIn("In Kotlin source", text)
        self.assertIn("Kotlin's renaming import", text)
        self.assertIn("Languages without import aliases", text)
        self.assertIn("Java may", text)

    def test_android_edge_to_edge_keeps_app_owned_exceptions(self) -> None:
        text = guidance(
            "platforms/android/skills/android-compose-ui/references/"
            "edge-to-edge-insets.md"
        )

        self.assertNotIn("deprecated no-ops", text)
        self.assertIn("Android application-window guidance", text)
        self.assertIn("isAppearanceLightStatusBars", text)
        self.assertIn("isNavigationBarContrastEnforced", text)
        self.assertIn("three-button navigation", text)

    def test_wiki_guidance_separates_local_config_from_shared_protocol(self) -> None:
        text = guidance(
            "common/skills/llm-wiki-documentation/references/current-guidance.md"
        )

        self.assertIn("Per-user runtime configuration", text)
        self.assertIn("Provider-neutral, team-shared runtime protocols", text)
        self.assertIn("evidence schema semantics", text)

    def test_read_only_reviewer_can_run_bounded_diagnostics(self) -> None:
        text = guidance(
            "workflows/skills/multi-perspective-review/references/"
            "current-guidance.md"
        )

        self.assertIn("bounded non-mutating diagnostics", text)
        self.assertIn("git diff", text)
        self.assertIn("side effects are unknown", text)
        self.assertNotIn("author patches; run commands; run formatters", text)

    def test_commit_review_binds_the_final_staged_state(self) -> None:
        text = guidance(
            "common/skills/commit-workflow/references/current-guidance.md"
        )

        self.assertIn("stage the exact commit unit", text)
        self.assertIn("final staged state", text)
        self.assertIn("any later stage, unstage, or restage invalidates", text)
        self.assertNotIn("Run the lightweight code review first", text)


if __name__ == "__main__":
    unittest.main()
