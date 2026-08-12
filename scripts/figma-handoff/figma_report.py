from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

from figma_analyze import (
    build_asset_inventory,
    summarize_asset_candidates,
    summarize_colors,
    summarize_component_blueprints,
    summarize_components,
    summarize_effects,
    summarize_flow_interactions,
    summarize_gradients,
    summarize_layout_metrics,
    summarize_layout_nodes,
    summarize_text_styles,
    summarize_text_runs,
)
from figma_parse import (
    parse_named_color_styles,
    parse_named_effect_styles,
    parse_named_text_styles,
    parse_variables,
    build_referenced_styles,
)
from figma_util import iter_nodes, normalize_node_id, round_number


def build_summary(
    file_key: str,
    start_node_id: str,
    source_url: str | None,
    node_documents: dict[str, dict[str, Any]],
    flow_edges: list[dict[str, str]],
    image_paths: dict[str, str],
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
    variables: dict[str, Any],
    file_styles: dict[str, dict[str, Any]],
    warnings: list[str],
    component_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _seen_node_ids: set[str] = set()
    all_nodes: list[dict[str, Any]] = []
    for document in node_documents.values():
        for node in iter_nodes(document):
            nid = normalize_node_id(str(node.get("id", "")))
            if nid and nid not in _seen_node_ids:
                _seen_node_ids.add(nid)
                all_nodes.append(node)

    node_name_by_id = {
        normalize_node_id(str(node.get("id", ""))): str(node.get("name", ""))
        for node in all_nodes
        if node.get("id")
    }

    screens = []
    for node_id, document in node_documents.items():
        bounds = document.get("absoluteBoundingBox") or {}
        screens.append(
            {
                "id": node_id,
                "name": document.get("name", ""),
                "type": document.get("type", ""),
                "width": round_number(bounds.get("width")),
                "height": round_number(bounds.get("height")),
                "imagePath": image_paths.get(node_id),
            }
        )

    parsed_variables = parse_variables(variables)
    flow_interactions = [
        {
            **interaction,
            "toName": node_name_by_id.get(interaction.get("toNodeId", ""), ""),
        }
        for interaction in summarize_flow_interactions(all_nodes)
    ]

    components = summarize_components(node_documents, component_index)
    component_label = {
        comp["componentId"]: (comp.get("componentSetName") or comp.get("name") or "")
        for comp in components
    }
    asset_candidates = _asset_candidates_with_fallback(all_nodes, node_documents, component_label)
    asset_dedup_by_id = {
        candidate["id"]: candidate["dedupKey"]
        for candidate in asset_candidates
        if candidate.get("id") and candidate.get("dedupKey")
    }

    return {
        "meta": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "fileKey": file_key,
            "startNodeId": start_node_id,
            "sourceUrl": source_url,
        },
        "screens": screens,
        "flowEdges": [
            {
                **edge,
                "toName": node_name_by_id.get(edge["toNodeId"], ""),
            }
            for edge in flow_edges
        ],
        "flowInteractions": flow_interactions,
        "designTokens": {
            "colorStyles": parse_named_color_styles(named_styles, style_node_details),
            "textStyles": parse_named_text_styles(named_styles, style_node_details),
            "effectStyles": parse_named_effect_styles(named_styles, style_node_details),
            "variables": parsed_variables,
        },
        "referencedStyles": build_referenced_styles(file_styles, node_documents),
        "components": components,
        "componentBlueprints": summarize_component_blueprints(node_documents, components, asset_dedup_by_id),
        "colors": summarize_colors(all_nodes, parsed_variables),
        "gradients": summarize_gradients(all_nodes),
        "textStyles": summarize_text_styles(all_nodes),
        "textRuns": summarize_text_runs(all_nodes),
        "effects": summarize_effects(all_nodes),
        "layoutMetrics": summarize_layout_metrics(all_nodes),
        "layoutNodes": summarize_layout_nodes(list(node_documents.values())),
        "assetCandidates": asset_candidates,
        "assetInventory": build_asset_inventory(asset_candidates),
        "warnings": warnings,
    }

