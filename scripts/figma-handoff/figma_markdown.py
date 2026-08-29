from __future__ import annotations

from typing import Any, Iterable

__all__ = ["render_markdown"]


def _format_effect_list(effects: list[dict[str, Any]], fallback: str = "(no details)") -> str:
    parts = []
    for effect in effects:
        effect_type = effect.get("type", "")
        if effect_type in {"DROP_SHADOW", "INNER_SHADOW"}:
            parts.append(
                f"{effect_type}({effect.get('color') or '?'} offset={effect.get('offsetX')},{effect.get('offsetY')} "
                f"r={effect.get('radius')})"
            )
        else:
            parts.append(f"{effect_type}(r={effect.get('radius')})")
    return " ".join(parts) if parts else fallback


def _format_gradient(gradient: dict[str, Any]) -> str:
    stops = " -> ".join(f"{stop.get('hex') or '?'}@{stop.get('position')}" for stop in gradient.get("stops", []))
    handles = " -> ".join(f"{handle.get('x')},{handle.get('y')}" for handle in gradient.get("handlePositions", []))
    angle = gradient.get("angleDegrees")
    details = f" angle={angle}deg" if angle is not None else ""
    details += f" handles={handles}" if handles else ""
    return f"{gradient.get('type', '')}({stops}{details})" if stops else str(gradient.get("type", ""))


def _format_interaction(interaction: dict[str, Any]) -> str:
    trigger = interaction.get("triggerType") or "trigger?"
    action = interaction.get("actionType") or "action?"
    navigation = f"/{interaction['navigation']}" if interaction.get("navigation") else ""
    destination = interaction.get("toNodeId")
    target = ""
    if destination:
        target_name = f" {interaction.get('toName')}" if interaction.get("toName") else ""
        target = f" -> `{destination}`{target_name}"
    transition = interaction.get("transition") if isinstance(interaction.get("transition"), dict) else {}
    bits = [str(value) for value in (transition.get("type"), transition.get("easingType")) if value]
    if transition.get("durationSeconds") is not None:
        bits.insert(1, f"{transition['durationSeconds']}s")
    transition_text = f" ({', '.join(bits)})" if bits else ""
    source = " [transitionNodeID]" if interaction.get("destinationSource") == "transitionNodeID" else ""
    return f"`{interaction['fromNodeId']}` {interaction.get('fromName', '')} {trigger} {action}{navigation}{target}{transition_text}{source}"


def _line_height(style: dict[str, Any]) -> tuple[Any, str]:
    if style.get("lineHeightPx") is not None:
        return style["lineHeightPx"], str(style.get("lineHeightUnit", ""))
    if style.get("lineHeightPercentFontSize") is not None:
        return style["lineHeightPercentFontSize"], "FONT_SIZE_%"
    if style.get("lineHeightPercent") is not None:
        return style["lineHeightPercent"], "PERCENT"
    return None, str(style.get("lineHeightUnit", ""))


def _format_text_style(style: dict[str, Any]) -> str:
    family = style.get("fontFamily") or style.get("fontPostScriptName")
    if not family:
        return " (font information unavailable)"
    line_height, unit = _line_height(style)
    spacing = style.get("letterSpacing")
    spacing_text = f" ls={spacing}({style.get('letterSpacingUnit', '')})" if spacing is not None else ""
    return f" {family} {style.get('fontWeight')} {style.get('fontSize')}px lh={line_height}({unit}){spacing_text}"


def _format_variable_value(value: Any) -> str:
    if isinstance(value, dict) and value.get("hex"):
        return str(value["hex"])
    if isinstance(value, dict) and value.get("alias"):
        resolved = f" = {value['resolvedHex']}" if value.get("resolvedHex") else ""
        return f"-> {value.get('aliasName') or value.get('alias')}{resolved}"
    return str(value)


def _named_color_row(style: dict[str, Any]) -> str:
    values = [*(f"`{value}`" for value in style.get("hexValues", [])), *(_format_gradient(value) for value in style.get("gradientValues", []))]
    details = f" {' '.join(values)}" if values else " (color details unavailable)"
    description = f" — {style['description']}" if style.get("description") else ""
    return f"- `{style['name']}`{details}{description}"


def _referenced_color_row(style: dict[str, Any]) -> str:
    values = [*(f"`{value}`" for value in style.get("hexValues", [])), *(_format_gradient(value) for value in style.get("gradientValues", []))]
    if not values and style.get("hex"):
        values.append(f"`{style['hex']}`")
    if not values and style.get("gradient"):
        values.append(_format_gradient(style["gradient"]))
    details = f" {' '.join(values)}" if values else " (color details unavailable)"
    return f"- `{style['name']}`{details}{' [remote]' if style.get('remote') else ''}"


