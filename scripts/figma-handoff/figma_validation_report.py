"""Human-readable report rendering for Figma handoff validation."""

from __future__ import annotations

from typing import Any


def format_report(problems: list[str], coverage: dict[str, Any]) -> str:
    lines = ["# Figma Handoff Validation Report", ""]
    if problems:
        lines.extend([f"## ❌ Schema Violations ({len(problems)})", *(f"- {problem}" for problem in problems)])
    else:
        lines.append("## ✅ No Schema Violations")
    assets = coverage["assets"]
    layout = coverage["layoutNodes"]
    warnings = coverage["warnings"]
    components = coverage["components"]
    image_percent = assets["imageFillWithPath"] * 100 // assets["imageFillTotal"] if assets["imageFillTotal"] else 100
    asset_percent = assets["withPath"] * 100 // assets["total"] if assets["total"] else 0
    lines.extend([
        "", "## Fidelity Coverage",
        f"- Screens: {coverage['screens']}",
        f"- Components: {components['total']} (instances {components['instances']} / variants {components['withVariant']} / blueprints {components['blueprints']})",
        f"- layoutNodes: {layout['total']} (opacity {layout['withOpacity']} / stroke {layout['withStrokeWeight']} / rotation {layout['withRotation']} / renderBounds {layout['withRenderBounds']})",
        f"- Colors {coverage['colors']} / gradients {coverage['gradients']} / text styles {coverage['textStyles']} / text runs {coverage['textRuns']} / effects {coverage['effects']}",
        f"- Image-fill recovery: {assets['imageFillWithPath']}/{assets['imageFillTotal']} ({image_percent}%)",
        f"- Overall asset recovery: {assets['withPath']}/{assets['total']} ({asset_percent}%), fallback chains {assets['withFallbackChain']}",
        f"- Unique icons: {coverage['iconInventory']['unique']} (name unclear {coverage['iconInventory']['nameUnclear']} / named by component {coverage['iconInventory']['namedByComponent']}), assets linked to components {assets['withNearestComponent']}",
        f"- Variables: {coverage['variables']['count']} (metadata {'available' if coverage['variables']['metadataAvailable'] else 'unavailable'})",
        f"- Warnings: {warnings['total']} (asset not renderable {warnings['assetNotRenderable']} / variables {warnings['variables']} / other {warnings['other']})",
    ])
    return "\n".join(lines) + "\n"
