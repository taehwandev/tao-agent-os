"""Network-free structural validation for ``design-summary.json``."""

from __future__ import annotations

import re
from typing import Any

_HEX_RE = re.compile(r"^#[0-9A-F]{6}([0-9A-F]{2})?$")
_REQUIRED_TOP_KEYS = (
    "meta", "screens", "flowEdges", "flowInteractions", "designTokens", "components",
    "componentBlueprints", "colors", "gradients", "textStyles", "textRuns", "effects",
    "layoutMetrics", "layoutNodes", "assetCandidates", "assetInventory", "warnings",
)
_LIST_KEYS = (
    "screens", "flowEdges", "flowInteractions", "components", "componentBlueprints", "colors",
    "gradients", "textStyles", "textRuns", "effects", "layoutNodes", "assetCandidates",
    "assetInventory", "warnings",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _validate_identified_items(
    problems: list[str],
    summary: dict[str, Any],
    collection_name: str,
    id_field: str,
    count_field: str | None = None,
) -> None:
    for index, item in enumerate(_sequence(summary.get(collection_name))):
        if not isinstance(item, dict):
            problems.append(f"{collection_name}[{index}] is not an object")
            continue
        if not item.get(id_field):
            problems.append(f"{collection_name}[{index}].{id_field} missing")
        if count_field:
            count = item.get(count_field)
            if not (_is_number(count) and count >= 1):
                problems.append(f"{collection_name}[{index}].{count_field} invalid: {count!r}")


def validate_summary(summary: Any) -> list[str]:
    """Return invariant violations without raising on malformed JSON shapes."""
    if not isinstance(summary, dict):
        return ["summary is not an object"]
    problems: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    for key in _REQUIRED_TOP_KEYS:
        require(key in summary, f"missing top-level key: {key}")
    for key in _LIST_KEYS:
        if key in summary:
            require(isinstance(summary[key], list), f"{key} is not a list")
    for key in ("meta", "designTokens", "layoutMetrics"):
        if key in summary:
            require(isinstance(summary[key], dict), f"{key} is not an object")

    meta = _mapping(summary.get("meta"))
    require(bool(meta.get("fileKey")), "meta.fileKey missing")
    require(bool(meta.get("startNodeId")), "meta.startNodeId missing")
    require(bool(meta.get("generatedAt")), "meta.generatedAt missing")

    for index, screen in enumerate(_sequence(summary.get("screens"))):
        if not isinstance(screen, dict):
            problems.append(f"screens[{index}] is not an object")
            continue
        require(bool(screen.get("id")), f"screens[{index}].id missing")

    for index, color in enumerate(_sequence(summary.get("colors"))):
        if not isinstance(color, dict):
            problems.append(f"colors[{index}] is not an object")
            continue
        hex_value = color.get("hex")
        require(
            isinstance(hex_value, str) and bool(_HEX_RE.match(hex_value)),
            f"colors[{index}].hex invalid: {hex_value!r}",
        )

    for index, gradient in enumerate(_sequence(summary.get("gradients"))):
        if not isinstance(gradient, dict):
            problems.append(f"gradients[{index}] is not an object")
            continue
        stops = gradient.get("stops", [])
        if not isinstance(stops, list):
            problems.append(f"gradients[{index}].stops is not a list")
            continue
        for stop_index, stop in enumerate(stops):
            if not isinstance(stop, dict):
                problems.append(f"gradients[{index}].stops[{stop_index}] is not an object")
                continue
            position = stop.get("position")
            if position is not None:
                require(
                    _is_number(position) and -0.001 <= position <= 1.001,
                    f"gradients[{index}].stops[{stop_index}].position out of [0,1]: {position!r}",
                )

    for index, node in enumerate(_sequence(summary.get("layoutNodes"))):
        if not isinstance(node, dict):
            problems.append(f"layoutNodes[{index}] is not an object")
            continue
        require(bool(node.get("id")), f"layoutNodes[{index}].id missing")
        require("type" in node, f"layoutNodes[{index}].type missing")
        opacity = node.get("opacity")
        if opacity is not None:
            require(
                _is_number(opacity) and -0.001 <= opacity <= 1.001,
                f"layoutNodes[{index}].opacity out of [0,1]: {opacity!r}",
            )
        stroke = node.get("strokeWeight")
        if stroke is not None:
            require(
                _is_number(stroke) and stroke >= 0,
                f"layoutNodes[{index}].strokeWeight invalid: {stroke!r}",
            )
        bounds = node.get("absoluteBoundingBox")
        if bounds is not None:
            require(
                isinstance(bounds, dict)
                and all(_is_number(bounds.get(key)) for key in ("x", "y", "width", "height")),
                f"layoutNodes[{index}].absoluteBoundingBox malformed",
            )

    _validate_identified_items(problems, summary, "assetCandidates", "id")
    _validate_identified_items(problems, summary, "components", "componentId", "usageCount")
    _validate_identified_items(problems, summary, "assetInventory", "dedupKey", "usageCount")
    for index, blueprint in enumerate(_sequence(summary.get("componentBlueprints"))):
        if not isinstance(blueprint, dict):
            problems.append(f"componentBlueprints[{index}] is not an object")
            continue
        require(bool(blueprint.get("componentId")), f"componentBlueprints[{index}].componentId missing")
        require(isinstance(blueprint.get("structure"), list), f"componentBlueprints[{index}].structure not a list")
    for index, style in enumerate(_sequence(summary.get("textStyles"))):
        if not isinstance(style, dict):
            problems.append(f"textStyles[{index}] is not an object")
            continue
        size = style.get("fontSize")
        if size is not None:
            require(_is_number(size) and size > 0, f"textStyles[{index}].fontSize invalid: {size!r}")

    require("variables" in _mapping(summary.get("designTokens")), "designTokens.variables missing")
    return problems
