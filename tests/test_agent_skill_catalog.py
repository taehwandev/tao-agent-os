"""Repository-local retrospective names require an in-repository skill bundle."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_skill_catalog import canonical_skill_ids


class ProjectSkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.rules = self.base / "rules"
        self.project.mkdir()
        self.rules.mkdir()
        self.skill(self.rules / "common/skills/refactoring")

    def skill(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text("# Skill contract\n", encoding="utf-8")

    def errors(self, names, loaded=None):
        return validate_retrospective_check(
            f"skills checked: {names}; outcome: no_reusable_gap; observation: not_needed",
            allowed_skill_ids=canonical_skill_ids(self.project, self.rules),
            loaded_skill_ids=loaded or {"refactoring"},
        )

    def test_keyflow_names_are_preserved_alongside_loaded_canonical_skill(self):
        names = ["keyflow-code-stewardship", "keyflow-rich-editor-qa",
                 "keyflow-editor-publishing-qa"]
        for name in names:
            self.skill(self.project / ".agent/skills" / name)
        self.assertEqual([], self.errors(", ".join(["refactoring", *names])))

    def test_local_loaded_skill_can_be_the_only_evaluated_skill(self):
        self.skill(self.project / ".agent/skills/editor-qa")
        self.assertEqual([], self.errors("editor-qa", {"editor_qa"}))

    def test_other_standard_and_legacy_roots_remain_supported(self):
        for index, root in enumerate((".agents/skills", ".codex/skills",
                                      ".agents/shared/llm-skills", ".agents/local/skills")):
            self.skill(self.project / root / f"local-{index}")
        catalog = canonical_skill_ids(self.project, self.rules)
        self.assertTrue({f"local_{index}" for index in range(4)} <= catalog)

    def test_unknown_and_unloaded_checks_are_not_weakened(self):
        self.skill(self.project / ".agent/skills/editor-qa")
        self.assertTrue(any("unknown canonical" in error for error in self.errors("refactoring, fake")))
        self.assertTrue(any("actually loaded" in error for error in self.errors("editor-qa")))

    def test_non_skill_files_and_arbitrary_locations_do_not_register_names(self):
        self.skill(self.project / "docs/skills/arbitrary")
        directory = self.project / ".agent/skills/not-a-document/SKILL.md"
        directory.mkdir(parents=True)
        self.assertTrue(any("unknown canonical" in error for error in self.errors("refactoring, arbitrary")))
        self.assertNotIn("not_a_document", canonical_skill_ids(self.project, self.rules))
        self.assertTrue(self.errors("refactoring, ../escape"))

    def test_root_directory_and_document_symlink_escapes_are_rejected(self):
        external = self.base / "external"
        self.skill(external / "escaped-root")
        (self.project / ".codex").mkdir()
        (self.project / ".codex/skills").symlink_to(external, target_is_directory=True)
        root = self.project / ".agent/skills"
        root.mkdir(parents=True)
        (root / "escaped-directory").symlink_to(external / "escaped-root", target_is_directory=True)
        (root / "escaped-file").mkdir()
        (root / "escaped-file/SKILL.md").symlink_to(external / "escaped-root/SKILL.md")
        self.assertEqual({"refactoring"}, canonical_skill_ids(self.project, self.rules))


if __name__ == "__main__":
    unittest.main()
