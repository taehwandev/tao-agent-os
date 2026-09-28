from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_graphify_route import graphify_is_work_target, graphify_route_context
from workflow_route import resolve_docs


class GraphifyRouteContextTests(unittest.TestCase):
    def test_unrelated_route_has_no_readiness_side_effect(self) -> None:
        with patch("workflow_graphify_route.inspect_target_graphify") as inspect:
            context = graphify_route_context(
                concerns=[],
                surface_matches=[{"name": "workflow_router"}],
                project_root=ROOT,
            )

        self.assertEqual(
            {"requested": False, "readiness": None, "blocking": [], "notes": []},
            context,
        )
        inspect.assert_not_called()

    def test_verified_graphify_surface_owns_readiness_inspection(self) -> None:
        with patch(
            "workflow_graphify_route.inspect_target_graphify",
            return_value={"ready": True, "query_smoke": True},
        ) as inspect:
            context = graphify_route_context(
                concerns=[],
                surface_matches=[{"name": "graphify_integration"}],
                project_root=ROOT,
            )

        self.assertTrue(context["requested"])
        self.assertTrue(context["readiness"]["ready"])
        self.assertEqual([], context["blocking"])
        inspect.assert_called_once_with(ROOT)

    def test_requested_readiness_without_project_is_blocking(self) -> None:
        context = graphify_route_context(
            concerns=["graphify"], surface_matches=[], project_root=None
        )

        self.assertFalse(context["readiness"]["ready"])
        self.assertTrue(context["blocking"])

    def test_bare_inferred_mention_does_not_require_readiness(self) -> None:
        for request in (
            "Fix the Bash gate: pure lookups (npm view/whoami/ls, graphify query/path/explain) "
            "should classify as read_only; add no new deny",
            "graphify query 명령을 읽기 전용으로 분류해줘",
            "Explain what graphify explain prints",
        ):
            with self.subTest(request=request), patch(
                "workflow_graphify_route.inspect_target_graphify"
            ) as inspect:
                context = graphify_route_context(
                    concerns=["graphify"],
                    surface_matches=[],
                    project_root=ROOT,
                    inferred_concerns={"graphify"},
                    request_text=request,
                )
                self.assertFalse(context["requested"])
                self.assertEqual([], context["blocking"])
                inspect.assert_not_called()

    def test_graph_setup_requests_still_require_readiness(self) -> None:
        for request in (
            "Install graphify for this project",
            "Set up the project graph with graphify",
            "Rebuild the knowledge graph with graphify update",
            "graphify 그래프를 갱신해줘",
            "그래프 설치해줘",
            "/graphify .",
        ):
            with self.subTest(request=request), patch(
                "workflow_graphify_route.inspect_target_graphify",
                return_value={"ready": False},
            ):
                context = graphify_route_context(
                    concerns=["graphify"],
                    surface_matches=[],
                    project_root=ROOT,
                    inferred_concerns={"graphify"},
                    request_text=request,
                )
                self.assertTrue(context["requested"])

    def test_named_concern_and_surface_keep_readiness_without_setup_words(self) -> None:
        self.assertTrue(graphify_is_work_target(
            ["graphify"], [], inferred_concerns=set(), request_text="mention only",
        ))
        self.assertTrue(graphify_is_work_target(
            [], [{"name": "target_project_graphify"}],
            inferred_concerns={"graphify"}, request_text="mention only",
        ))

    def test_route_gates_follow_the_work_target(self) -> None:
        mention = resolve_docs(
            "bugfix", None, ["graphify"], request_classified=True,
            request_text="classify graphify query as a read-only lookup",
            inferred_concerns=["graphify"],
        )
        setup = resolve_docs(
            "bugfix", None, ["graphify"], request_classified=True,
            request_text="install graphify and build the project graph",
            inferred_concerns=["graphify"],
        )
        self.assertNotIn("graphify readiness", mention["gates"])
        self.assertIn("graphify readiness", setup["gates"])


if __name__ == "__main__":
    unittest.main()
