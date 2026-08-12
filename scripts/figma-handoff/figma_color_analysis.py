from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from figma_style_parse import _parse_effect_entry
from figma_util import _color_dict_to_hex, extract_text_style, paint_to_hex, parse_gradient_paint

__all__ = ["ColorAnalysis"]


def _summarize_colors(nodes: list[dict[str, Any]], parsed_variables: dict[str, Any]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    sources: dict[str, list[str]] = defaultdict(list)
    bound_var_names: dict[str, list[str]] = defaultdict(list)
    bound_var_ids: dict[str, list[str]] = defaultdict(list)
    variable_names = _build_variable_name_map(parsed_variables)

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
            for index, paint in enumerate(node.get(field, []) or []):
                if not isinstance(paint, dict) or paint.get("visible") is False or paint.get("type") != "SOLID":
                    continue
                hex_value = paint_to_hex(paint)
                if not hex_value or (len(hex_value) == 9 and hex_value.endswith("00")):
                    continue
                variable_id = _bound_variable_id_for_paint(node, paint, field, index)
                record(hex_value, node_name, field, variable_id, variable_names.get(variable_id, ""))

        background = node.get("backgroundColor")
        if isinstance(background, dict):
            hex_value = _color_dict_to_hex(background)
            if hex_value and not (len(hex_value) == 9 and hex_value.endswith("00")):
                variable_id = _bound_variable_id_for_field(node, "backgroundColor", None)
                record(hex_value, node_name, "backgroundColor", variable_id, variable_names.get(variable_id, ""))

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


def _summarize_gradients(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return [{**parsed[key], "count": count, "sources": sources[key]} for key, count in counter.most_common()]


def _build_variable_name_map(parsed_variables: dict[str, Any]) -> dict[str, str]:
    collections = {
        str(collection.get("id", "")): str(collection.get("name", ""))
        for collection in parsed_variables.get("collections", [])
        if collection.get("id")
    }
    result: dict[str, str] = {}
    for variable in parsed_variables.get("variables", []):
        variable_id = str(variable.get("id", ""))
        if not variable_id:
            continue
        collection_name = collections.get(str(variable.get("collectionId", "")), "")
        variable_name = str(variable.get("name", ""))
        result[variable_id] = "/".join(part for part in (collection_name, variable_name) if part) or variable_id
    return result


def _bound_variable_id_for_paint(
    node: dict[str, Any], paint: dict[str, Any], field: str, index: int
) -> str:
    for container_name in ("boundVariables", "boundVariableIds"):
        container = paint.get(container_name)
        if not isinstance(container, dict):
            continue
        for candidate in (container.get("color"), _select_bound_variable(container.get(field), index), container):
            variable_id = _extract_variable_id(candidate)
            if variable_id:
                return variable_id
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
            variable_id = _extract_variable_id(candidate)
            if variable_id:
                return variable_id
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


def _extract_variable_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return next((nested for item in value if (nested := _extract_variable_id(item))), "")
    if not isinstance(value, dict):
        return ""
    raw_id = value.get("id")
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    return next(
        (nested for key in ("color", "variable", "resolvedVariable", "alias") if (nested := _extract_variable_id(value.get(key)))),
        "",
    )


def _summarize_text_styles(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    parsed: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.get("type") != "TEXT" or not isinstance(node.get("style"), dict):
            continue
        base_style = node["style"]
        styles = [base_style]
        override_table = node.get("styleOverrideTable")
        if isinstance(override_table, dict):
            styles.extend({**base_style, **override} for override in override_table.values() if isinstance(override, dict))
        sample = str(node.get("characters", node.get("name", ""))).replace("\n", " ")
        for style in styles:
            summary = extract_text_style(style)
            key = json.dumps(summary, sort_keys=True, ensure_ascii=False)
            counter[key] += 1
            parsed[key] = summary
            if sample and sample not in samples[key] and len(samples[key]) < 5:
                samples[key].append(sample[:80])
    return [{**parsed[key], "count": count, "samples": samples[key]} for key, count in counter.most_common()]


def _summarize_effects(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return [{**parsed[key], "count": count, "sources": sources[key]} for key, count in counter.most_common()]


class ColorAnalysis:
    """Color, gradient, text-style, and effect analysis family."""

    build_variable_name_map = staticmethod(_build_variable_name_map)
    summarize_colors = staticmethod(_summarize_colors)
    summarize_effects = staticmethod(_summarize_effects)
    summarize_gradients = staticmethod(_summarize_gradients)
    summarize_text_styles = staticmethod(_summarize_text_styles)
