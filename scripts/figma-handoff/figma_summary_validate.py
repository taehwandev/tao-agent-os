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


def _validate_layout_nodes(
    problems: list[str],
    nodes: list[Any],
    strict_visibility: bool,
) -> tuple[set[str], set[str], set[str]]:
    layout_node_ids: set[str] = set()
    rendered_ids: set[str] = set()
    excluded_ids: set[str] = set()

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            problems.append(f"layoutNodes[{index}] is not an object")
            continue
        require(bool(node.get("id")), f"layoutNodes[{index}].id missing")
        node_id = str(node.get("id", ""))
        if node_id:
            layout_node_ids.add(node_id)
        require("type" in node, f"layoutNodes[{index}].type missing")
        visible = node.get("visible")
        if visible is not None:
            require(isinstance(visible, bool), f"layoutNodes[{index}].visible not a boolean: {visible!r}")
        opacity = node.get("opacity")
        if opacity is not None:
            require(
                _is_number(opacity) and -0.001 <= opacity <= 1.001,
                f"layoutNodes[{index}].opacity out of [0,1]: {opacity!r}",
            )
        effective_visible = node.get("effectiveVisible")
        if strict_visibility:
            require(
                isinstance(effective_visible, bool),
                f"layoutNodes[{index}].effectiveVisible not a boolean: {effective_visible!r}",
            )
        reasons = node.get("visibilityReasons")
        if effective_visible is False:
            excluded_ids.add(node_id)
            require(
                isinstance(reasons, list)
                and bool(reasons)
                and all(isinstance(reason, str) and bool(reason) for reason in reasons),
                f"layoutNodes[{index}].visibilityReasons missing for excluded node",
            )
        elif effective_visible is True:
            rendered_ids.add(node_id)
            require(
                reasons in (None, []),
                f"layoutNodes[{index}].visibilityReasons present for rendered node",
            )
        _validate_rendered_paints(problems, node, index)
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
    return layout_node_ids, rendered_ids, excluded_ids


def _validate_implementation_inventory(
    problems: list[str],
    inventory: dict[str, Any],
    strict_visibility: bool,
    layout_node_ids: set[str],
    effective_rendered_ids: set[str],
    effective_excluded_ids: set[str],
) -> set[str]:
    if not inventory:
        return set()

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    rendered_values = inventory.get("renderedNodeIds")
    excluded_values = inventory.get("excludedNodes")
    require(
        isinstance(rendered_values, list)
        and all(isinstance(node_id, str) and bool(node_id) for node_id in rendered_values),
        "implementationInventory.renderedNodeIds is not a list of ids",
    )
    require(isinstance(excluded_values, list), "implementationInventory.excludedNodes is not a list")
    rendered_ids = {
        node_id for node_id in _sequence(rendered_values) if isinstance(node_id, str) and node_id
    }
    excluded_ids: set[str] = set()
    for index, node in enumerate(_sequence(excluded_values)):
        if not isinstance(node, dict):
            problems.append(f"implementationInventory.excludedNodes[{index}] is not an object")
            continue
        node_id = node.get("id")
        require(
            isinstance(node_id, str) and bool(node_id),
            f"implementationInventory.excludedNodes[{index}].id missing",
        )
        reasons = node.get("reasons")
        require(
            isinstance(reasons, list)
            and bool(reasons)
            and all(isinstance(reason, str) and bool(reason) for reason in reasons),
            f"implementationInventory.excludedNodes[{index}].reasons missing",
        )
        if isinstance(node_id, str) and node_id:
            excluded_ids.add(node_id)

    overlap = sorted(rendered_ids & excluded_ids)
    if overlap:
        problems.append(
            "implementationInventory rendered and excluded node ids overlap: " + ", ".join(overlap)
        )
    if strict_visibility:
        require(
            rendered_ids | excluded_ids == layout_node_ids,
            "implementationInventory does not partition all layout node ids",
        )
        require(
            rendered_ids == effective_rendered_ids,
            "implementationInventory.renderedNodeIds disagrees with effectiveVisible",
        )
        require(
            excluded_ids == effective_excluded_ids,
            "implementationInventory.excludedNodes disagrees with effectiveVisible",
        )
    return excluded_ids


def _validate_excluded_worklist_leaks(
    problems: list[str],
    summary: dict[str, Any],
    excluded_ids: set[str],
) -> None:
    for asset in _sequence(summary.get("assetCandidates")):
        if isinstance(asset, dict) and asset.get("id") in excluded_ids:
            problems.append(f"assetCandidates includes excluded node id: {asset['id']}")
    for collection_name in ("flowEdges", "flowInteractions"):
        for item in _sequence(summary.get(collection_name)):
            if isinstance(item, dict) and item.get("fromNodeId") in excluded_ids:
                problems.append(
                    f"{collection_name} includes excluded source node id: {item['fromNodeId']}"
                )


