from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


from workflow_common import SCOPE_CHANGE_LIFECYCLE_COMMANDS
from workflow_doc_resolution import doc_size
from workflow_route import resolve_docs


class ScopeChangeLifecycleTests(unittest.TestCase):
    def test_normal_code_routes_keep_final_checks_and_short_retrospective(self) -> None:
        for command in sorted(SCOPE_CHANGE_LIFECYCLE_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                expected = (["tests"] if command == "test" else ["tests", "review hook"])
                expected.append("retrospective check")
                self.assertEqual(expected, route["gates"])
                self.assertEqual(
                    ["start", "review", "finish"],
                    [hook["hook"] for hook in route["hooks"]
                     if hook["hook"] in {"start", "review", "finish"}],
                )
                self.assertTrue(route["skill_feedback"]["enabled"])
                self.assertFalse(next(h for h in route["hooks"]
                                      if h["hook"] == "skill-feedback")["required"])

    def test_scope_change_policy_records_only_material_expansion(self) -> None:
        route = resolve_docs("task", None, [], request_classified=True)

        self.assertEqual(
            {
                "mode": "on_material_change",
                "baseline": "start_intake",
                "unchanged": "no_intermediate_gate_or_checkpoint",
                "trigger": [
                    "owner",
                    "repository",
                    "effect_ceiling",
                    "acceptance_behavior",
                    "external_target",
                ],
                "action": (
                    "record_one_semantic_checkpoint; start_a_new_route_only_when_"
                    "project_authority_effect_or_external_target_changes"
                ),
            },
            route["scope_change_policy"],
        )

    def test_normal_code_routes_use_compact_initial_reading(self) -> None:
        total_bytes = 0
        for command in sorted(SCOPE_CHANGE_LIFECYCLE_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                required = route["required_docs"]

                self.assertIn(
                    "common/skills/testing/references/final-check.md", required
                )
                self.assertNotIn(
                    "common/skills/testing/references/current-guidance.md",
                    required,
                )
                self.assertNotIn(
                    "common/skills/code-review/references/current-guidance.md",
                    required,
                )
                if command == "test":
                    self.assertNotIn(
                        "workflows/skills/review-and-commit/SKILL.md", required
                    )
                else:
                    self.assertIn(
                        "workflows/skills/review-and-commit/SKILL.md", required
                    )
                total_bytes += sum(doc_size(ROOT, doc) for doc in required)

        self.assertLess(total_bytes, 100_000)

    def test_explicit_testing_concern_still_promotes_detailed_guidance(self) -> None:
        route = resolve_docs(
            "feature", None, ["testing"], request_classified=True
        )

        self.assertIn(
            "common/skills/testing/references/current-guidance.md",
            route["required_docs"],
        )

    def test_platform_and_request_surfaces_keep_the_compact_budget(self) -> None:
        cases = (
            ("버튼 위치를 8dp 아래로 옮겨줘", 25_000),
            ("새 Compose 화면을 추가해줘", 50_000),
        )

        for request_text, byte_limit in cases:
            with self.subTest(request_text=request_text):
                route = resolve_docs(
                    "feature",
                    "android",
                    [],
                    request_classified=True,
                    request_text=request_text,
                )

                self.assertLessEqual(len(route["required_docs"]), 8)
                self.assertLess(
                    sum(doc_size(ROOT, doc) for doc in route["required_docs"]),
                    byte_limit,
                )

    def test_platform_default_keeps_detailed_cards_as_references(self) -> None:
        route = resolve_docs(
            "feature",
            "android",
            [],
            request_classified=True,
        )

        self.assertIn(
            "platforms/android/skills/android-architecture/references/current-guidance.md",
            route["required_docs"],
        )
        self.assertNotIn(
            "platforms/android/skills/android-viewmodel-state/references/current-guidance.md",
            route["required_docs"],
        )
        self.assertIn(
            "platforms/android/skills/android-viewmodel-state/SKILL.md",
            route["reference_docs"],
        )

    def test_compose_feature_keeps_optional_ecosystem_detail_as_reference(self) -> None:
        route = resolve_docs(
            "feature",
            "android",
            [],
            request_classified=True,
            request_text="새 Compose 화면을 추가해줘",
        )

        self.assertIn(
            "platforms/android/skills/android-compose-ui/references/current-guidance.md",
            route["required_docs"],
        )
        self.assertNotIn(
            "platforms/android/skills/source-coverage/references/compose-performance-source-map.md",
            route["required_docs"],
        )
        self.assertIn(
            "platforms/android/skills/source-coverage/references/compose-performance-source-map.md",
            route["reference_docs"],
        )

    def test_final_check_is_reported_as_a_gate_contract(self) -> None:
        route = resolve_docs("feature", None, [], request_classified=True)
        reasons = {
            item["doc"]: item["reason"]
            for item in route["required_doc_reasons"]
        }

        self.assertEqual(
            "gate_contract",
            reasons["common/skills/testing/references/final-check.md"],
        )

    def test_specialized_routes_keep_their_existing_gate_models(self) -> None:
        for command in ("product", "commit", "release", "cleanup", "multi-agent"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertNotIn("scope_change_policy", route)
                self.assertNotEqual(["tests", "review hook"], route["gates"])


if __name__ == "__main__":
    unittest.main()
