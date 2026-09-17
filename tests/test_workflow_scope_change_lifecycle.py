from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


from workflow_common import SCOPE_CHANGE_LIFECYCLE_COMMANDS
from workflow_route import resolve_docs


class ScopeChangeLifecycleTests(unittest.TestCase):
    def test_normal_code_routes_have_only_final_tests_and_review(self) -> None:
        for command in sorted(SCOPE_CHANGE_LIFECYCLE_COMMANDS):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                expected = ["tests"] if command == "test" else ["tests", "review hook"]
                self.assertEqual(expected, route["gates"])
                self.assertEqual(
                    ["start", "review", "finish"],
                    [hook["hook"] for hook in route["hooks"]],
                )
                self.assertFalse(route["skill_feedback"]["enabled"])

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

    def test_specialized_routes_keep_their_existing_gate_models(self) -> None:
        for command in ("product", "commit", "release", "cleanup", "multi-agent"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)

                self.assertNotIn("scope_change_policy", route)
                self.assertNotEqual(["tests", "review hook"], route["gates"])


if __name__ == "__main__":
    unittest.main()