def _text_candidate_row(style: dict[str, Any]) -> str:
    family = style.get("fontFamily") or style.get("fontPostScriptName") or "unknown"
    line_height, unit = _line_height(style)
    spacing = style.get("letterSpacing")
    spacing_text = f" letterSpacing={spacing}({style.get('letterSpacingUnit', '')})" if spacing is not None else ""
    samples = " / ".join(style.get("samples", [])[:2])
    return (
        f"- `{family}` size={style.get('fontSize')} weight={style.get('fontWeight')} "
        f"lineHeight={line_height}({unit}){spacing_text} align={style.get('textAlignHorizontal', '')} "
        f"x{style['count']} ({samples})"
    )


def _text_run_row(run: dict[str, Any]) -> str:
    text = str(run.get("text", "")).replace("\n", " ")[:60]
    range_info = run.get("range", {})
    return (
        f"- `{run['nodeId']}` {run.get('nodeName', '')} {range_info.get('start')}..{range_info.get('end')} "
        f"`{text}`{_format_text_style(run.get('resolvedStyle', {}))}"
    )


def _format_layout_node(node: dict[str, Any]) -> str:
    fields = (
        "layoutMode", "layoutWrap", "layoutPositioning", "layoutAlign", "layoutGrow",
        "primaryAxisSizingMode", "counterAxisSizingMode", "itemSpacing", "opacity", "rotation",
        "strokeWeight", "strokeAlign",
    )
    details = " ".join(f"{key}={node[key]}" for key in fields if node.get(key) is not None)
    paint_details = _format_rendered_paints(node.get("renderedPaints", {}))
    if paint_details:
        details = " ".join(part for part in (details, paint_details) if part)
    parent = f" parent=`{node['parentId']}`" if node.get("parentId") else ""
    return f"`{node['id']}` {node.get('name', '')} ({node.get('type', '')}){parent}{' ' + details if details else ''}"


def _format_rendered_paints(paint_stack: dict[str, Any]) -> str:
    fields: list[str] = []
    for field, paints in paint_stack.items():
        if not isinstance(paints, list):
            continue
        values: list[str] = []
        for paint in paints:
            if not isinstance(paint, dict):
                continue
            if paint.get("hex"):
                values.append(str(paint["hex"]))
            elif isinstance(paint.get("gradient"), dict):
                values.append(_format_gradient(paint["gradient"]))
            else:
                values.append(str(paint.get("type", "")))
        if values:
            fields.append(f"{field}=[{'; '.join(values)}]")
    return " ".join(fields)


def _format_excluded_node(node: dict[str, Any]) -> str:
    reasons = ", ".join(str(reason) for reason in node.get("reasons", [])) or "reason unavailable"
    return f"- `{node.get('id', '')}` {node.get('name', '')} ({node.get('type', '')}) — {reasons}"


def _format_layout_metric(key: str, values: list[dict[str, Any]]) -> str:
    value_text = ", ".join("{}({})".format(item["value"], item["count"]) for item in values[:10])
    return f"- {key}: {value_text}"


def _section(lines: list[str], title: str, rows: Iterable[str], empty: str = "- None") -> None:
    rendered = list(rows)
    lines.extend(["", f"## {title}", "", *(rendered or [empty])])


def _render_visibility_gate(lines: list[str], summary: dict[str, Any]) -> None:
    inventory = summary.get("implementationInventory")
    if not isinstance(inventory, dict):
        _section(
            lines,
            "Implementation Visibility Gate",
            (),
            "- Legacy summary without an implementation inventory. Resolve node and ancestor visibility from `layoutNodes` and the rendered frame before implementation.",
        )
        return

    rendered_node_ids = inventory.get("renderedNodeIds", [])
    excluded_nodes = inventory.get("excludedNodes", [])
    lines.extend([
        "",
        "## Implementation Visibility Gate",
        "",
        f"- Implement only the {len(rendered_node_ids)} nodes in `implementationInventory.renderedNodeIds`.",
        f"- Do not implement the {len(excluded_nodes)} nodes listed under `excludedNodes`, including their controls, callbacks, actions, assets, or styles.",
        "- A listed component or raw layout node is not implementation evidence unless it is effectively visible in the rendered state.",
    ])
    _section(
        lines,
        "Do Not Implement — Excluded Nodes",
        (_format_excluded_node(node) for node in excluded_nodes),
    )


