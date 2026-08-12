#!/usr/bin/env python3
"""Validator and fidelity coverage report for design-summary.json.

Provides:
- validate_summary(summary): schema and invariant violations (empty means pass)
- coverage_report(summary): quantitative fidelity metrics and warning groups

The module is network-free and shared by offline tests, live smoke, and the CLI.
CLI: python3 figma_validate.py <design-summary.json>  (exit 1 on violations)
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

_HEX_RE = re.compile(r"^#[0-9A-F]{6}([0-9A-F]{2})?$")
_REQUIRED_TOP_KEYS = (
    "meta",
    "screens",
    "flowEdges",
    "flowInteractions",
    "designTokens",
    "components",
    "componentBlueprints",
    "colors",
    "gradients",
    "textStyles",
    "textRuns",
    "effects",
    "layoutMetrics",
    "layoutNodes",
    "assetCandidates",
    "assetInventory",
    "warnings",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_summary(summary: dict[str, Any]) -> list[str]:
    """Return structural and invariant violations; an empty list means pass."""
    problems: list[str] = []

    def require(cond: bool, message: str) -> None:
        if not cond:
            problems.append(message)

    require(isinstance(summary, dict), "summary is not an object")
    if not isinstance(summary, dict):
        return problems

    for key in _REQUIRED_TOP_KEYS:
        require(key in summary, f"missing top-level key: {key}")

    meta = summary.get("meta", {})
    require(isinstance(meta, dict) and bool(meta.get("fileKey")), "meta.fileKey missing")
    require(isinstance(meta, dict) and bool(meta.get("startNodeId")), "meta.startNodeId missing")
    require(isinstance(meta, dict) and bool(meta.get("generatedAt")), "meta.generatedAt missing")

    for i, screen in enumerate(summary.get("screens", []) or []):
        require(bool(screen.get("id")), f"screens[{i}].id missing")

    for i, color in enumerate(summary.get("colors", []) or []):
        hex_value = color.get("hex")
        require(
            isinstance(hex_value, str) and bool(_HEX_RE.match(hex_value)),
            f"colors[{i}].hex invalid: {hex_value!r}",
        )

    for i, gradient in enumerate(summary.get("gradients", []) or []):
        for j, stop in enumerate(gradient.get("stops", []) or []):
            pos = stop.get("position")
            if pos is not None:
                require(
                    _is_number(pos) and -0.001 <= pos <= 1.001,
                    f"gradients[{i}].stops[{j}].position out of [0,1]: {pos!r}",
                )

    for i, node in enumerate(summary.get("layoutNodes", []) or []):
        require(bool(node.get("id")), f"layoutNodes[{i}].id missing")
        require("type" in node, f"layoutNodes[{i}].type missing")
        opacity = node.get("opacity")
        if opacity is not None:
            require(
                _is_number(opacity) and -0.001 <= opacity <= 1.001,
                f"layoutNodes[{i}].opacity out of [0,1]: {opacity!r}",
            )
        stroke = node.get("strokeWeight")
        if stroke is not None:
            require(_is_number(stroke) and stroke >= 0, f"layoutNodes[{i}].strokeWeight invalid: {stroke!r}")
        box = node.get("absoluteBoundingBox")
        if box is not None:
            require(
                isinstance(box, dict) and all(_is_number(box.get(k)) for k in ("x", "y", "width", "height")),
                f"layoutNodes[{i}].absoluteBoundingBox malformed",
            )

    for i, style in enumerate(summary.get("textStyles", []) or []):
        size = style.get("fontSize")
        if size is not None:
            require(_is_number(size) and size > 0, f"textStyles[{i}].fontSize invalid: {size!r}")

    for i, asset in enumerate(summary.get("assetCandidates", []) or []):
        require(bool(asset.get("id")), f"assetCandidates[{i}].id missing")

    for i, comp in enumerate(summary.get("components", []) or []):
        require(bool(comp.get("componentId")), f"components[{i}].componentId missing")
        count = comp.get("usageCount")
        require(
            _is_number(count) and count >= 1,
            f"components[{i}].usageCount invalid: {count!r}",
        )

    for i, bp in enumerate(summary.get("componentBlueprints", []) or []):
        require(bool(bp.get("componentId")), f"componentBlueprints[{i}].componentId missing")
        require(isinstance(bp.get("structure"), list), f"componentBlueprints[{i}].structure not a list")

    for i, icon in enumerate(summary.get("assetInventory", []) or []):
        require(bool(icon.get("dedupKey")), f"assetInventory[{i}].dedupKey missing")
        count = icon.get("usageCount")
        require(
            _is_number(count) and count >= 1,
            f"assetInventory[{i}].usageCount invalid: {count!r}",
        )

    tokens = summary.get("designTokens", {})
    require(isinstance(tokens, dict) and "variables" in tokens, "designTokens.variables missing")

    return problems


def coverage_report(summary: dict[str, Any]) -> dict[str, Any]:
    """Return quantitative fidelity metrics, including rendered asset recovery."""
    layout_nodes = summary.get("layoutNodes", []) or []

    def count_with(field: str) -> int:
        return sum(1 for n in layout_nodes if n.get(field) is not None)

    assets = summary.get("assetCandidates", []) or []
    uniq: dict[str, dict[str, Any]] = {}
    for asset in assets:
        aid = asset.get("id")
        if aid and aid not in uniq:
            uniq[aid] = asset
    asset_values = list(uniq.values())
    image_fills = [a for a in asset_values if a.get("imageRefs")]

    warnings = summary.get("warnings", []) or []
    warn_asset = sum(1 for w in warnings if "not renderable standalone" in w)
    warn_vars = sum(1 for w in warnings if "Variables" in w or "variables" in w)

    variables = summary.get("designTokens", {}).get("variables", {}).get("variables", []) or []

    components = summary.get("components", []) or []
    inventory = summary.get("assetInventory", []) or []

    return {
        "screens": len(summary.get("screens", []) or []),
        "components": {
            "total": len(components),
            "instances": sum(c.get("usageCount", 0) for c in components),
            "withVariant": sum(1 for c in components if c.get("variantProperties")),
            "blueprints": len(summary.get("componentBlueprints", []) or []),
        },
        "layoutNodes": {
            "total": len(layout_nodes),
            "withOpacity": count_with("opacity"),
            "withStrokeWeight": count_with("strokeWeight"),
            "withRotation": count_with("rotation"),
            "withRenderBounds": count_with("absoluteRenderBounds"),
            "withConstraints": count_with("constraints"),
        },
        "colors": len(summary.get("colors", []) or []),
        "gradients": len(summary.get("gradients", []) or []),
        "textStyles": len(summary.get("textStyles", []) or []),
        "textRuns": len(summary.get("textRuns", []) or []),
        "effects": len(summary.get("effects", []) or []),
        "assets": {
            "total": len(asset_values),
            "withPath": sum(1 for a in asset_values if a.get("assetPath")),
            "imageFillTotal": len(image_fills),
            "imageFillWithPath": sum(1 for a in image_fills if a.get("assetPath")),
            "withFallbackChain": sum(1 for a in asset_values if a.get("renderFallbackIds")),
            "withNearestComponent": sum(1 for a in asset_values if a.get("nearestComponentName")),
        },
        "iconInventory": {
            "unique": len(inventory),
            "nameUnclear": sum(1 for i in inventory if i.get("nameUnclear")),
            "namedByComponent": sum(1 for i in inventory if i.get("nameUnclear") and i.get("nearestComponentName")),
        },
        "variables": {
            "count": len(variables),
            "enterpriseAvailable": len(variables) > 0,
        },
        "warnings": {
            "total": len(warnings),
            "assetNotRenderable": warn_asset,
            "variables": warn_vars,
            "other": len(warnings) - warn_asset - warn_vars,
        },
    }


def format_report(problems: list[str], coverage: dict[str, Any]) -> str:
    lines: list[str] = ["# Figma Handoff Validation Report", ""]
    if problems:
        lines.append(f"## ❌ Schema Violations ({len(problems)})")
        lines.extend(f"- {p}" for p in problems)
    else:
        lines.append("## ✅ No Schema Violations")
    lines.append("")
    lines.append("## Fidelity Coverage")
    a = coverage["assets"]
    ln = coverage["layoutNodes"]
    w = coverage["warnings"]
    img_pct = (a["imageFillWithPath"] * 100 // a["imageFillTotal"]) if a["imageFillTotal"] else 100
    asset_pct = (a["withPath"] * 100 // a["total"]) if a["total"] else 0
    c = coverage["components"]
    lines.extend([
        f"- Screens: {coverage['screens']}",
        f"- Components: {c['total']} (instances {c['instances']} / variants {c['withVariant']} / blueprints {c['blueprints']})",
        f"- layoutNodes: {ln['total']} (opacity {ln['withOpacity']} / stroke {ln['withStrokeWeight']} "
        f"/ rotation {ln['withRotation']} / renderBounds {ln['withRenderBounds']})",
        f"- Colors {coverage['colors']} / gradients {coverage['gradients']} / text styles {coverage['textStyles']} "
        f"/ text runs {coverage['textRuns']} / effects {coverage['effects']}",
        f"- Image-fill recovery: {a['imageFillWithPath']}/{a['imageFillTotal']} ({img_pct}%)",
        f"- Overall asset recovery: {a['withPath']}/{a['total']} ({asset_pct}%), fallback chains {a['withFallbackChain']}",
        f"- Unique icons: {coverage['iconInventory']['unique']} (name unclear {coverage['iconInventory']['nameUnclear']} / "
        f"named by component {coverage['iconInventory']['namedByComponent']}), assets linked to components {a['withNearestComponent']}",
        f"- Variables: {coverage['variables']['count']} (metadata {'available' if coverage['variables']['enterpriseAvailable'] else 'unavailable'})",
        f"- Warnings: {w['total']} (asset not renderable {w['assetNotRenderable']} / variables {w['variables']} / other {w['other']})",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 figma_validate.py <design-summary.json>", file=sys.stderr)
        return 2
    try:
        summary = json.loads(open(argv[1], encoding="utf-8").read())
    except (OSError, ValueError) as error:
        print(f"ERROR: cannot read summary: {error}", file=sys.stderr)
        return 2
    problems = validate_summary(summary)
    print(format_report(problems, coverage_report(summary)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
