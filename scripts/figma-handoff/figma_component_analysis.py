from __future__ import annotations

from collections import defaultdict
from typing import Any

from figma_util import iter_nodes, normalize_node_id, round_number

__all__ = ["ComponentAnalysis"]


def _summarize_components(
    node_documents: dict[str, dict[str, Any]],
    component_index: dict[str, Any] | None,
    included_node_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a usage-ordered component list without double-counting overlapping roots."""
    index = component_index or {}
    normalized_components = {
        normalize_node_id(str(key)): value
        for key, value in (index.get("components") or {}).items()
        if isinstance(value, dict)
    }
    normalized_sets = {
        normalize_node_id(str(key)): value
        for key, value in (index.get("componentSets") or {}).items()
        if isinstance(value, dict)
    }
    usage: dict[str, dict[str, Any]] = {}
    seen_node_ids: set[str] = set()
    for screen_id, document in node_documents.items():
        for node in iter_nodes(document):
            node_id = normalize_node_id(str(node.get("id", "")))
            if node_id and node_id in seen_node_ids:
                continue
            if node_id:
                seen_node_ids.add(node_id)
            if included_node_ids is not None and node_id not in included_node_ids:
                continue
            if node.get("type") != "INSTANCE":
                continue
            raw_component_id = node.get("componentId")
            if not isinstance(raw_component_id, str) or not raw_component_id:
                continue
            component_id = normalize_node_id(raw_component_id)
            entry = usage.setdefault(
                component_id,
                {
                    "usageCount": 0,
                    "usedInScreens": [],
                    "instanceNodeIds": [],
                    "variantProperties": {},
                    "instanceName": "",
                },
            )
            entry["usageCount"] += 1
            if node_id:
                entry["instanceNodeIds"].append(node_id)
            if screen_id not in entry["usedInScreens"]:
                entry["usedInScreens"].append(screen_id)
            if not entry["variantProperties"]:
                entry["variantProperties"] = _flatten_component_properties(
                    node.get("componentProperties"), variant_only=True
                )
            if not entry["instanceName"]:
                entry["instanceName"] = str(node.get("name", ""))

    catalog: list[dict[str, Any]] = []
    for component_id, use in usage.items():
        meta = normalized_components.get(component_id, {})
        entry: dict[str, Any] = {
            "componentId": component_id,
            "name": meta.get("name") or use["instanceName"],
            "usageCount": use["usageCount"],
            "usedInScreens": use["usedInScreens"],
            "instanceNodeIds": use["instanceNodeIds"],
        }
        raw_set_id = meta.get("componentSetId")
        if isinstance(raw_set_id, str) and raw_set_id:
            set_id = normalize_node_id(raw_set_id)
            entry["componentSetId"] = set_id
            set_meta = normalized_sets.get(set_id, {})
            if set_meta.get("name"):
                entry["componentSetName"] = set_meta["name"]
        if use["variantProperties"]:
            entry["variantProperties"] = use["variantProperties"]
        if meta.get("description"):
            entry["description"] = meta["description"]
        if isinstance(meta.get("remote"), bool):
            entry["remote"] = meta["remote"]
        catalog.append(entry)
    catalog.sort(key=lambda component: (-component["usageCount"], component["componentId"]))
    return catalog


def _flatten_component_properties(value: Any, variant_only: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(name): prop.get("value")
        for name, prop in value.items()
        if isinstance(prop, dict) and (not variant_only or prop.get("type") == "VARIANT")
    }


def _descendant_count(node: dict[str, Any], included_node_ids: set[str] | None) -> int:
    return 1 + sum(
        _descendant_count(child, included_node_ids)
        for child in (node.get("children") or [])
        if isinstance(child, dict)
        and (
            included_node_ids is None
            or normalize_node_id(str(child.get("id", ""))) in included_node_ids
        )
    )


def _summarize_component_blueprints(
    node_documents: dict[str, dict[str, Any]],
    components: list[dict[str, Any]],
    asset_dedup_by_id: dict[str, str] | None = None,
    max_nodes: int = 80,
    included_node_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    asset_dedup_by_id = asset_dedup_by_id or {}
    instances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_node_ids: set[str] = set()

    def collect(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node_id = normalize_node_id(str(node.get("id", "")))
        duplicate = bool(node_id and node_id in seen_node_ids)
        if node_id and not duplicate:
            seen_node_ids.add(node_id)
        if included_node_ids is not None and node_id not in included_node_ids:
            return
        if not duplicate and node.get("type") == "INSTANCE":
            raw_component_id = node.get("componentId")
            if isinstance(raw_component_id, str) and raw_component_id:
                instances[normalize_node_id(raw_component_id)].append(node)
        for child in node.get("children") or []:
            collect(child)

    for document in node_documents.values():
        collect(document)

    catalog_by_id = {component["componentId"]: component for component in components}
    blueprints: list[dict[str, Any]] = []
    for component_id, nodes in instances.items():
        representative = max(nodes, key=lambda node: _descendant_count(node, included_node_ids))
        structure: list[dict[str, Any]] = []

        def emit(node: dict[str, Any], depth: int) -> None:
            if len(structure) >= max_nodes:
                return
            node_id = normalize_node_id(str(node.get("id", "")))
            if included_node_ids is not None and node_id not in included_node_ids:
                return
            bounds = node.get("absoluteBoundingBox") or {}
            item: dict[str, Any] = {"name": node.get("name", ""), "type": node.get("type", ""), "depth": depth}
            if bounds.get("width") is not None:
                item["w"] = round_number(bounds.get("width"))
            if bounds.get("height") is not None:
                item["h"] = round_number(bounds.get("height"))
            raw_component_id = node.get("componentId")
            nested_instance = node.get("type") == "INSTANCE" and isinstance(raw_component_id, str) and bool(raw_component_id)
            if nested_instance:
                item["componentId"] = normalize_node_id(raw_component_id)
            dedup_key = asset_dedup_by_id.get(node_id)
            if dedup_key:
                item["assetDedupKey"] = dedup_key
            if node.get("type") == "TEXT":
                characters = str(node.get("characters", "")).replace("\n", " ").strip()
                if characters:
                    item["text"] = characters[:40]
            structure.append(item)
            if nested_instance:
                return
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    emit(child, depth + 1)

        for child in representative.get("children") or []:
            if isinstance(child, dict):
                emit(child, 1)
        if not structure:
            continue
        catalog_entry = catalog_by_id.get(component_id, {})
        representative_bounds = representative.get("absoluteBoundingBox") or {}
        blueprint: dict[str, Any] = {
            "componentId": component_id,
            "name": catalog_entry.get("componentSetName") or catalog_entry.get("name") or representative.get("name", ""),
            "usageCount": len(nodes),
            "representativeInstanceId": normalize_node_id(str(representative.get("id", ""))),
            "structure": structure,
        }
        if representative_bounds.get("width") is not None and representative_bounds.get("height") is not None:
            blueprint["size"] = {
                "w": round_number(representative_bounds.get("width")),
                "h": round_number(representative_bounds.get("height")),
            }
        if catalog_entry.get("componentSetName"):
            blueprint["componentSetName"] = catalog_entry["componentSetName"]
        if catalog_entry.get("variantProperties"):
            blueprint["variantProperties"] = catalog_entry["variantProperties"]
        blueprints.append(blueprint)
    blueprints.sort(key=lambda blueprint: (-blueprint["usageCount"], blueprint["componentId"]))
    return blueprints


class ComponentAnalysis:
    """Component catalog and blueprint analysis family."""

    summarize_component_blueprints = staticmethod(_summarize_component_blueprints)
    summarize_components = staticmethod(_summarize_components)
