from __future__ import annotations

import argparse
from typing import Any

__all__ = ["build_manifest"]


def build_manifest(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": summary.get("schemaVersion", 3),
        "tool": "figma-handoff.py",
        "arguments": {
            "format": args.format,
            "scale": args.scale,
            "maxFlowDepth": args.max_flow_depth,
            "images": not args.no_images,
            "includeImageFills": args.include_image_fills,
            "exportAssets": getattr(args, "export_assets", False),
        },
        "summary": {
            "screenCount": len(summary["screens"]),
            "flowEdgeCount": len(summary["flowEdges"]),
            "flowInteractionCount": len(summary.get("flowInteractions", [])),
            "namedColorStyleCount": len(summary["designTokens"]["colorStyles"]),
            "namedTextStyleCount": len(summary["designTokens"]["textStyles"]),
            "namedEffectStyleCount": len(summary["designTokens"]["effectStyles"]),
            "variableCount": len(summary["designTokens"]["variables"].get("variables", [])),
            "referencedColorStyleCount": len(summary.get("referencedStyles", {}).get("colorStyles", [])),
            "referencedTextStyleCount": len(summary.get("referencedStyles", {}).get("textStyles", [])),
            "referencedEffectStyleCount": len(summary.get("referencedStyles", {}).get("effectStyles", [])),
            "componentCount": len(summary.get("components", [])),
            "componentBlueprintCount": len(summary.get("componentBlueprints", [])),
            "colorCandidateCount": len(summary["colors"]),
            "gradientCandidateCount": len(summary.get("gradients", [])),
            "textStyleCandidateCount": len(summary["textStyles"]),
            "textRunCount": len(summary.get("textRuns", [])),
            "effectCandidateCount": len(summary.get("effects", [])),
            "layoutNodeCount": len(summary.get("layoutNodes", [])),
            "renderedNodeCount": len(
                summary.get("implementationInventory", {}).get("renderedNodeIds", [])
            ),
            "excludedNodeCount": len(
                summary.get("implementationInventory", {}).get("excludedNodes", [])
            ),
            "assetCandidateCount": len(summary["assetCandidates"]),
            "assetInventoryCount": len(summary.get("assetInventory", [])),
        },
    }
