from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.graphify_graph_integrity import (
    inspect_graph_integrity,
    repair_graph_integrity,
)


class GraphifyIntegrityRepairTests(unittest.TestCase):
    def test_repair_removes_edges_but_fails_closed_on_ambiguous_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "a", "file_type": "code", "label": "kept"},
                            {"id": "a", "file_type": "code", "label": "duplicate"},
                            {"id": "missing-type", "label": "malformed"},
                            {"label": "missing id", "file_type": "document"},
                            {"id": "b", "file_type": "document"},
                        ],
                        "links": [
                            {"source": "a", "target": "b", "type": "VALID"},
                            {"source": "a", "target": "missing", "type": "DANGLING"},
                            {"source": "a", "target": "a", "type": "SELF"},
                            "malformed",
                        ],
                        "metadata": {"preserved": True},
                    }
                ),
                encoding="utf-8",
            )

            result = repair_graph_integrity(graph)
            repaired = json.loads(graph.read_text(encoding="utf-8"))
            verified = inspect_graph_integrity(graph.parent, graph)

        self.assertFalse(result["ready"])
        self.assertEqual(0, result["removed_node_count"])
        self.assertEqual(3, result["removed_edge_count"])
        self.assertEqual(
            [
                {"id": "a", "file_type": "code", "label": "kept"},
                {"id": "a", "file_type": "code", "label": "duplicate"},
                {"id": "missing-type", "label": "malformed"},
                {"label": "missing id", "file_type": "document"},
                {"id": "b", "file_type": "document"},
            ],
            repaired["nodes"],
        )
        self.assertEqual(
            [{"source": "a", "target": "b", "type": "VALID"}],
            repaired["links"],
        )
        self.assertEqual({"preserved": True}, repaired["metadata"])
        self.assertFalse(verified["graph_integrity_ready"])

    def test_repair_cannot_report_ready_without_any_valid_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "missing-type"},
                            {"label": "missing-id", "file_type": "code"},
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            result = repair_graph_integrity(graph)
            verified = inspect_graph_integrity(graph.parent, graph)

        self.assertFalse(result["ready"])
        self.assertEqual(0, result["removed_node_count"])
        self.assertFalse(verified["graph_integrity_ready"])

    def test_ready_is_bound_to_post_write_reinspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "a", "file_type": "code"}],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "support.graphify_graph_integrity.inspect_graph_integrity",
                return_value={"graph_integrity_ready": False},
            ):
                result = repair_graph_integrity(graph)

        self.assertFalse(result["ready"])

    def test_dry_run_reports_sanitized_counts_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            original = json.dumps(
                {
                    "nodes": [
                        {"id": "a", "file_type": "code"},
                        {"id": "a", "file_type": "code"},
                    ],
                    "links": [{"source": "a", "target": "missing"}],
                }
            )
            graph.write_text(original, encoding="utf-8")

            result = repair_graph_integrity(graph, dry_run=True)
            after = graph.read_text(encoding="utf-8")

        self.assertFalse(result["ready"])
        self.assertEqual(0, result["removed_node_count"])
        self.assertEqual(1, result["removed_edge_count"])
        self.assertEqual(original, after)


if __name__ == "__main__":
    unittest.main()
