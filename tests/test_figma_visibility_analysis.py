from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

from figma_visibility_analysis import VisibilityAnalysis


class VisibilityAnalysisTests(unittest.TestCase):
    def test_visibility_reasons_distinguish_self_and_ancestor(self) -> None:
        hidden = {"id": "1:9", "visible": False}
        transparent = {"id": "1:11", "opacity": 0}

        self.assertEqual(VisibilityAnalysis.own_reasons(hidden), ["self.visible=false"])
        self.assertEqual(
            VisibilityAnalysis.ancestor_reasons(hidden, "1:9"),
            ["ancestor:1:9.visible=false"],
        )
        self.assertEqual(VisibilityAnalysis.own_reasons(transparent), ["self.opacity=0"])

    def test_rendered_paints_keep_exact_solid_alpha_and_gradient_stops(self) -> None:
        paints = VisibilityAnalysis.rendered_paints(
            {
                "fills": [
                    {
                        "type": "SOLID",
                        "opacity": 0.5,
                        "color": {"r": 1, "g": 0, "b": 0, "a": 0.5},
                    }
                ],
                "strokes": [
                    {
                        "type": "GRADIENT_LINEAR",
                        "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
                        "gradientStops": [
                            {"position": 0, "color": {"r": 1, "g": 1, "b": 1, "a": 0.45}},
                            {"position": 1, "color": {"r": 1, "g": 1, "b": 1, "a": 0.05}},
                        ],
                    }
                ],
            }
        )

        self.assertEqual(paints["fills"][0]["hex"], "#FF000040")
        self.assertEqual(
            [stop["hex"] for stop in paints["strokes"][0]["gradient"]["stops"]],
            ["#FFFFFF73", "#FFFFFF0D"],
        )

    def test_inventory_partitions_rendered_and_excluded_nodes(self) -> None:
        inventory = VisibilityAnalysis.build_inventory(
            [
                {"id": "1:1", "effectiveVisible": True},
                {
                    "id": "1:2",
                    "name": "HiddenFilter",
                    "type": "INSTANCE",
                    "effectiveVisible": False,
                    "visibilityReasons": ["self.visible=false"],
                },
            ]
        )

        self.assertEqual(inventory["renderedNodeIds"], ["1:1"])
        self.assertEqual(inventory["excludedNodes"][0]["id"], "1:2")


if __name__ == "__main__":
    unittest.main()