def _asset_candidates_with_fallback(
    all_nodes: list[dict[str, Any]],
    node_documents: dict[str, dict[str, Any]],
    component_label: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """asset 후보에 조상 폴백 체인 + 가장 가까운 컴포넌트 이름을 붙인다.

    깊이 중첩된 아이콘 노드는 단독 렌더가 null이지만, 조상 컨테이너를 위로 올라가면
    렌더되는 노드가 나온다. render 단계에서 후보가 null이면 이 체인을 순서대로 시도한다.
    화면 프레임(node_documents 키)은 전체 화면이라 폴백 대상에서 제외한다.

    또한 이름 없는 벡터라도 대개 이름 있는 컴포넌트(`Icon/Search`) 안에 있으므로,
    조상 인스턴스의 componentId를 찾아 `nearestComponentName`을 backfill한다.
    """
    component_label = component_label or {}
    parent_by_id: dict[str, str | None] = {}
    name_by_id: dict[str, str] = {}
    component_by_id: dict[str, str] = {}

    def walk(node: dict[str, Any], parent_id: str | None) -> None:
        node_id = normalize_node_id(str(node.get("id", "")))
        current = node_id or parent_id
        if node_id:
            parent_by_id[node_id] = parent_id
            name_by_id[node_id] = str(node.get("name", ""))
            component_id = node.get("componentId")
            if isinstance(component_id, str) and component_id:
                component_by_id[node_id] = normalize_node_id(component_id)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child, current)

    for document in node_documents.values():
        walk(document, None)

    def nearest_component_name(candidate_id: str) -> str:
        cursor: str | None = candidate_id
        depth = 0
        while cursor is not None and depth < 8:
            component_id = component_by_id.get(cursor)
            if component_id:
                return component_label.get(component_id, "")
            cursor = parent_by_id.get(cursor)
            depth += 1
        return ""

    screen_ids = set(node_documents.keys())
    candidates = summarize_asset_candidates(all_nodes)
    max_ancestor_depth = 3
    for candidate in candidates:
        candidate_id = candidate.get("id", "")
        chain: list[dict[str, str]] = []
        cursor = parent_by_id.get(candidate_id)
        depth = 0
        while cursor is not None and depth < max_ancestor_depth:
            if cursor not in screen_ids:
                chain.append({"id": cursor, "name": name_by_id.get(cursor, cursor)})
            cursor = parent_by_id.get(cursor)
            depth += 1
        if chain:
            candidate["renderFallbackIds"] = chain
        nearest_name = nearest_component_name(candidate_id)
        if nearest_name:
            candidate["nearestComponentName"] = nearest_name
    return candidates

def _format_effect_list(effects: list[dict[str, Any]], fallback: str = "(상세 없음)") -> str:
    parts: list[str] = []
    for eff in effects:
        eff_type = eff.get("type", "")
        if eff_type in {"DROP_SHADOW", "INNER_SHADOW"}:
            color_str = eff.get("color") or "?"
            parts.append(
                f"{eff_type}({color_str} offset={eff.get('offsetX')},{eff.get('offsetY')} r={eff.get('radius')})"
            )
        else:
            parts.append(f"{eff_type}(r={eff.get('radius')})")
    return " ".join(parts) if parts else fallback

def _format_gradient(gradient: dict[str, Any]) -> str:
    stops = " -> ".join(
        f"{stop.get('hex') or '?'}@{stop.get('position')}"
        for stop in gradient.get("stops", [])
    )
    handles = " -> ".join(
        f"{handle.get('x')},{handle.get('y')}"
        for handle in gradient.get("handlePositions", [])
    )
    handle_part = f" handles={handles}" if handles else ""
    angle = gradient.get("angleDegrees")
    angle_part = f" angle={angle}deg" if angle is not None else ""
    return f"{gradient.get('type', '')}({stops}{angle_part}{handle_part})" if stops else str(gradient.get("type", ""))


def _format_interaction(interaction: dict[str, Any]) -> str:
    trigger = interaction.get("triggerType") or "trigger?"
    action = interaction.get("actionType") or "action?"
    navigation = f"/{interaction.get('navigation')}" if interaction.get("navigation") else ""
    destination = interaction.get("toNodeId")
    to_part = ""
    if destination:
        to_name = f" {interaction.get('toName')}" if interaction.get("toName") else ""
        to_part = f" -> `{destination}`{to_name}"
    transition = interaction.get("transition") if isinstance(interaction.get("transition"), dict) else {}
    transition_bits = []
    if transition.get("type"):
        transition_bits.append(str(transition["type"]))
    if transition.get("durationSeconds") is not None:
        transition_bits.append(f"{transition['durationSeconds']}s")
    if transition.get("easingType"):
        transition_bits.append(str(transition["easingType"]))
    transition_part = f" ({', '.join(transition_bits)})" if transition_bits else ""
    source = f" [{interaction.get('destinationSource')}]" if interaction.get("destinationSource") == "transitionNodeID" else ""
    return (
        f"`{interaction['fromNodeId']}` {interaction.get('fromName', '')} "
        f"{trigger} {action}{navigation}{to_part}{transition_part}{source}"
    )


