from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_graphify_route import graphify_route_context


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


if __name__ == "__main__":
    unittest.main()
