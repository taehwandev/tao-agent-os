from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

from figma_analyze import summarize_component_blueprints, summarize_components, summarize_layout_nodes
from figma_report import build_summary


class OverlappingDocumentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = {
            "id": "2:2",
            "name": "Card",
            "type": "INSTANCE",
            "componentId": "10:1",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 40},
            "children": [{"id": "2:3", "name": "Label", "type": "TEXT", "characters": "Hello"}],
        }
        self.frame = {
            "id": "2:1",
            "name": "Screen",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 375, "height": 812},
            "children": [self.instance],
        }
        self.section = {"id": "1:1", "name": "Flow", "type": "SECTION", "children": [self.frame]}
        self.documents = {"1:1": self.section, "2:1": self.frame}

    def test_direct_analyzers_count_overlapping_nodes_once(self) -> None:
        layout_nodes = summarize_layout_nodes(list(self.documents.values()))
        self.assertEqual([node["id"] for node in layout_nodes].count("2:1"), 1)
        self.assertEqual([node["id"] for node in layout_nodes].count("2:2"), 1)

        components = summarize_components(self.documents, component_index=None)
        self.assertEqual(components[0]["usageCount"], 1)
        blueprints = summarize_component_blueprints(self.documents, components)
        self.assertEqual(blueprints[0]["usageCount"], 1)

    def test_summary_deduplicates_layout_components_and_blueprints(self) -> None:
        summary = build_summary(
            file_key="FILE",
            start_node_id="1:1",
            source_url=None,
            node_documents=self.documents,
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables={},
            file_styles={},
            warnings=[],
        )
        layout_ids = [node["id"] for node in summary["layoutNodes"]]
        self.assertEqual(len(layout_ids), len(set(layout_ids)))
        self.assertEqual(summary["components"][0]["usageCount"], 1)
        self.assertEqual(summary["componentBlueprints"][0]["usageCount"], 1)

    def test_hidden_ancestor_wins_when_overlapping_child_root_arrives_first(self) -> None:
        self.section["visible"] = False
        documents = {"2:1": self.frame, "1:1": self.section}

        layout_nodes = summarize_layout_nodes(list(documents.values()))
        by_id = {node["id"]: node for node in layout_nodes}

        self.assertFalse(by_id["2:1"]["effectiveVisible"])
        self.assertEqual(by_id["2:1"]["visibilityReasons"], ["ancestor:1:1.visible=false"])
        self.assertFalse(by_id["2:2"]["effectiveVisible"])
        self.assertEqual(by_id["2:2"]["visibilityReasons"], ["ancestor:1:1.visible=false"])


if __name__ == "__main__":
    unittest.main()
