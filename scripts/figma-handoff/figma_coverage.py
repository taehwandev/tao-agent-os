"""Fidelity coverage calculation for Figma handoff summaries."""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def coverage_report(summary: Any) -> dict[str, Any]:
    root = _mapping(summary)
    layout_nodes = [item for item in _sequence(root.get("layoutNodes")) if isinstance(item, dict)]
    assets = [item for item in _sequence(root.get("assetCandidates")) if isinstance(item, dict)]
    unique_assets: dict[str, dict[str, Any]] = {}
    for asset in assets:
        asset_id = asset.get("id")
        if isinstance(asset_id, str) and asset_id and asset_id not in unique_assets:
            unique_assets[asset_id] = asset
    asset_values = list(unique_assets.values())
    image_fills = [asset for asset in asset_values if asset.get("imageRefs")]
    warnings = [warning for warning in _sequence(root.get("warnings")) if isinstance(warning, str)]
    variables = _sequence(_mapping(_mapping(root.get("designTokens")).get("variables")).get("variables"))
    components = [item for item in _sequence(root.get("components")) if isinstance(item, dict)]
    inventory = [item for item in _sequence(root.get("assetInventory")) if isinstance(item, dict)]

    def count_with(field: str) -> int:
        return sum(1 for node in layout_nodes if node.get(field) is not None)

    asset_warning_count = sum("not renderable standalone" in warning for warning in warnings)
    variable_warning_count = sum("Variables" in warning or "variables" in warning for warning in warnings)
    return {
        "screens": len(_sequence(root.get("screens"))),
        "components": {
            "total": len(components),
            "instances": sum(
                item.get("usageCount", 0)
                for item in components
                if _is_number(item.get("usageCount", 0))
            ),
            "withVariant": sum(1 for item in components if item.get("variantProperties")),
            "blueprints": len(_sequence(root.get("componentBlueprints"))),
        },
        "layoutNodes": {
            "total": len(layout_nodes),
            "withOpacity": count_with("opacity"),
            "withStrokeWeight": count_with("strokeWeight"),
            "withRotation": count_with("rotation"),
            "withRenderBounds": count_with("absoluteRenderBounds"),
            "withConstraints": count_with("constraints"),
        },
        "colors": len(_sequence(root.get("colors"))),
        "gradients": len(_sequence(root.get("gradients"))),
        "textStyles": len(_sequence(root.get("textStyles"))),
        "textRuns": len(_sequence(root.get("textRuns"))),
        "effects": len(_sequence(root.get("effects"))),
        "assets": {
            "total": len(asset_values),
            "withPath": sum(bool(item.get("assetPath")) for item in asset_values),
            "imageFillTotal": len(image_fills),
            "imageFillWithPath": sum(bool(item.get("assetPath")) for item in image_fills),
            "withFallbackChain": sum(bool(item.get("renderFallbackIds")) for item in asset_values),
            "withNearestComponent": sum(bool(item.get("nearestComponentName")) for item in asset_values),
        },
        "iconInventory": {
            "unique": len(inventory),
            "nameUnclear": sum(bool(item.get("nameUnclear")) for item in inventory),
            "namedByComponent": sum(
                bool(item.get("nameUnclear") and item.get("nearestComponentName"))
                for item in inventory
            ),
        },
        "variables": {"count": len(variables), "metadataAvailable": bool(variables)},
        "warnings": {
            "total": len(warnings),
            "assetNotRenderable": asset_warning_count,
            "variables": variable_warning_count,
            "other": len(warnings) - asset_warning_count - variable_warning_count,
        },
    }
