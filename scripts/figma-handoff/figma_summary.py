from __future__ import annotations

import datetime as dt
from typing import Any

from figma_asset_analysis import AssetAnalysis
from figma_color_analysis import ColorAnalysis
from figma_component_analysis import ComponentAnalysis
from figma_interaction_analysis import summarize_flow_interactions
from figma_layout_analysis import LayoutAnalysis
from figma_style_parse import StyleParser
from figma_util import iter_nodes, normalize_node_id, round_number
from figma_variable_parse import parse_variables

__all__ = ["build_summary"]


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
    seen_node_ids: set[str] = set()
    all_nodes: list[dict[str, Any]] = []
    for document in node_documents.values():
        for node in iter_nodes(document):
            node_id = normalize_node_id(str(node.get("id", "")))
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                all_nodes.append(node)

    node_names = {
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
    interactions = [
        {**interaction, "toName": node_names.get(interaction.get("toNodeId", ""), "")}
        for interaction in summarize_flow_interactions(all_nodes)
    ]
    components = ComponentAnalysis.summarize_components(node_documents, component_index)
    component_labels = {
        component["componentId"]: component.get("componentSetName") or component.get("name") or ""
        for component in components
    }
    asset_candidates = _asset_candidates_with_fallback(all_nodes, node_documents, component_labels)
    asset_keys = {
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
            {**edge, "toName": node_names.get(edge["toNodeId"], "")}
            for edge in flow_edges
        ],
        "flowInteractions": interactions,
        "designTokens": {
            "colorStyles": StyleParser.parse_named_color_styles(named_styles, style_node_details),
            "textStyles": StyleParser.parse_named_text_styles(named_styles, style_node_details),
            "effectStyles": StyleParser.parse_named_effect_styles(named_styles, style_node_details),
            "variables": parsed_variables,
        },
        "referencedStyles": StyleParser.build_referenced_styles(file_styles, node_documents),
        "components": components,
        "componentBlueprints": ComponentAnalysis.summarize_component_blueprints(node_documents, components, asset_keys),
        "colors": ColorAnalysis.summarize_colors(all_nodes, parsed_variables),
        "gradients": ColorAnalysis.summarize_gradients(all_nodes),
        "textStyles": ColorAnalysis.summarize_text_styles(all_nodes),
        "textRuns": LayoutAnalysis.summarize_text_runs(all_nodes),
        "effects": ColorAnalysis.summarize_effects(all_nodes),
        "layoutMetrics": LayoutAnalysis.summarize_layout_metrics(all_nodes),
        "layoutNodes": LayoutAnalysis.summarize_layout_nodes(list(node_documents.values())),
        "assetCandidates": asset_candidates,
        "assetInventory": AssetAnalysis.build_asset_inventory(asset_candidates),
        "warnings": warnings,
    }


def _asset_candidates_with_fallback(
    all_nodes: list[dict[str, Any]],
    node_documents: dict[str, dict[str, Any]],
    component_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    component_labels = component_labels or {}
    parent_by_id: dict[str, str | None] = {}
    name_by_id: dict[str, str] = {}
    component_by_id: dict[str, str] = {}

    def walk(node: dict[str, Any], parent_id: str | None) -> None:
        node_id = normalize_node_id(str(node.get("id", "")))
        current_id = node_id or parent_id
        if node_id and node_id not in parent_by_id:
            parent_by_id[node_id] = parent_id
            name_by_id[node_id] = str(node.get("name", ""))
            component_id = node.get("componentId")
            if isinstance(component_id, str) and component_id:
                component_by_id[node_id] = normalize_node_id(component_id)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child, current_id)

    for document in node_documents.values():
        walk(document, None)

    def nearest_component_name(candidate_id: str) -> str:
        cursor: str | None = candidate_id
        depth = 0
        while cursor is not None and depth < 8:
            component_id = component_by_id.get(cursor)
            if component_id:
                return component_labels.get(component_id, "")
            cursor = parent_by_id.get(cursor)
            depth += 1
        return ""

    screen_ids = set(node_documents.keys())
    candidates = AssetAnalysis.summarize_asset_candidates(all_nodes)
    for candidate in candidates:
        candidate_id = candidate.get("id", "")
        chain: list[dict[str, str]] = []
        cursor = parent_by_id.get(candidate_id)
        depth = 0
        while cursor is not None and depth < 3:
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