def _format_text_style_inline(style: dict[str, Any]) -> str:
    family = style.get("fontFamily") or style.get("fontPostScriptName")
    if not family:
        return " (font 정보 없음)"
    line_height, line_height_unit = _text_style_line_height(style)
    letter_spacing = style.get("letterSpacing")
    letter_unit = style.get("letterSpacingUnit", "")
    letter_part = f" ls={letter_spacing}({letter_unit})" if letter_spacing is not None else ""
    return (
        f" {family} {style.get('fontWeight')} {style.get('fontSize')}px"
        f" lh={line_height}({line_height_unit}){letter_part}"
    )

def _text_style_line_height(style: dict[str, Any]) -> tuple[Any, str]:
    if style.get("lineHeightPx") is not None:
        return style.get("lineHeightPx"), str(style.get("lineHeightUnit", ""))
    if style.get("lineHeightPercentFontSize") is not None:
        return style.get("lineHeightPercentFontSize"), "FONT_SIZE_%"
    if style.get("lineHeightPercent") is not None:
        return style.get("lineHeightPercent"), "PERCENT"
    return None, str(style.get("lineHeightUnit", ""))

def _format_variable_value(value: Any) -> str:
    if isinstance(value, dict) and value.get("hex"):
        return str(value["hex"])
    if isinstance(value, dict) and value.get("alias"):
        alias_name = value.get("aliasName") or value.get("alias")
        resolved = f" = {value['resolvedHex']}" if value.get("resolvedHex") else ""
        return f"-> {alias_name}{resolved}"
    return str(value)

def _format_layout_node(node: dict[str, Any]) -> str:
    pieces = []
    for key in (
        "layoutMode",
        "layoutWrap",
        "layoutPositioning",
        "layoutAlign",
        "layoutGrow",
        "primaryAxisSizingMode",
        "counterAxisSizingMode",
        "itemSpacing",
        "opacity",
        "rotation",
        "strokeWeight",
        "strokeAlign",
    ):
        if node.get(key) is not None:
            pieces.append(f"{key}={node[key]}")
    parent = f" parent=`{node['parentId']}`" if node.get("parentId") else ""
    detail = " ".join(pieces)
    detail_part = f" {detail}" if detail else ""
    return f"`{node['id']}` {node.get('name', '')} ({node.get('type', '')}){parent}{detail_part}"