def _validate_components_and_text(
    problems: list[str],
    summary: dict[str, Any],
    strict_visibility: bool,
    excluded_ids: set[str],
) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    for index, component in enumerate(_sequence(summary.get("components"))):
        if not isinstance(component, dict):
            continue
        instance_node_ids = component.get("instanceNodeIds")
        if strict_visibility:
            require(
                isinstance(instance_node_ids, list)
                and all(isinstance(node_id, str) and bool(node_id) for node_id in instance_node_ids),
                f"components[{index}].instanceNodeIds is not a list of ids",
            )
        leaked = sorted(
            {node_id for node_id in _sequence(instance_node_ids) if isinstance(node_id, str)}
            & excluded_ids
        )
        if leaked:
            problems.append(
                f"components[{index}].instanceNodeIds includes excluded node ids: {', '.join(leaked)}"
            )
    for index, blueprint in enumerate(_sequence(summary.get("componentBlueprints"))):
        if not isinstance(blueprint, dict):
            problems.append(f"componentBlueprints[{index}] is not an object")
            continue
        require(bool(blueprint.get("componentId")), f"componentBlueprints[{index}].componentId missing")
        require(
            isinstance(blueprint.get("structure"), list),
            f"componentBlueprints[{index}].structure not a list",
        )
    for index, style in enumerate(_sequence(summary.get("textStyles"))):
        if not isinstance(style, dict):
            problems.append(f"textStyles[{index}] is not an object")
            continue
        size = style.get("fontSize")
        if size is not None:
            require(_is_number(size) and size > 0, f"textStyles[{index}].fontSize invalid: {size!r}")


def validate_summary(summary: Any) -> list[str]:
    """Return invariant violations without raising on malformed JSON shapes."""
    if not isinstance(summary, dict):
        return ["summary is not an object"]
    problems: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    schema_version = summary.get("schemaVersion")
    if schema_version is not None:
        require(
            isinstance(schema_version, int) and not isinstance(schema_version, bool) and schema_version >= 1,
            f"schemaVersion invalid: {schema_version!r}",
        )
    strict_visibility = isinstance(schema_version, int) and schema_version >= 4

    for key in _REQUIRED_TOP_KEYS:
        require(key in summary, f"missing top-level key: {key}")
    if strict_visibility:
        require("implementationInventory" in summary, "missing top-level key: implementationInventory")
    for key in _LIST_KEYS:
        if key in summary:
            require(isinstance(summary[key], list), f"{key} is not a list")
    for key in ("meta", "designTokens", "layoutMetrics"):
        if key in summary:
            require(isinstance(summary[key], dict), f"{key} is not an object")
    if "implementationInventory" in summary:
        require(
            isinstance(summary["implementationInventory"], dict),
            "implementationInventory is not an object",
        )

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

    layout_node_ids, effective_rendered_ids, effective_excluded_ids = _validate_layout_nodes(
        problems,
        _sequence(summary.get("layoutNodes")),
        strict_visibility,
    )

    _validate_identified_items(problems, summary, "assetCandidates", "id")
    _validate_identified_items(problems, summary, "components", "componentId", "usageCount")
    _validate_identified_items(problems, summary, "assetInventory", "dedupKey", "usageCount")
    excluded_inventory_ids = _validate_implementation_inventory(
        problems,
        _mapping(summary.get("implementationInventory")),
        strict_visibility,
        layout_node_ids,
        effective_rendered_ids,
        effective_excluded_ids,
    )
    _validate_excluded_worklist_leaks(problems, summary, excluded_inventory_ids)
    _validate_components_and_text(
        problems,
        summary,
        strict_visibility,
        excluded_inventory_ids,
    )

    require("variables" in _mapping(summary.get("designTokens")), "designTokens.variables missing")
    return problems


def _validate_rendered_paints(
    problems: list[str],
    node: dict[str, Any],
    node_index: int,
) -> None:
    paint_stack = node.get("renderedPaints")
    if paint_stack is None:
        return
    if not isinstance(paint_stack, dict):
        problems.append(f"layoutNodes[{node_index}].renderedPaints is not an object")
        return
    for field, paints in paint_stack.items():
        if not isinstance(paints, list):
            problems.append(f"layoutNodes[{node_index}].renderedPaints.{field} is not a list")
            continue
        for paint_index, paint in enumerate(paints):
            prefix = f"layoutNodes[{node_index}].renderedPaints.{field}[{paint_index}]"
            if not isinstance(paint, dict):
                problems.append(f"{prefix} is not an object")
                continue
            if not paint.get("type"):
                problems.append(f"{prefix}.type missing")
            hex_value = paint.get("hex")
            if hex_value is not None and not (
                isinstance(hex_value, str) and bool(_HEX_RE.match(hex_value))
            ):
                problems.append(f"{prefix}.hex invalid: {hex_value!r}")
