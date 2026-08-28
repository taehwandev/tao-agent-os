from __future__ import annotations

from collections import Counter
from typing import Any

from figma_util import extract_text_style, format_number, is_number, normalize_node_id, round_number

__all__ = ["LayoutAnalysis"]


def _summarize_layout_metrics(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    numeric_keys = (
        "itemSpacing", "counterAxisSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
        "cornerRadius", "minWidth", "maxWidth", "minHeight", "maxHeight",
    )
    enum_keys = (
        "layoutMode", "primaryAxisAlignItems", "counterAxisAlignItems", "counterAxisAlignContent",
        "layoutWrap", "primaryAxisSizingMode", "counterAxisSizingMode", "layoutPositioning",
    )
    numeric_counters: dict[str, Counter[str]] = {key: Counter() for key in numeric_keys}
    enum_counters: dict[str, Counter[str]] = {key: Counter() for key in enum_keys}
    for node in nodes:
        radii = node.get("rectangleCornerRadii")
        has_individual_radii = isinstance(radii, list) and len(radii) == 4
        for key in numeric_keys:
            if key == "cornerRadius" and has_individual_radii:
                continue
            value = node.get(key)
            if is_number(value):
                numeric_counters[key][format_number(value)] += 1
        if has_individual_radii:
            for radius in radii:
                if is_number(radius):
                    numeric_counters["cornerRadius"][format_number(radius)] += 1
        for key in enum_keys:
            value = node.get(key)
            if isinstance(value, str) and value:
                enum_counters[key][value] += 1
    result: dict[str, list[dict[str, Any]]] = {}
    for key, counter in (*numeric_counters.items(), *enum_counters.items()):
        if counter:
            result[key] = [{"value": value, "count": count} for value, count in counter.most_common()]
    return result


def _summarize_layout_nodes(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten layout trees once even when fetched roots overlap."""
    result: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()

    def walk(node: Any, parent_id: str | None, depth: int) -> None:
        if not isinstance(node, dict):
            return
        node_id = normalize_node_id(str(node.get("id", "")))
        duplicate = bool(node_id and node_id in seen_node_ids)
        if node_id and not duplicate:
            seen_node_ids.add(node_id)
        if not duplicate:
            entry = _layout_node_entry(node, parent_id, depth)
            if entry:
                result.append(entry)
        current_id = node_id or parent_id
        for child in node.get("children", []) or []:
            walk(child, current_id, depth + 1)

    for document in documents:
        walk(document, None, 0)
    return result


def _layout_node_entry(node: dict[str, Any], parent_id: str | None, depth: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": normalize_node_id(str(node.get("id", ""))),
        "name": node.get("name", ""),
        "type": node.get("type", ""),
        "parentId": parent_id,
        "depth": depth,
    }
    bounds = _rounded_mapping(node.get("absoluteBoundingBox"))
    if bounds:
        entry["absoluteBoundingBox"] = bounds
    render_bounds = _rounded_mapping(node.get("absoluteRenderBounds"))
    if render_bounds:
        entry["absoluteRenderBounds"] = render_bounds
    fields = (
        "layoutMode", "layoutWrap", "primaryAxisAlignItems", "counterAxisAlignItems", "counterAxisAlignContent",
        "primaryAxisSizingMode", "counterAxisSizingMode", "layoutPositioning", "layoutAlign", "layoutGrow",
        "layoutSizingHorizontal", "layoutSizingVertical", "itemSpacing", "counterAxisSpacing", "paddingTop",
        "paddingRight", "paddingBottom", "paddingLeft", "cornerRadius", "rectangleCornerRadii", "minWidth",
        "maxWidth", "minHeight", "maxHeight", "constraints", "clipsContent", "overflowDirection", "opacity",
        "blendMode", "isMask", "maskType", "rotation", "relativeTransform", "size", "strokeWeight",
        "strokeAlign", "individualStrokeWeights", "strokeDashes", "visible",
    )
    for field in fields:
        if field in node:
            entry[field] = _round_layout_value(node[field])
    component_id = node.get("componentId")
    if isinstance(component_id, str) and component_id:
        entry["componentId"] = normalize_node_id(component_id)
    component_properties = _flatten_component_properties(node.get("componentProperties"))
    if component_properties:
        entry["componentProperties"] = component_properties
    return entry if len(entry) > 5 else {}


def _flatten_component_properties(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(name): prop.get("value")
        for name, prop in value.items()
        if isinstance(prop, dict)
    }


def _round_layout_value(value: Any) -> Any:
    if is_number(value):
        return round_number(value)
    if isinstance(value, dict):
        return _rounded_mapping(value)
    if isinstance(value, list):
        return [_round_layout_value(item) for item in value]
    return value


def _rounded_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _round_layout_value(child) for key, child in value.items()}


def _summarize_text_runs(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") != "TEXT":
            continue
        characters = str(node.get("characters", ""))
        overrides = node.get("characterStyleOverrides")
        override_table = node.get("styleOverrideTable")
        base_style = node.get("style")
        if not characters or not isinstance(overrides, list) or not isinstance(override_table, dict):
            continue
        if not isinstance(base_style, dict):
            base_style = {}
        run_start = 0
        current_override = overrides[0] if overrides else None
        for index, override_id in enumerate(overrides[1:], start=1):
            if override_id != current_override:
                _append_text_run(result, node, characters, base_style, override_table, run_start, index, current_override)
                run_start = index
                current_override = override_id
        _append_text_run(
            result, node, characters, base_style, override_table, run_start,
            min(len(overrides), len(characters)), current_override,
        )
    return result


def _append_text_run(
    result: list[dict[str, Any]],
    node: dict[str, Any],
    characters: str,
    base_style: dict[str, Any],
    override_table: dict[str, Any],
    start: int,
    end: int,
    override_id: Any,
) -> None:
    if end <= start or override_id in (None, 0, "0"):
        return
    override = override_table.get(str(override_id))
    if not isinstance(override, dict):
        return
    result.append(
        {
            "nodeId": normalize_node_id(str(node.get("id", ""))),
            "nodeName": node.get("name", ""),
            "range": {"start": start, "end": end},
            "text": characters[start:end],
            "overrideId": str(override_id),
            "resolvedStyle": extract_text_style({**base_style, **override}),
        }
    )


class LayoutAnalysis:
    """Layout metrics, flattened nodes, and text-run analysis family."""

    summarize_layout_metrics = staticmethod(_summarize_layout_metrics)
    summarize_layout_nodes = staticmethod(_summarize_layout_nodes)
    summarize_text_runs = staticmethod(_summarize_text_runs)