def _render_implementation_checklist(lines: list[str]) -> None:
    lines.extend([
        "", "## Platform-neutral Implementation Checklist", "",
        "- Read the target repository's instructions, screen entry points, navigation, and state ownership first.",
        "- Start from `implementationInventory.renderedNodeIds`; never implement a node in `excludedNodes`.",
        "- Map each visible node's exact `renderedPaints` to the target product's tokens. A nearby token is valid only when it reproduces the same paint stack.",
        "- Implement reusable components from `componentBlueprints` and `components` first.",
        "- Use the full-frame image only as a comparison reference; implement the actual structure and individual assets.",
        "- Before completion, compare visible controls and emitted actions in both directions and require zero unmatched implementation items.",
        "- Follow the target repository's current accessibility, responsive behavior, tests, and preview rules.",
        "", "## Missing State Log", "", "- Add states that Figma does not specify to this section during implementation.",
    ])


def render_markdown(summary: dict[str, Any]) -> str:
    meta = summary["meta"]
    lines = [
        "# Figma Handoff", "",
        "This file is a shared implementation reference generated from the Figma REST API. It is not an automatic conversion; it gives iOS and Android implementers a common view of the screen structure and token candidates.",
        "", "## Source", "",
        f"- fileKey: `{meta['fileKey']}`", f"- startNodeId: `{meta['startNodeId']}`", f"- generatedAt: `{meta['generatedAt']}`",
    ]
    if meta.get("sourceUrl"):
        lines.append(f"- sourceUrl: {meta['sourceUrl']}")

    def screen_row(screen: dict[str, Any]) -> str:
        size = f" / {screen['width']}x{screen['height']}" if screen.get("width") is not None and screen.get("height") is not None else ""
        image = f" / image: `{screen['imagePath']}`" if screen.get("imagePath") else ""
        return f"- `{screen['id']}` {screen.get('name', '')} ({screen.get('type', '')}{size}){image}"

    _section(lines, "Screens", (screen_row(screen) for screen in summary["screens"]))
    _render_visibility_gate(lines, summary)
    _section(
        lines, "Prototype Flow Edges",
        (f"- `{edge['fromNodeId']}` {edge.get('fromName', '')} -> `{edge['toNodeId']}`{' ' + edge['toName'] if edge.get('toName') else ''}" for edge in summary["flowEdges"]),
        "- No prototype transition was found in the Figma JSON. The prototype may have no connection or the API payload may not include it.",
    )
    interactions = summary.get("flowInteractions", [])
    interaction_rows = [f"- {_format_interaction(item)}" for item in interactions[:120]]
    if len(interactions) > 120:
        interaction_rows.append(f"- ... and {len(interactions) - 120} more")
    _section(lines, "Prototype Interaction Details", interaction_rows)

    tokens = summary.get("designTokens", {})
    _section(lines, "Design Tokens — Color Styles", (_named_color_row(style) for style in tokens.get("colorStyles", [])))
    _section(lines, "Design Tokens — Text Styles", (
        f"- `{style['name']}`{_format_text_style(style)}{' — ' + style['description'] if style.get('description') else ''}"
        for style in tokens.get("textStyles", [])
    ))
    _section(lines, "Design Tokens — Effect Styles", (
        f"- `{style['name']}` {_format_effect_list(style.get('effects', []))}{' — ' + style['description'] if style.get('description') else ''}"
        for style in tokens.get("effectStyles", [])
    ))
    variable_data = tokens.get("variables", {})
    collection_names = {item.get("id", ""): item.get("name", "") for item in variable_data.get("collections", [])}
    variables = variable_data.get("variables", [])
    variable_rows = []
    for variable in variables[:60]:
        modes = variable.get("valuesByMode", {})
        value = next(iter(modes.values()), "") if modes else ""
        name = f"{collection_names.get(variable.get('collectionId', ''), '')}/{variable['name']}"
        variable_rows.append(f"- `{name}` ({variable.get('resolvedType', '')}) = {_format_variable_value(value)}")
    if len(variables) > 60:
        variable_rows.append(f"- ... and {len(variables) - 60} more (see raw/variables.json)")
    _section(lines, "Design Tokens — Variables", variable_rows)

    referenced = summary.get("referencedStyles", {})
    _section(lines, "Referenced Color Styles (from node payload)", (_referenced_color_row(style) for style in referenced.get("colorStyles", [])))
    _section(lines, "Referenced Text Styles (from node payload)", (f"- `{style['name']}`{_format_text_style(style)}{' [remote]' if style.get('remote') else ''}" for style in referenced.get("textStyles", [])))
    _section(lines, "Referenced Effect Styles (from node payload)", (f"- `{style['name']}` {_format_effect_list(style.get('effects', []))}{' [remote]' if style.get('remote') else ''}" for style in referenced.get("effectStyles", [])))

    components = summary.get("components", [])
    component_rows = []
    for component in components[:60]:
        variants = component.get("variantProperties") or {}
        variant_text = f" [{', '.join(f'{key}={value}' for key, value in variants.items())}]" if variants else ""
        label = component.get("componentSetName") or component.get("name", "")
        component_rows.append(f"- `{component['componentId']}` {label}{variant_text} x{component['usageCount']} ({len(component.get('usedInScreens', []))} screens)")
    _section(lines, "Components (usage order — rendered implementation work list)", component_rows, "- None (no visible instances or component definitions in the payload)")

    blueprint_rows = []
    for blueprint in summary.get("componentBlueprints", [])[:8]:
        size = blueprint.get("size") or {}
        size_text = f" {size.get('w')}x{size.get('h')}" if size else ""
        blueprint_rows.append(f"- `{blueprint['componentId']}` **{blueprint.get('name', '')}**{size_text} x{blueprint['usageCount']}")
        for item in blueprint.get("structure", [])[:24]:
            indent = "  " * item.get("depth", 1)
            reference = f" → comp `{item['componentId']}`" if item.get("componentId") else ""
            asset = f" [asset {item['assetDedupKey'][:14]}]" if item.get("assetDedupKey") else ""
            text = f" \"{item['text']}\"" if item.get("text") else ""
            dims = f" {item['w']}x{item['h']}" if item.get("w") is not None and item.get("h") is not None else ""
            blueprint_rows.append(f"  {indent}- {item.get('name', '')} ({item.get('type', '')}){dims}{reference}{asset}{text}")
    _section(lines, "Component Blueprints (internal structure — assemble from this)", blueprint_rows)

    _section(lines, "Rendered Color Candidates (usage order)", (
        f"- `{color['hex']}` x{color['count']}{' [var: ' + (color.get('boundVariableNames') or color.get('boundVariableIds'))[0] + ']' if (color.get('boundVariableNames') or color.get('boundVariableIds')) else ''} ({', '.join(color.get('sources', [])[:3])})"
        for color in summary["colors"][:20]
    ))
    _section(lines, "Gradient Candidates (rendered nodes only)", (f"- {_format_gradient(item)} x{item['count']} ({', '.join(item.get('sources', [])[:3])})" for item in summary.get("gradients", [])[:20]))
    _section(lines, "Text Style Candidates (usage order)", (_text_candidate_row(style) for style in summary["textStyles"][:20]))
    _section(lines, "Text Override Runs", (_text_run_row(run) for run in summary.get("textRuns", [])[:60]))
    _section(lines, "Effect Candidates", (f"- {_format_effect_list([effect])} x{effect['count']} ({', '.join(effect.get('sources', [])[:2])})" for effect in summary.get("effects", [])[:20]))
    _section(lines, "Layout Metric Candidates", (_format_layout_metric(key, values) for key, values in summary["layoutMetrics"].items()))
    rendered_layout_nodes = [
        node
        for node in summary.get("layoutNodes", [])
        if node.get("effectiveVisible") is not False
    ]
    _section(
        lines,
        "Rendered Layout Nodes (implementation allowlist)",
        (f"- {_format_layout_node(node)}" for node in rendered_layout_nodes[:120]),
    )
    _section(lines, "Unique Icon Inventory (deduplication — avoid duplicate implementations)", (
        f"- {item.get('name', '')}{' (component: ' + item['nearestComponentName'] + ')' if item.get('nearestComponentName') else ''} ({item.get('type', '')}) x{item['usageCount']}{' ⚠️name unclear' if item.get('nameUnclear') else ''}"
        for item in summary.get("assetInventory", [])[:60]
    ))
    _section(lines, "Rendered Asset Candidates", (
        f"- `{asset['id']}` {asset.get('name', '')} ({asset.get('type', '')})"
        f"{' [component: ' + asset['nearestComponentName'] + ']' if asset.get('nearestComponentName') else ''}"
        for asset in summary["assetCandidates"][:50]
    ))
    _render_implementation_checklist(lines)
    _section(lines, "Warnings", (f"- {warning}" for warning in summary["warnings"])) if summary["warnings"] else None
    return "\n".join(lines) + "\n"
