from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

from figma_coverage import coverage_report
from figma_summary_validate import validate_summary
from figma_validate import main


def _valid_summary() -> dict:
    return {
        "meta": {"fileKey": "FILE", "startNodeId": "1:1", "generatedAt": "2026-08-12T00:00:00Z"},
        "screens": [],
        "flowEdges": [],
        "flowInteractions": [],
        "designTokens": {"variables": {}},
        "components": [],
        "componentBlueprints": [],
        "colors": [],
        "gradients": [],
        "textStyles": [],
        "textRuns": [],
        "effects": [],
        "layoutMetrics": {},
        "layoutNodes": [],
        "assetCandidates": [],
        "assetInventory": [],
        "warnings": [],
    }


def _valid_v4_summary() -> dict:
    summary = _valid_summary()
    summary.update(
        {
            "schemaVersion": 4,
            "layoutNodes": [
                {
                    "id": "1:1",
                    "name": "Screen",
                    "type": "FRAME",
                    "effectiveVisible": True,
                },
                {
                    "id": "1:2",
                    "name": "HiddenFilter",
                    "type": "INSTANCE",
                    "visible": False,
                    "effectiveVisible": False,
                    "visibilityReasons": ["self.visible=false"],
                },
            ],
            "implementationInventory": {
                "renderedNodeIds": ["1:1"],
                "excludedNodes": [
                    {
                        "id": "1:2",
                        "name": "HiddenFilter",
                        "type": "INSTANCE",
                        "reasons": ["self.visible=false"],
                    }
                ],
            },
        }
    )
    return summary


class FigmaValidatorShapeTests(unittest.TestCase):
    def test_non_object_summary_returns_violation_and_safe_coverage(self) -> None:
        self.assertEqual(validate_summary([]), ["summary is not an object"])
        coverage = coverage_report([])
        self.assertEqual(coverage["screens"], 0)
        self.assertEqual(coverage["layoutNodes"]["total"], 0)

    def test_wrong_container_types_are_reported_without_exception(self) -> None:
        summary = _valid_summary()
        summary.update(
            {
                "meta": [],
                "screens": {},
                "designTokens": [],
                "layoutMetrics": [],
                "layoutNodes": [None],
                "components": ["bad"],
                "warnings": [42],
            }
        )
        problems = validate_summary(summary)
        self.assertIn("meta is not an object", problems)
        self.assertIn("screens is not a list", problems)
        self.assertIn("designTokens is not an object", problems)
        self.assertIn("layoutNodes[0] is not an object", problems)
        self.assertIn("components[0] is not an object", problems)
        coverage_report(summary)

    def test_cli_reports_non_object_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "summary.json"
            path.write_text(json.dumps([]), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["figma_validate.py", str(path)])
        self.assertEqual(result, 1)
        self.assertIn("summary is not an object", stdout.getvalue())
        self.assertNotIn("Traceback", stdout.getvalue())

    def test_valid_summary_remains_valid(self) -> None:
        self.assertEqual(validate_summary(_valid_summary()), [])

    def test_valid_schema_v4_visibility_inventory_passes(self) -> None:
        self.assertEqual(validate_summary(_valid_v4_summary()), [])

    def test_schema_v4_rejects_partition_overlap_and_hidden_asset_leak(self) -> None:
        summary = _valid_v4_summary()
        summary["implementationInventory"]["renderedNodeIds"].append("1:2")
        summary["assetCandidates"].append({"id": "1:2"})
        summary["flowEdges"].append({"fromNodeId": "1:2", "toNodeId": "1:1"})
        summary["flowInteractions"].append({"fromNodeId": "1:2"})
        problems = validate_summary(summary)
        self.assertIn(
            "implementationInventory rendered and excluded node ids overlap: 1:2",
            problems,
        )
        self.assertIn("assetCandidates includes excluded node id: 1:2", problems)
        self.assertIn("flowEdges includes excluded source node id: 1:2", problems)
        self.assertIn("flowInteractions includes excluded source node id: 1:2", problems)


if __name__ == "__main__":
    unittest.main()