def render_markdown(summary: dict[str, Any]) -> str:
    meta = summary["meta"]
    lines: list[str] = [
        "# Figma Handoff",
        "",
        "이 파일은 Figma REST API로 생성한 공통 구현 기준입니다. 자동 변환 결과가 아니라 iOS/Android 구현자가 같은 화면 구조와 토큰 후보를 보도록 만드는 handoff 산출물입니다.",
        "",
        "## Source",
        "",
        f"- fileKey: `{meta['fileKey']}`",
        f"- startNodeId: `{meta['startNodeId']}`",
        f"- generatedAt: `{meta['generatedAt']}`",
    ]
    if meta.get("sourceUrl"):
        lines.append(f"- sourceUrl: {meta['sourceUrl']}")

    lines.extend(["", "## Screens", ""])
    for screen in summary["screens"]:
        size = ""
        if screen.get("width") is not None and screen.get("height") is not None:
            size = f" / {screen['width']}x{screen['height']}"
        image = f" / image: `{screen['imagePath']}`" if screen.get("imagePath") else ""
        lines.append(f"- `{screen['id']}` {screen.get('name', '')} ({screen.get('type', '')}{size}){image}")

    lines.extend(["", "## Prototype Flow Edges", ""])
    if summary["flowEdges"]:
        for edge in summary["flowEdges"]:
            to_name = f" {edge['toName']}" if edge.get("toName") else ""
            lines.append(f"- `{edge['fromNodeId']}` {edge.get('fromName', '')} -> `{edge['toNodeId']}`{to_name}")
    else:
        lines.append("- Figma JSON에서 prototype transition을 찾지 못했습니다. prototype 연결이 없거나 API payload에 포함되지 않은 경우일 수 있습니다.")

    lines.extend(["", "## Prototype Interaction Details", ""])
    if summary.get("flowInteractions"):
        for interaction in summary["flowInteractions"][:120]:
            lines.append(f"- {_format_interaction(interaction)}")
        if len(summary["flowInteractions"]) > 120:
            lines.append(f"- ... 외 {len(summary['flowInteractions']) - 120}개")
    else:
        lines.append("- 없음")

    tokens = summary.get("designTokens", {})

    lines.extend(["", "## Design Tokens — Color Styles", ""])
    color_styles = tokens.get("colorStyles", [])
    if color_styles:
        for s in color_styles:
            desc = f" — {s['description']}" if s.get("description") else ""
            hexes = " ".join(f"`{h}`" for h in s.get("hexValues", []))
            gradients = "; ".join(_format_gradient(g) for g in s.get("gradientValues", []))
            color_parts = " ".join(part for part in (hexes, gradients) if part)
            color_part = f" {color_parts}" if color_parts else " (색상 상세 없음)"
            lines.append(f"- `{s['name']}`{color_part}{desc}")
    else:
        lines.append("- 없음 (파일에 named color style이 없거나 API 접근 불가)")

    lines.extend(["", "## Design Tokens — Text Styles", ""])
    text_styles_named = tokens.get("textStyles", [])
    if text_styles_named:
        for s in text_styles_named:
            desc = f" — {s['description']}" if s.get("description") else ""
            font_part = _format_text_style_inline(s)
            lines.append(f"- `{s['name']}`{font_part}{desc}")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Design Tokens — Effect Styles", ""])
    effect_styles = tokens.get("effectStyles", [])
    if effect_styles:
        for s in effect_styles:
            desc = f" — {s['description']}" if s.get("description") else ""
            lines.append(f"- `{s['name']}` {_format_effect_list(s.get('effects', []))}{desc}")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Design Tokens — Variables", ""])
    var_data = tokens.get("variables", {})
    all_vars = var_data.get("variables", [])
    collections = {c.get("id", ""): c.get("name", "") for c in var_data.get("collections", [])}
    if all_vars:
        for var in all_vars[:60]:
            coll_name = collections.get(var.get("collectionId", ""), "")
            resolved_type = var.get("resolvedType", "")
            modes = var.get("valuesByMode", {})
            first_value = next(iter(modes.values()), "") if modes else ""
            display_value = _format_variable_value(first_value)
            lines.append(f"- `{coll_name}/{var['name']}` ({resolved_type}) = {display_value}")
        if len(all_vars) > 60:
            lines.append(f"- ... 외 {len(all_vars) - 60}개 (raw/variables.json 참조)")
    else:
        lines.append("- 없음")

    ref_styles = summary.get("referencedStyles", {})

    ref_colors = ref_styles.get("colorStyles", [])
    lines.extend(["", "## Referenced Color Styles (노드 payload 기준)", ""])
    if ref_colors:
        for s in ref_colors:
            remote_tag = " [remote]" if s.get("remote") else ""
            hexes = " ".join(f"`{h}`" for h in (s.get("hexValues") or []))
            gradients = "; ".join(_format_gradient(g) for g in (s.get("gradientValues") or []))
            color_parts = " ".join(part for part in (hexes, gradients) if part)
            if color_parts:
                color_part = f" {color_parts}"
            elif s.get("hex"):
                color_part = f" `{s['hex']}`"
            elif s.get("gradient"):
                color_part = f" {_format_gradient(s['gradient'])}"
            else:
                color_part = " (색상 상세 없음)"
            lines.append(f"- `{s['name']}`{color_part}{remote_tag}")
    else:
        lines.append("- 없음")

    ref_texts = ref_styles.get("textStyles", [])
    lines.extend(["", "## Referenced Text Styles (노드 payload 기준)", ""])
    if ref_texts:
        for s in ref_texts:
            remote_tag = " [remote]" if s.get("remote") else ""
            font_part = _format_text_style_inline(s)
            lines.append(f"- `{s['name']}`{font_part}{remote_tag}")
    else:
        lines.append("- 없음")

    ref_effects = ref_styles.get("effectStyles", [])
    lines.extend(["", "## Referenced Effect Styles (노드 payload 기준)", ""])
    if ref_effects:
        for s in ref_effects:
            remote_tag = " [remote]" if s.get("remote") else ""
            lines.append(f"- `{s['name']}` {_format_effect_list(s.get('effects', []))}{remote_tag}")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Components (사용 빈도 기준 — 컴포넌트화 work-list)", ""])
    component_catalog = summary.get("components", [])
    if component_catalog:
        for comp in component_catalog[:60]:
            # variant 멤버는 컴포넌트셋 이름이 진짜 이름(name은 variant 문자열)이라 셋 이름을 우선.
            label = comp.get("componentSetName") or comp.get("name", "")
            variant = comp.get("variantProperties") or {}
            variant_part = ""
            if variant:
                variant_bits = ", ".join(f"{k}={v}" for k, v in variant.items())
                variant_part = f" [{variant_bits}]"
            screens = len(comp.get("usedInScreens", []))
            lines.append(
                f"- `{comp['componentId']}` {label}{variant_part}"
                f" x{comp['usageCount']} ({screens}개 화면)"
            )
        if len(component_catalog) > 60:
            lines.append(f"- ... 외 {len(component_catalog) - 60}개")
    else:
        lines.append("- 없음 (인스턴스가 없거나 컴포넌트 정의 payload 미포함)")

    lines.extend(["", "## Component Blueprints (컴포넌트별 내부 구조 — 이대로 조립)", ""])
    blueprints = summary.get("componentBlueprints", [])
    if blueprints:
        for bp in blueprints[:8]:
            size = bp.get("size") or {}
            size_part = f" {size.get('w')}x{size.get('h')}" if size else ""
            lines.append(f"- `{bp['componentId']}` **{bp.get('name', '')}**{size_part} x{bp['usageCount']}")
            for item in bp.get("structure", [])[:24]:
                indent = "  " * item.get("depth", 1)
                ref = f" → comp `{item['componentId']}`" if item.get("componentId") else ""
                asset = f" [asset {item['assetDedupKey'][:14]}]" if item.get("assetDedupKey") else ""
                text = f" \"{item['text']}\"" if item.get("text") else ""
                dims = f" {item['w']}x{item['h']}" if item.get("w") is not None and item.get("h") is not None else ""
                lines.append(f"  {indent}- {item.get('name', '')} ({item.get('type', '')}){dims}{ref}{asset}{text}")
            if len(bp.get("structure", [])) > 24:
                lines.append(f"    - ... 외 {len(bp['structure']) - 24}개 노드")
        if len(blueprints) > 8:
            lines.append(f"- ... 외 {len(blueprints) - 8}개 컴포넌트 (design-summary.json 참조)")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Color Candidates (사용 빈도 기준)", ""])
    for color in summary["colors"][:20]:
        source = ", ".join(color.get("sources", [])[:3])
        var_names = color.get("boundVariableNames", [])
        var_ids = color.get("boundVariableIds", [])
        var_hint_value = var_names[0] if var_names else (var_ids[0] if var_ids else "")
        var_hint = f" [var: {var_hint_value}]" if var_hint_value else ""
        lines.append(f"- `{color['hex']}` x{color['count']}{var_hint} ({source})")
    if not summary["colors"]:
        lines.append("- 없음")

    lines.extend(["", "## Gradient Candidates", ""])
    for gradient in summary.get("gradients", [])[:20]:
        source = ", ".join(gradient.get("sources", [])[:3])
        lines.append(f"- {_format_gradient(gradient)} x{gradient['count']} ({source})")
    if not summary.get("gradients"):
        lines.append("- 없음")

    lines.extend(["", "## Text Style Candidates (사용 빈도 기준)", ""])
    for style in summary["textStyles"][:20]:
        family = style.get("fontFamily") or style.get("fontPostScriptName") or "unknown"
        size = style.get("fontSize")
        line_height, line_height_unit = _text_style_line_height(style)
        weight = style.get("fontWeight")
        align = style.get("textAlignHorizontal", "")
        letter_spacing = style.get("letterSpacing")
        letter_unit = style.get("letterSpacingUnit", "")
        letter_part = f" letterSpacing={letter_spacing}({letter_unit})" if letter_spacing is not None else ""
        samples = " / ".join(style.get("samples", [])[:2])
        lines.append(
            f"- `{family}` size={size} weight={weight} lineHeight={line_height}({line_height_unit})"
            f"{letter_part} align={align} x{style['count']} ({samples})"
        )
    if not summary["textStyles"]:
        lines.append("- 없음")

    lines.extend(["", "## Text Override Runs", ""])
    if summary.get("textRuns"):
        for run in summary["textRuns"][:60]:
            style = _format_text_style_inline(run.get("resolvedStyle", {}))
            text = str(run.get("text", "")).replace("\n", " ")[:60]
            range_info = run.get("range", {})
            lines.append(
                f"- `{run['nodeId']}` {run.get('nodeName', '')} "
                f"{range_info.get('start')}..{range_info.get('end')} `{text}`{style}"
            )
        if len(summary["textRuns"]) > 60:
            lines.append(f"- ... 외 {len(summary['textRuns']) - 60}개")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Effect Candidates", ""])
    for effect in summary.get("effects", [])[:20]:
        detail = _format_effect_list([effect])
        src = ", ".join(effect.get("sources", [])[:2])
        lines.append(f"- {detail} x{effect['count']} ({src})")
    if not summary.get("effects"):
        lines.append("- 없음")

    lines.extend(["", "## Layout Metric Candidates", ""])
    for key, values in summary["layoutMetrics"].items():
        top_values = ", ".join(f"{item['value']}({item['count']})" for item in values[:10])
        lines.append(f"- {key}: {top_values}")
    if not summary["layoutMetrics"]:
        lines.append("- 없음")

    lines.extend(["", "## Layout Nodes", ""])
    if summary.get("layoutNodes"):
        for node in summary["layoutNodes"][:120]:
            lines.append(f"- {_format_layout_node(node)}")
        if len(summary["layoutNodes"]) > 120:
            lines.append(f"- ... 외 {len(summary['layoutNodes']) - 120}개")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Unique Icon Inventory (dedup 기준 — 반복 구현 방지)", ""])
    inventory = summary.get("assetInventory", [])
    if inventory:
        for icon in inventory[:60]:
            near = icon.get("nearestComponentName")
            unclear = " ⚠️이름불명확" if icon.get("nameUnclear") else ""
            near_part = f" (컴포넌트: {near})" if near else ""
            lines.append(
                f"- {icon.get('name', '')}{near_part} ({icon.get('type', '')}) x{icon['usageCount']}{unclear}"
            )
        if len(inventory) > 60:
            lines.append(f"- ... 외 {len(inventory) - 60}개")
    else:
        lines.append("- 없음")

    lines.extend(["", "## Asset Candidates", ""])
    if summary["assetCandidates"]:
        for asset in summary["assetCandidates"][:50]:
            near = f" [컴포넌트: {asset['nearestComponentName']}]" if asset.get("nearestComponentName") else ""
            lines.append(f"- `{asset['id']}` {asset.get('name', '')} ({asset.get('type', '')}){near}")
    else:
        lines.append("- 없음")

    lines.extend(
        [
            "",
            "## Platform-neutral Implementation Checklist",
            "",
            "- 대상 저장소의 지침과 기존 화면 진입점, 내비게이션, 상태 소유권을 먼저 확인합니다.",
            "- Figma 값을 직접 복제하기 전에 대상 제품의 기존 색상·타이포그래피·간격 토큰에 매핑합니다.",
            "- `componentBlueprints`와 `components`를 기준으로 재사용 컴포넌트를 먼저 구현합니다.",
            "- 전체 프레임 이미지는 비교 reference로만 쓰고 실제 UI 구조와 개별 asset으로 구현합니다.",
            "- 접근성, 반응형 동작, 테스트와 preview는 대상 저장소의 현재 규칙을 따릅니다.",
            "",
            "## Missing State Log",
            "",
            "- Figma에 명시되지 않은 상태는 구현 중 이 섹션에 추가합니다.",
        ]
    )

    if summary["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in summary["warnings"]:
            lines.append(f"- {warning}")

    return "\n".join(lines) + "\n"

def build_manifest(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": 3,
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
            "assetCandidateCount": len(summary["assetCandidates"]),
            "assetInventoryCount": len(summary.get("assetInventory", [])),
        },
    }
