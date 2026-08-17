from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_doc_surfaces import infer_surface_docs
from workflow_gate_policy import CODE_WORK_COMMANDS
from workflow_route import resolve_docs


_PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "work_surface_preflight_under_test", ROOT / "scripts" / "agent-preflight.py"
)
assert _PREFLIGHT_SPEC and _PREFLIGHT_SPEC.loader
agent_preflight = importlib.util.module_from_spec(_PREFLIGHT_SPEC)
_PREFLIGHT_SPEC.loader.exec_module(agent_preflight)


class WorkSurfaceResolutionRoutingTests(unittest.TestCase):
    def test_code_route_requires_resolution_before_source_docs(self) -> None:
        for command in CODE_WORK_COMMANDS:
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertLess(
                    route["gates"].index("work surface resolution"),
                    route["gates"].index("source docs"),
                )

    def test_phrase_only_framework_is_not_a_policy_match(self) -> None:
        for platform, request in (
            ("android", "Compose를 사용해줘"),
            ("application", "React renderer를 사용해줘"),
            ("flutter", "Flutter Widget을 사용해줘"),
            ("ios", "SwiftUI를 사용해줘"),
            ("kmp", "Compose Multiplatform을 사용해줘"),
            ("web", "React TSX를 사용해줘"),
            (None, "React Native Expo로 만들어줘"),
            (None, "Python FastAPI endpoint를 만들어줘"),
        ):
            with self.subTest(platform=platform):
                _, matches = infer_surface_docs(
                    command="feature", platform=platform, request_text=request
                )
                self.assertFalse(
                    any(str(match["name"]).endswith("_self_selected") for match in matches)
                )

    def test_request_path_is_a_candidate_until_explicitly_verified(self) -> None:
        _, candidate_matches = infer_surface_docs(
            command="task",
            request_text="`scripts/workflow_route.py` 수정해줘",
        )
        _, verified_matches = infer_surface_docs(
            command="task",
            surface_paths=["scripts/workflow_route.py"],
        )

        self.assertFalse(any(match["type"] == "path_surface" for match in candidate_matches))
        self.assertTrue(any(match["name"] == "workflow_router" for match in verified_matches))

    def test_dirty_paths_are_recorded_as_candidates_not_promoted_surfaces(self) -> None:
        args = SimpleNamespace(
            project=ROOT,
            rules=ROOT,
            command="feature",
            request="Implement the scoped routing change",
            continuation_scope="",
            request_classified=False,
            classification_evidence="",
            intent_envelope="",
            approval_record="",
            runtime_session_id="surface-test",
            concern=[],
            platform=[],
            surface_path=[],
            parent_evidence=None,
        )
        captured: dict[str, object] = {}

        def fake_resolve_docs(*_args: object, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"missing": [], "blocking": [], "notes": []}

        with (
            patch.object(
                agent_preflight,
                "route_intake_decision",
                return_value=({"clarity": "clear-scoped"}, []),
            ),
            patch.object(agent_preflight, "resolve_docs", side_effect=fake_resolve_docs),
        ):
            route, error, status = agent_preflight.route_payload(
                args,
                {"stdout": " M scripts/workflow.py\n?? tests/test_new_surface.py\n"},
            )

        self.assertEqual("", error)
        self.assertEqual(0, status)
        self.assertEqual([], captured["surface_paths"])
        self.assertEqual(
            {
                "request_paths": [],
                "dirty_paths": ["scripts/workflow.py", "tests/test_new_surface.py"],
            },
            route["surface_candidates"],
        )

    def test_unrelated_workflow_entrypoint_does_not_request_graphify(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["scripts/workflow.py"],
        )

        self.assertNotIn("graphify readiness", route["gates"])
        self.assertFalse(
            any(match["name"] == "graphify_integration" for match in route["doc_surface_matches"])
        )

    def test_verified_graphify_owner_still_requests_readiness(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["scripts/workflow_graphify_route.py"],
        )

        self.assertIn("graphify readiness", route["gates"])
        self.assertTrue(
            any(match["name"] == "graphify_integration" for match in route["doc_surface_matches"])
        )

    def test_clearing_run_state_routes_to_the_retention_rule(self) -> None:
        """The rule exists to be read before the deletion, not after it.

        Run directories are named by whatever the caller passed, so deciding by
        name deletes other sessions' open runs. That is only avoidable by
        someone who read the retention rule first, which means the request has
        to reach it.
        """

        for request in (
            ".tao 정리해줘",
            "clean up the run store",
            "delete the continuation packets that cannot be resumed",
            "런 상태 정리해줘",
        ):
            with self.subTest(request=request):
                docs, _ = infer_surface_docs(command="task", request_text=request)
                self.assertIn(
                    "workflows/skills/session-continuation-protocol/SKILL.md", docs
                )

    def test_branch_cleanup_is_not_swallowed_by_the_run_state_intent(self) -> None:
        """Two destructive cleanups, two different sets of gates."""

        docs, _ = infer_surface_docs(command="task", request_text="브랜치 정리해줘")

        self.assertIn("common/skills/branch-cleanup/SKILL.md", docs)
        self.assertNotIn(
            "workflows/skills/session-continuation-protocol/SKILL.md", docs
        )


if __name__ == "__main__":
    unittest.main()
