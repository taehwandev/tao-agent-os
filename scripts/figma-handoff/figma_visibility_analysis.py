from __future__ import annotations

from typing import Any

from figma_util import is_number, paint_to_hex, parse_gradient_paint, round_number

__all__ = ["VisibilityAnalysis"]


def _own_reasons(node: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if node.get("visible") is False:
        reasons.append("self.visible=false")
    opacity = node.get("opacity")
    if is_number(opacity) and float(opacity) <= 0:
        reasons.append("self.opacity=0")
    return reasons


def _ancestor_reasons(node: dict[str, Any], node_id: str) -> list[str]:
    label = node_id or str(node.get("name", "")) or "unknown"
    reasons: list[str] = []
    if node.get("visible") is False:
        reasons.append(f"ancestor:{label}.visible=false")
    opacity = node.get("opacity")
    if is_number(opacity) and float(opacity) <= 0:
        reasons.append(f"ancestor:{label}.opacity=0")
    return reasons


def _rendered_paints(node: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for field in ("background", "fills", "strokes"):
        paints = node.get(field, []) or []
        if not isinstance(paints, list):
            continue
        summarized = [
            paint_summary
            for paint in paints
            if isinstance(paint, dict)
            and (paint_summary := _rendered_paint(paint)) is not None
        ]
        if summarized:
            result[field] = summarized

    background_color = node.get("backgroundColor")
    if isinstance(background_color, dict):
        summary = _rendered_paint({"type": "SOLID", "color": background_color})
        if summary:
            result["backgroundColor"] = [summary]
    return result


def _rendered_paint(paint: dict[str, Any]) -> dict[str, Any] | None:
    if paint.get("visible") is False:
        return None
    opacity = paint.get("opacity")
    if is_number(opacity) and float(opacity) <= 0:
        return None
    paint_type = paint.get("type")
    if not isinstance(paint_type, str) or not paint_type:
        return None

    summary: dict[str, Any] = {"type": paint_type}
    if is_number(opacity):
        summary["opacity"] = round_number(opacity)
    if isinstance(paint.get("blendMode"), str):
        summary["blendMode"] = paint["blendMode"]

    if paint_type == "SOLID":
        hex_value = paint_to_hex(paint)
        if not hex_value or (len(hex_value) == 9 and hex_value.endswith("00")):
            return None
        summary["hex"] = hex_value
    elif gradient := parse_gradient_paint(paint):
        summary["gradient"] = gradient
    elif paint_type == "IMAGE":
        if paint.get("imageRef"):
            summary["imageRef"] = paint["imageRef"]
        if paint.get("scaleMode"):
            summary["scaleMode"] = paint["scaleMode"]
        if isinstance(paint.get("imageTransform"), list):
            summary["imageTransform"] = _round_value(paint["imageTransform"])
    return summary


def _round_value(value: Any) -> Any:
    if is_number(value):
        return round_number(value)
    if isinstance(value, dict):
        return {str(key): _round_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_round_value(item) for item in value]
    return value


def _build_inventory(layout_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "renderedNodeIds": [
            node["id"]
            for node in layout_nodes
            if node.get("effectiveVisible") is True and node.get("id")
        ],
        "excludedNodes": [
            {
                "id": node["id"],
                "name": node.get("name", ""),
                "type": node.get("type", ""),
                "reasons": node.get("visibilityReasons", []),
            }
            for node in layout_nodes
            if node.get("effectiveVisible") is False and node.get("id")
        ],
    }


class VisibilityAnalysis:
    """Effective visibility, implementation inventory, and node paint provenance."""

    ancestor_reasons = staticmethod(_ancestor_reasons)
    build_inventory = staticmethod(_build_inventory)
    own_reasons = staticmethod(_own_reasons)
    rendered_paints = staticmethod(_rendered_paints)
