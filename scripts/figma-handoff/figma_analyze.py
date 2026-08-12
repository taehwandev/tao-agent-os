from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from figma_parse import _parse_effect_entry
from figma_util import (
    _color_dict_to_hex,
    extract_text_style,
    format_number,
    is_number,
    iter_nodes,
    normalize_node_id,
    paint_to_hex,
    parse_gradient_paint,
    round_number,
)


def summarize_colors(nodes: list[dict[str, Any]], parsed_variables: dict[str, Any]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    sources: dict[str, list[str]] = defaultdict(list)
    bound_var_names: dict[str, list[str]] = defaultdict(list)
    bound_var_ids: dict[str, list[str]] = defaultdict(list)
    variable_names = build_variable_name_map(parsed_variables)

    def record(hex_value: str, node_name: str, field: str, variable_id: str = "", variable_name: str = "") -> None:
        counter[hex_value] += 1
        source = f"{node_name} ({field})"
        if source not in sources[hex_value] and len(sources[hex_value]) < 8:
            sources[hex_value].append(source)
        if variable_id and variable_id not in bound_var_ids[hex_value]:
            bound_var_ids[hex_value].append(variable_id)
        if variable_name and variable_name not in bound_var_names[hex_value]:
            bound_var_names[hex_value].append(variable_name)

    for node in nodes:
        node_name = str(node.get("name", ""))

        for field in ("fills", "strokes"):
            for i, paint in enumerate(node.get(field, []) or []):
                if not isinstance(paint, dict) or paint.get("visible") is False:
                    continue
                if paint.get("type") != "SOLID":
                    continue
                hex_value = paint_to_hex(paint)
                if not hex_value:
                    continue
                if len(hex_value) == 9 and hex_value.endswith("00"):
                    continue
                variable_id = ""
                variable_name = ""
                var_id = _bound_variable_id_for_paint(node, paint, field, i)
                if var_id:
                    variable_id = var_id
                    variable_name = variable_names.get(var_id, "")
                record(hex_value, node_name, field, variable_id, variable_name)

        bg_color = node.get("backgroundColor")
        if isinstance(bg_color, dict):
            hex_value = _color_dict_to_hex(bg_color)
            if hex_value and not (len(hex_value) == 9 and hex_value.endswith("00")):
                var_id = _bound_variable_id_for_field(node, "backgroundColor", None)
                record(
                    hex_value,
                    node_name,
                    "backgroundColor",
                    var_id,
                    variable_names.get(var_id, "") if var_id else "",
                )

    return [
        {
            "hex": hex_value,
            "count": count,
            "sources": sources[hex_value],
            "boundVariableNames": bound_var_names.get(hex_value, []),
            "boundVariableIds": bound_var_ids.get(hex_value, []),
        }
        for hex_value, count in counter.most_common()
    ]

def summarize_gradients(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    parsed: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        node_name = str(node.get("name", ""))
        for field in ("background", "fills", "strokes"):
            for paint in node.get(field, []) or []:
                gradient = parse_gradient_paint(paint)
                if not gradient:
                    continue
                key = json.dumps(gradient, sort_keys=True, ensure_ascii=False)
                counter[key] += 1
                parsed[key] = gradient
                source = f"{node_name} ({field})"
                if source not in sources[key] and len(sources[key]) < 8:
                    sources[key].append(source)

    return [
        {
            **parsed[key],
            "count": count,
            "sources": sources[key],
        }
        for key, count in counter.most_common()
    ]

def build_variable_name_map(parsed_variables: dict[str, Any]) -> dict[str, str]:
    collections = {
        str(collection.get("id", "")): str(collection.get("name", ""))
        for collection in parsed_variables.get("collections", [])
        if collection.get("id")
    }
    result: dict[str, str] = {}
    for variable in parsed_variables.get("variables", []):
        var_id = str(variable.get("id", ""))
        if not var_id:
            continue
        collection_name = collections.get(str(variable.get("collectionId", "")), "")
        variable_name = str(variable.get("name", ""))
        result[var_id] = "/".join(part for part in (collection_name, variable_name) if part) or var_id
    return result

def _bound_variable_id_for_paint(node: dict[str, Any], paint: dict[str, Any], field: str, index: int) -> str:
    for container_name in ("boundVariables", "boundVariableIds"):
        container = paint.get(container_name)
        if not isinstance(container, dict):
            continue
        for candidate in (
            container.get("color"),
            _select_bound_variable(container.get(field), index),
            container,
        ):
            var_id = _extract_variable_id(candidate)
            if var_id:
                return var_id
    return _bound_variable_id_for_field(node, field, index)

def _bound_variable_id_for_field(node: dict[str, Any], field: str, index: int | None) -> str:
    key_candidates = [field]
    if field == "backgroundColor":
        key_candidates.extend(["background", "fills"])
    for container_name in ("boundVariables", "boundVariableIds"):
        container = node.get(container_name)
        if not isinstance(container, dict):
            continue
        for key in key_candidates:
            value = container.get(key)
            candidate = _select_bound_variable(value, index) if index is not None else value
            var_id = _extract_variable_id(candidate)
            if var_id:
                return var_id
    return ""

def _select_bound_variable(value: Any, index: int) -> Any:
    if isinstance(value, list):
        return value[index] if index < len(value) else None
    if isinstance(value, dict):
        if str(index) in value:
            return value[str(index)]
        if index in value:
            return value[index]
        return value
    return value

def _extract_variable_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            nested_id = _extract_variable_id(item)
            if nested_id:
                return nested_id
        return ""
    if not isinstance(value, dict):
        return ""
    raw_id = value.get("id")
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    for key in ("color", "variable", "resolvedVariable", "alias"):
        nested_id = _extract_variable_id(value.get(key))
        if nested_id:
            return nested_id
    return ""

def summarize_text_styles(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    parsed: dict[str, dict[str, Any]] = {}

    for node in nodes:
        if node.get("type") != "TEXT":
            continue
        base_style = node.get("style")
        if not isinstance(base_style, dict):
            continue

        styles_to_record: list[dict[str, Any]] = [base_style]
        override_table = node.get("styleOverrideTable")
        if isinstance(override_table, dict):
            for override in override_table.values():
                if isinstance(override, dict):
                    merged = {**base_style, **override}
                    styles_to_record.append(merged)

        sample = str(node.get("characters", node.get("name", ""))).replace("\n", " ")
        for style in styles_to_record:
            summary = extract_text_style(style)
            key = json.dumps(summary, sort_keys=True, ensure_ascii=False)
            counter[key] += 1
            parsed[key] = summary
            if sample and sample not in samples[key] and len(samples[key]) < 5:
                samples[key].append(sample[:80])

    return [
        {
            **parsed[key],
            "count": count,
            "samples": samples[key],
        }
        for key, count in counter.most_common()
    ]

def summarize_effects(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    parsed: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        for effect in node.get("effects", []) or []:
            if not isinstance(effect, dict) or effect.get("visible") is False:
                continue
            summary = _parse_effect_entry(effect)
            key = json.dumps(summary, sort_keys=True, ensure_ascii=False)
            counter[key] += 1
            parsed[key] = summary
            source = str(node.get("name", ""))
            if source and source not in sources[key] and len(sources[key]) < 5:
                sources[key].append(source)

    return [
        {**parsed[key], "count": count, "sources": sources[key]}
        for key, count in counter.most_common()
    ]


def summarize_flow_interactions(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []

    for node in nodes:
        node_id = normalize_node_id(str(node.get("id", "")))
        if not node_id:
            continue
        node_name = str(node.get("name", ""))
        legacy_target = _normalize_optional_node_id(node.get("transitionNodeID"))
        legacy_transition = {
            "type": None,
            "durationSeconds": _duration_to_seconds(node.get("transitionDuration")),
            "easingType": node.get("transitionEasing"),
        }

        raw_interactions = node.get("interactions")
        if isinstance(raw_interactions, list) and raw_interactions:
            for interaction in raw_interactions:
                if not isinstance(interaction, dict):
                    continue
                trigger = interaction.get("trigger") if isinstance(interaction.get("trigger"), dict) else {}
                actions = interaction.get("actions")
                if isinstance(actions, list) and actions:
                    for action in actions:
                        if isinstance(action, dict):
                            interactions.append(_parse_interaction_action(node_id, node_name, trigger, action, legacy_target))
                else:
                    interactions.append({
                        "fromNodeId": node_id,
                        "fromName": node_name,
                        "triggerType": trigger.get("type"),
                        "actionType": None,
                        "navigation": None,
                        "toNodeId": legacy_target,
                        "destinationSource": "transitionNodeID" if legacy_target else None,
                        "transition": legacy_transition,
                        "rawTrigger": trigger,
                        "rawAction": None,
                    })
        elif legacy_target:
            interactions.append({
                "fromNodeId": node_id,
                "fromName": node_name,
                "triggerType": None,
                "actionType": "NODE",
                "navigation": None,
                "toNodeId": legacy_target,
                "destinationSource": "transitionNodeID",
                "transition": legacy_transition,
                "rawTrigger": None,
                "rawAction": None,
            })

    return interactions


def _parse_interaction_action(
    node_id: str,
    node_name: str,
    trigger: dict[str, Any],
    action: dict[str, Any],
    legacy_target: str | None,
) -> dict[str, Any]:
    destination_key = ""
    raw_destination = None
    for key in ("destinationId", "destinationID", "destinationNodeID"):
        if action.get(key):
            destination_key = key
            raw_destination = action.get(key)
            break
    destination = _normalize_optional_node_id(raw_destination)
    destination_source = f"action.{destination_key}" if destination_key and destination else None
    if destination is None and legacy_target:
        destination = legacy_target
        destination_source = "transitionNodeID"

    transition = action.get("transition") if isinstance(action.get("transition"), dict) else {}
    easing = transition.get("easing") if isinstance(transition.get("easing"), dict) else {}
    return {
        "fromNodeId": node_id,
        "fromName": node_name,
        "triggerType": trigger.get("type"),
        "actionType": action.get("type"),
        "navigation": action.get("navigation"),
        "toNodeId": destination,
        "destinationSource": destination_source,
        "transition": {
            "type": transition.get("type"),
            "durationSeconds": _duration_to_seconds(transition.get("duration")),
            "easingType": easing.get("type") or transition.get("easing"),
            "direction": transition.get("direction"),
            "matchLayers": transition.get("matchLayers"),
            "easingFunctionCubicBezier": transition.get("easingFunctionCubicBezier"),
        },
        "rawTrigger": trigger,
        "rawAction": action,
    }


def _normalize_optional_node_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return normalize_node_id(value)


def _duration_to_seconds(value: Any) -> int | float | None:
    duration = round_number(value)
    if duration is None:
        return None
    if duration > 10:
        return round_number(duration / 1000)
    return duration


def summarize_layout_metrics(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    numeric_keys = (
        "itemSpacing",
        "counterAxisSpacing",
        "paddingTop",
        "paddingRight",
        "paddingBottom",
        "paddingLeft",
        "cornerRadius",
        "minWidth",
        "maxWidth",
        "minHeight",
        "maxHeight",
    )
    enum_keys = (
        "layoutMode",
        "primaryAxisAlignItems",
        "counterAxisAlignItems",
        "counterAxisAlignContent",
        "layoutWrap",
        "primaryAxisSizingMode",
        "counterAxisSizingMode",
        "layoutPositioning",
    )

    numeric_counters: dict[str, Counter[str]] = {k: Counter() for k in numeric_keys}
    enum_counters: dict[str, Counter[str]] = {k: Counter() for k in enum_keys}

    for node in nodes:
        radii = node.get("rectangleCornerRadii")
        has_individual_radii = isinstance(radii, list) and len(radii) == 4
        for key in numeric_keys:
            if key == "cornerRadius" and has_individual_radii:
                continue  # per-corner array takes precedence; count below
            value = node.get(key)
            if is_number(value):
                numeric_counters[key][format_number(value)] += 1
        if has_individual_radii:
            for r in radii:
                if is_number(r):
                    numeric_counters["cornerRadius"][format_number(r)] += 1
        for key in enum_keys:
            value = node.get(key)
            if isinstance(value, str) and value:
                enum_counters[key][value] += 1

    result: dict[str, list[dict[str, Any]]] = {}
    for key, counter in numeric_counters.items():
        if counter:
            result[key] = [{"value": v, "count": c} for v, c in counter.most_common()]
    for key, counter in enum_counters.items():
        if counter:
            result[key] = [{"value": v, "count": c} for v, c in counter.most_common()]
    return result

def summarize_layout_nodes(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(node: Any, parent_id: str | None, depth: int) -> None:
        if not isinstance(node, dict):
            return
        entry = _layout_node_entry(node, parent_id, depth)
        if entry:
            result.append(entry)
        node_id = normalize_node_id(str(node.get("id", ""))) or parent_id
        for child in node.get("children", []) or []:
            walk(child, node_id, depth + 1)

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
        "layoutMode",
        "layoutWrap",
        "primaryAxisAlignItems",
        "counterAxisAlignItems",
        "counterAxisAlignContent",
        "primaryAxisSizingMode",
        "counterAxisSizingMode",
        "layoutPositioning",
        "layoutAlign",
        "layoutGrow",
        "layoutSizingHorizontal",
        "layoutSizingVertical",
        "itemSpacing",
        "counterAxisSpacing",
        "paddingTop",
        "paddingRight",
        "paddingBottom",
        "paddingLeft",
        "cornerRadius",
        "rectangleCornerRadii",
        "minWidth",
        "maxWidth",
        "minHeight",
        "maxHeight",
        "constraints",
        "clipsContent",
        "overflowDirection",
        # 시각 충실도(1:1 재현)에 필요하지만 이전엔 summary에서 누락되던 필드들.
        # 값 자체는 raw/nodes.json에 항상 존재했다.
        "opacity",
        "blendMode",
        "isMask",
        "maskType",
        "rotation",
        "relativeTransform",
        "size",
        "strokeWeight",
        "strokeAlign",
        "individualStrokeWeights",
        "strokeDashes",
    )
    for field in fields:
        if field in node:
            entry[field] = _round_layout_value(node[field])

    # 인스턴스 정체성: 이 노드가 어느 컴포넌트의 인스턴스인지 + variant/텍스트 등 속성.
    # 값은 raw/nodes.json에 항상 있었지만 summary에서 누락되던 정보다.
    component_id = node.get("componentId")
    if isinstance(component_id, str) and component_id:
        entry["componentId"] = normalize_node_id(component_id)
    component_properties = _flatten_component_properties(node.get("componentProperties"))
    if component_properties:
        entry["componentProperties"] = component_properties

    return entry if len(entry) > 5 else {}


def _flatten_component_properties(value: Any, variant_only: bool = False) -> dict[str, Any]:
    """Figma componentProperties(`{name: {value, type}}`)를 `{name: value}`로 평탄화.

    variant_only=True면 VARIANT 타입만 남긴다(카탈로그 variant 표기용).
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for name, prop in value.items():
        if not isinstance(prop, dict):
            continue
        if variant_only and prop.get("type") != "VARIANT":
            continue
        result[str(name)] = prop.get("value")
    return result


def summarize_components(
    node_documents: dict[str, dict[str, Any]],
    component_index: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """화면에서 실제 사용된 컴포넌트 인벤토리(= 컴포넌트화 work-list).

    인스턴스를 componentId로 묶어 사용 횟수·사용 화면·variant를 집계하고,
    file-level components/componentSets 맵으로 이름·컴포넌트셋을 보강한다.
    사용 횟수 내림차순 정렬 → 상위부터 하나씩 코드 컴포넌트로 정의하면 된다.
    """
    index = component_index or {}
    norm_components = {
        normalize_node_id(str(k)): v
        for k, v in (index.get("components") or {}).items()
        if isinstance(v, dict)
    }
    norm_sets = {
        normalize_node_id(str(k)): v
        for k, v in (index.get("componentSets") or {}).items()
        if isinstance(v, dict)
    }

    usage: dict[str, dict[str, Any]] = {}
    for screen_id, document in node_documents.items():
        for node in iter_nodes(document):
            if node.get("type") != "INSTANCE":
                continue
            raw_cid = node.get("componentId")
            if not isinstance(raw_cid, str) or not raw_cid:
                continue
            cid = normalize_node_id(raw_cid)
            entry = usage.setdefault(
                cid,
                {"usageCount": 0, "usedInScreens": [], "variantProperties": {}, "instanceName": ""},
            )
            entry["usageCount"] += 1
            if screen_id not in entry["usedInScreens"]:
                entry["usedInScreens"].append(screen_id)
            if not entry["variantProperties"]:
                entry["variantProperties"] = _flatten_component_properties(
                    node.get("componentProperties"), variant_only=True
                )
            if not entry["instanceName"]:
                entry["instanceName"] = str(node.get("name", ""))

    catalog: list[dict[str, Any]] = []
    for cid, use in usage.items():
        meta = norm_components.get(cid, {})
        entry: dict[str, Any] = {
            "componentId": cid,
            "name": meta.get("name") or use["instanceName"],
            "usageCount": use["usageCount"],
            "usedInScreens": use["usedInScreens"],
        }
        set_id_raw = meta.get("componentSetId")
        if isinstance(set_id_raw, str) and set_id_raw:
            set_id = normalize_node_id(set_id_raw)
            entry["componentSetId"] = set_id
            set_meta = norm_sets.get(set_id, {})
            if set_meta.get("name"):
                entry["componentSetName"] = set_meta["name"]
        if use["variantProperties"]:
            entry["variantProperties"] = use["variantProperties"]
        if meta.get("description"):
            entry["description"] = meta["description"]
        if isinstance(meta.get("remote"), bool):
            entry["remote"] = meta["remote"]
        catalog.append(entry)

    catalog.sort(key=lambda c: (-c["usageCount"], c["componentId"]))
    return catalog


def _descendant_count(node: dict[str, Any]) -> int:
    return 1 + sum(
        _descendant_count(child)
        for child in (node.get("children") or [])
        if isinstance(child, dict)
    )


def summarize_component_blueprints(
    node_documents: dict[str, dict[str, Any]],
    components: list[dict[str, Any]],
    asset_dedup_by_id: dict[str, str] | None = None,
    max_nodes: int = 80,
) -> list[dict[str, Any]]:
    """각 컴포넌트를 어떻게 조립하는지 알려주는 청사진(대표 인스턴스의 내부 서브트리).

    구현자가 화면을 범용 레이아웃으로 손으로 재구성하지 않도록, "이 카드 = Slot/image +
    title + LeftActions(avatar·name·HeartToggle+Count)" 같은 실제 내부 구조를 넘긴다.
    중첩 인스턴스(예 Icon/HeartToggle)는 경계에서 멈추고 componentId 참조만 남겨(각자 자기
    청사진이 있으므로) 조합형으로 유지하고 크기 폭발을 막는다.
    """
    asset_dedup_by_id = asset_dedup_by_id or {}
    instances: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def collect(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "INSTANCE":
            raw_cid = node.get("componentId")
            if isinstance(raw_cid, str) and raw_cid:
                instances[normalize_node_id(raw_cid)].append(node)
        for child in node.get("children") or []:
            collect(child)

    for document in node_documents.values():
        collect(document)

    catalog_by_id = {c["componentId"]: c for c in components}
    blueprints: list[dict[str, Any]] = []
    for cid, nodes in instances.items():
        representative = max(nodes, key=_descendant_count)
        structure: list[dict[str, Any]] = []

        def emit(node: dict[str, Any], depth: int) -> None:
            if len(structure) >= max_nodes:
                return
            node_id = normalize_node_id(str(node.get("id", "")))
            bounds = node.get("absoluteBoundingBox") or {}
            item: dict[str, Any] = {
                "name": node.get("name", ""),
                "type": node.get("type", ""),
                "depth": depth,
            }
            if bounds.get("width") is not None:
                item["w"] = round_number(bounds.get("width"))
            if bounds.get("height") is not None:
                item["h"] = round_number(bounds.get("height"))
            raw_cid = node.get("componentId")
            nested_instance = node.get("type") == "INSTANCE" and isinstance(raw_cid, str) and bool(raw_cid)
            if nested_instance:
                item["componentId"] = normalize_node_id(raw_cid)
            dedup_key = asset_dedup_by_id.get(node_id)
            if dedup_key:
                item["assetDedupKey"] = dedup_key
            if node.get("type") == "TEXT":
                chars = str(node.get("characters", "")).replace("\n", " ").strip()
                if chars:
                    item["text"] = chars[:40]
            structure.append(item)
            if nested_instance:
                return  # 중첩 인스턴스는 경계 — 내부로 재귀하지 않음
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    emit(child, depth + 1)

        for child in representative.get("children") or []:
            if isinstance(child, dict):
                emit(child, 1)

        if not structure:
            continue  # 내부 구조 없는 순수 아이콘 리프는 청사진 불필요

        catalog_entry = catalog_by_id.get(cid, {})
        rep_bounds = representative.get("absoluteBoundingBox") or {}
        blueprint: dict[str, Any] = {
            "componentId": cid,
            "name": catalog_entry.get("componentSetName")
            or catalog_entry.get("name")
            or representative.get("name", ""),
            "usageCount": len(nodes),
            "representativeInstanceId": normalize_node_id(str(representative.get("id", ""))),
            "structure": structure,
        }
        if rep_bounds.get("width") is not None and rep_bounds.get("height") is not None:
            blueprint["size"] = {
                "w": round_number(rep_bounds.get("width")),
                "h": round_number(rep_bounds.get("height")),
            }
        if catalog_entry.get("componentSetName"):
            blueprint["componentSetName"] = catalog_entry["componentSetName"]
        if catalog_entry.get("variantProperties"):
            blueprint["variantProperties"] = catalog_entry["variantProperties"]
        blueprints.append(blueprint)

    blueprints.sort(key=lambda b: (-b["usageCount"], b["componentId"]))
    return blueprints

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

def summarize_text_runs(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        _append_text_run(result, node, characters, base_style, override_table, run_start, min(len(overrides), len(characters)), current_override)
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
    resolved_style = {**base_style, **override}
    result.append({
        "nodeId": normalize_node_id(str(node.get("id", ""))),
        "nodeName": node.get("name", ""),
        "range": {"start": start, "end": end},
        "text": characters[start:end],
        "overrideId": str(override_id),
        "resolvedStyle": extract_text_style(resolved_style),
    })

def _asset_dedup_key(node: dict[str, Any], image_refs: list[str]) -> str:
    """같은 asset을 한 번만 렌더/다운로드하기 위한 dedup 키.

    - 이미지 fill: imageRef가 같으면 확실히 같은 비트맵 → "img:<refs>".
    - 벡터/불리언 등: 렌더 결과를 결정하는 시각 필드(+name)가 모두 같을 때만 병합한다.
      name·색·기하(fillGeometry)까지 포함하므로 시각적으로 다른 아이콘이 잘못 합쳐지지 않는다.
      기하 데이터가 없으면 type/name/size/fills/strokes/effects 조합으로 보수적으로 병합한다.
    """
    if image_refs:
        return "img:" + ",".join(sorted(image_refs))

    signature_fields = (
        "type", "name", "size", "absoluteBoundingBox", "fills", "strokes",
        "strokeWeight", "strokeAlign", "individualStrokeWeights", "cornerRadius",
        "rectangleCornerRadii", "effects", "opacity", "blendMode",
        "fillGeometry", "strokeGeometry",
    )
    signature = {field: node[field] for field in signature_fields if field in node}
    digest = hashlib.sha1(
        json.dumps(signature, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return "vec:" + digest


_GENERIC_NAME_PREFIXES = (
    "vector", "rectangle", "group", "union", "ellipse", "subtract",
    "frame", "mask", "shape", "path", "intersect", "exclude", "line",
)


def _is_generic_name(name: Any) -> bool:
    """`Vector`, `Rectangle 12`, `Group 5`처럼 의미 없는 자동 생성 이름인가."""
    text = str(name or "").strip().lower()
    return not text or any(text.startswith(prefix) for prefix in _GENERIC_NAME_PREFIXES)


def _pick_representative_name(names: list[str], nearest_names: list[str]) -> str:
    for name in names:
        if not _is_generic_name(name):
            return name
    if nearest_names:
        return nearest_names[0]
    return names[0] if names else ""


def build_asset_inventory(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """assetCandidates를 dedupKey로 묶은 고유 아이콘 인벤토리(반복 구현 방지용).

    동일 시그니처(geometry+색+name 또는 imageRef) asset은 한 항목으로 묶고,
    이름이 generic이면 `nearestComponentName`(포함된 컴포넌트 이름)으로 대표 이름을 복구한다.
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for candidate in candidates:
        key = candidate.get("dedupKey") or candidate.get("id") or ""
        group = groups.get(key)
        if group is None:
            group = {
                "type": candidate.get("type", ""),
                "nodeIds": [],
                "names": [],
                "imageRefs": candidate.get("imageRefs") or [],
                "nearestNames": [],
            }
            groups[key] = group
            order.append(key)
        if candidate.get("id"):
            group["nodeIds"].append(candidate["id"])
        if candidate.get("name"):
            group["names"].append(str(candidate["name"]))
        nearest = candidate.get("nearestComponentName")
        if nearest:
            group["nearestNames"].append(str(nearest))

    inventory: list[dict[str, Any]] = []
    for key in order:
        group = groups[key]
        entry: dict[str, Any] = {
            "dedupKey": key,
            "name": _pick_representative_name(group["names"], group["nearestNames"]),
            "type": group["type"],
            "usageCount": len(group["nodeIds"]),
            "nodeIds": group["nodeIds"],
            "nameUnclear": all(_is_generic_name(n) for n in group["names"]) if group["names"] else True,
        }
        if group["imageRefs"]:
            entry["imageRefs"] = group["imageRefs"]
        if group["nearestNames"]:
            entry["nearestComponentName"] = group["nearestNames"][0]
        inventory.append(entry)

    inventory.sort(key=lambda e: (-e["usageCount"], e["dedupKey"]))
    return inventory


def summarize_asset_candidates(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for node in nodes:
        export_settings = node.get("exportSettings") or []
        image_refs: list[str] = []
        for field in ("fills", "strokes"):
            for paint in node.get(field, []) or []:
                if isinstance(paint, dict) and paint.get("type") == "IMAGE" and paint.get("imageRef"):
                    image_refs.append(str(paint["imageRef"]))

        if export_settings or image_refs or node.get("type") in {"VECTOR", "BOOLEAN_OPERATION"}:
            candidates.append(
                {
                    "id": normalize_node_id(str(node.get("id", ""))),
                    "name": node.get("name", ""),
                    "type": node.get("type", ""),
                    "exportSettings": export_settings,
                    "imageRefs": image_refs,
                    "dedupKey": _asset_dedup_key(node, image_refs),
                }
            )

    return candidates
