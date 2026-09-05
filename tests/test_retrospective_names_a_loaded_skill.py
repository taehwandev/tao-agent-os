from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_finish_gate_policy import validate_gate_evidence
from agent_skill_catalog import skill_ids_from_doc_paths

KNOWN = {
    "agent_task_lifecycle",
    "ambiguity_gate",
    "graphify",
    "retrospective_learning",
    "review_and_commit",
    "testing",
    "verification_policy",
}
ROUTE_DOCS = [
    "workflows/skills/agent-task-lifecycle/SKILL.md",
    "workflows/skills/agent-task-lifecycle/references/current-guidance.md",
    "workflows/skills/ambiguity-gate/SKILL.md",
]


def evidence(skills: str, outcome: str = "no_reusable_gap", observation: str = "not_needed") -> str:
    return (
        f"retrospective check; skills checked: {skills}; "
        f"outcome: {outcome}; observation: {observation}"
    )


def check(skills: str, loaded: set[str] | None, **kwargs) -> list[str]:
    return validate_retrospective_check(
        evidence(skills, **kwargs), allowed_skill_ids=KNOWN, loaded_skill_ids=loaded
    )


class SkillIdsFromDocPathsTests(unittest.TestCase):
    def test_a_bundle_owns_its_skill_doc_and_every_reference_below_it(self) -> None:
        self.assertEqual(
            {"agent_task_lifecycle", "ambiguity_gate"},
            skill_ids_from_doc_paths(ROUTE_DOCS),
        )

    def test_both_container_names_resolve_and_hyphens_normalize(self) -> None:
        self.assertEqual(
            {"code_conventions", "house_style"},
            skill_ids_from_doc_paths([
                "common/skills/code-conventions/SKILL.md",
                ".agents/shared/llm-skills/house-style/references/deep/note.md",
            ]),
        )

    def test_paths_outside_any_bundle_contribute_nothing(self) -> None:
        self.assertEqual(
            set(),
            skill_ids_from_doc_paths([
                "AGENTS.md", "index.md", "docs/routing/overview.md", "", "skills/SKILL.md",
            ]),
        )

    def test_the_first_container_wins_for_a_nested_repository_copy(self) -> None:
        # A bundle whose reference tree happens to contain the word "skills"
        # again must still resolve to the outer bundle it belongs to.
        self.assertEqual(
            {"outer"},
            skill_ids_from_doc_paths(["common/skills/outer/references/skills/inner.md"]),
        )

    def test_windows_separators_resolve_the_same_bundle(self) -> None:
        self.assertEqual(
            {"agent_task_lifecycle"},
            skill_ids_from_doc_paths([r"workflows\skills\agent-task-lifecycle\SKILL.md"]),
        )


class RetrospectiveNamesALoadedSkillTests(unittest.TestCase):
    def test_a_skill_this_run_never_loaded_is_refused_and_the_loaded_set_is_named(self) -> None:
        failures = check("graphify", {"agent_task_lifecycle", "ambiguity_gate"})
        self.assertEqual(1, len(failures))
        self.assertIn("must name at least one skill this run actually loaded", failures[0])
        self.assertIn("agent_task_lifecycle, ambiguity_gate", failures[0])

    def test_one_loaded_name_is_enough_so_a_wider_retrospective_is_not_punished(self) -> None:
        self.assertEqual([], check("graphify, testing, ambiguity_gate", {"ambiguity_gate"}))

    def test_the_gate_that_every_route_requires_may_always_name_its_own_skill(self) -> None:
        # All 27 routes require `retrospective check`, so the skill governing
        # how to record it is used by every run whether or not the route listed
        # its document.
        self.assertEqual([], check("retrospective_learning", {"ambiguity_gate"}))
        self.assertIn(
            "retrospective_learning",
            check("graphify", {"ambiguity_gate"})[0],
        )

    def test_a_route_with_no_skill_documents_cannot_judge_and_does_not_block(self) -> None:
        self.assertEqual([], check("graphify", set()))
        self.assertEqual([], check("graphify", None))

    def test_no_skill_used_stays_exempt(self) -> None:
        self.assertEqual(
            [], check("none", {"ambiguity_gate"}, outcome="no_skill_used")
        )

    def test_a_reusable_gap_is_held_to_the_same_rule(self) -> None:
        failures = check(
            "graphify", {"ambiguity_gate"},
            outcome="reusable_gap", observation="recorded",
        )
        self.assertTrue(any("actually loaded" in item for item in failures))

    def test_unparseable_slugs_report_one_mistake_not_two(self) -> None:
        failures = check("made up skill!", {"ambiguity_gate"})
        self.assertEqual(1, len(failures))
        self.assertIn("canonical skill slugs", failures[0])

    def test_an_unknown_but_wellformed_slug_reports_both_of_its_real_problems(self) -> None:
        failures = check("never_heard_of_it", {"ambiguity_gate"})
        self.assertTrue(any("unknown canonical skills" in item for item in failures))
        self.assertTrue(any("actually loaded" in item for item in failures))


class RoutePolicyIntegrationTests(unittest.TestCase):
    def test_the_policy_derives_the_loaded_set_from_the_route_required_docs(self) -> None:
        failures = validate_gate_evidence(
            {"retrospective check": evidence("graphify")},
            ["retrospective check"],
            route={"required_docs": ROUTE_DOCS},
            allowed_skill_ids=KNOWN,
        )
        self.assertTrue(any("actually loaded" in item for item in failures))
        self.assertEqual(
            [],
            validate_gate_evidence(
                {"retrospective check": evidence("ambiguity_gate")},
                ["retrospective check"],
                route={"required_docs": ROUTE_DOCS},
                allowed_skill_ids=KNOWN,
            ),
        )

    def test_a_missing_route_leaves_the_gate_exactly_as_it_was(self) -> None:
        self.assertEqual(
            [],
            validate_gate_evidence(
                {"retrospective check": evidence("graphify")},
                ["retrospective check"],
                route=None,
                allowed_skill_ids=KNOWN,
            ),
        )


if __name__ == "__main__":
    unittest.main()
