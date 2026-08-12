from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterator

from figma_util import (
    _color_dict_to_hex,
    extract_text_style,
    iter_nodes,
    normalize_node_id,
    paint_to_hex,
    parse_gradient_paint,
    round_number,
)


def _iter_named_styles(
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
    style_type: str,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for style in named_styles.get("meta", {}).get("styles", []):
        if style.get("style_type") != style_type:
            continue
        node_id = normalize_node_id(style.get("node_id", ""))
        doc = style_node_details.get(node_id, {})
        base = {
            "key": style.get("key", ""),
            "name": style.get("name", ""),
            "description": style.get("description", ""),
            "nodeId": node_id,
        }
        yield base, doc

def parse_named_color_styles(
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for base, doc in _iter_named_styles(named_styles, style_node_details, "FILL"):
        gradient_values = [
            gradient
            for gradient in (parse_gradient_paint(p) for p in (doc.get("fills") or []))
            if gradient
        ]
        hex_values = [
            paint_to_hex(p)
            for p in (doc.get("fills") or [])
            if isinstance(p, dict) and p.get("type") == "SOLID" and p.get("visible") is not False
        ]
        result.append({
            **base,
            "hexValues": [h for h in hex_values if h],
            "gradientValues": gradient_values,
        })
    return result

def parse_named_text_styles(
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for base, doc in _iter_named_styles(named_styles, style_node_details, "TEXT"):
        s = doc.get("style") or {}
        result.append({**base, **extract_text_style(s)})
    return result

def _parse_effect_entry(eff: dict[str, Any]) -> dict[str, Any]:
    eff_type = eff.get("type", "")
    entry: dict[str, Any] = {"type": eff_type}
    if eff_type in {"DROP_SHADOW", "INNER_SHADOW"}:
        color = eff.get("color")
        entry["color"] = _color_dict_to_hex(color) if isinstance(color, dict) else None
        entry["offsetX"] = round_number(eff.get("offset", {}).get("x"))
        entry["offsetY"] = round_number(eff.get("offset", {}).get("y"))
        entry["radius"] = round_number(eff.get("radius"))
        entry["spread"] = round_number(eff.get("spread"))
    elif eff_type in {"LAYER_BLUR", "BACKGROUND_BLUR"}:
        entry["radius"] = round_number(eff.get("radius"))
    return entry

def parse_named_effect_styles(
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for base, doc in _iter_named_styles(named_styles, style_node_details, "EFFECT"):
        effects = [
            _parse_effect_entry(eff)
            for eff in (doc.get("effects") or [])
            if isinstance(eff, dict) and eff.get("visible") is not False
        ]
        result.append({**base, "effects": effects})
    return result

def build_referenced_styles(
    file_styles: dict[str, dict[str, Any]],
    node_documents: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build a named style catalog from node payload `styles` maps.

    When styles come from an external library (remote=True) the /styles endpoint
    returns an empty list.  This function recovers style metadata by reading the
    `styles` field that is present on every node payload and cross-referencing it
    with actual fill/text/effect values found on nodes that reference each style.
    """
    style_samples: dict[str, dict[str, Any]] = {}

    for document in node_documents.values():
        for node in iter_nodes(document):
            node_style_refs = node.get("styles")
            if not isinstance(node_style_refs, dict):
                continue
            for field_name, raw_style_id in node_style_refs.items():
                if not isinstance(raw_style_id, str):
                    continue
                style_id = normalize_node_id(raw_style_id)
                if style_id not in file_styles or style_id in style_samples:
                    continue
                style_type = file_styles[style_id].get("styleType", "")
                if style_type == "FILL":
                    sample = _collect_paint_style_sample(node, field_name)
                    if sample:
                        style_samples[style_id] = sample
                elif style_type == "TEXT":
                    s = node.get("style") or {}
                    if s.get("fontFamily"):
                        style_samples[style_id] = extract_text_style(s)
                elif style_type == "EFFECT":
                    effects = [
                        _parse_effect_entry(e)
                        for e in (node.get("effects") or [])
                        if isinstance(e, dict) and e.get("visible") is not False
                    ]
                    if effects:
                        style_samples[style_id] = {"effects": effects}

    color_styles: list[dict[str, Any]] = []
    text_styles: list[dict[str, Any]] = []
    effect_styles: list[dict[str, Any]] = []
    seen_style_keys: set[str] = set()
    seen_names_by_type: dict[str, set[str]] = defaultdict(set)

    # Prefer entries that have a resolved sample (hex/font/effect data available)
    sorted_items = sorted(
        file_styles.items(),
        key=lambda item: (item[1].get("name", ""), 0 if normalize_node_id(item[0]) in style_samples else 1),
    )
    for raw_id, meta in sorted_items:
        style_key = meta.get("key", "")
        if style_key and style_key in seen_style_keys:
            continue
        if style_key:
            seen_style_keys.add(style_key)

        style_type = meta.get("styleType", "")
        style_name = meta.get("name", "")
        # Secondary dedup: same name + type from different library versions
        if style_name and style_name in seen_names_by_type[style_type]:
            continue
        if style_name:
            seen_names_by_type[style_type].add(style_name)

        style_id = normalize_node_id(raw_id)
        base: dict[str, Any] = {
            "nodeId": style_id,
            "key": style_key,
            "name": style_name,
            "remote": meta.get("remote", False),
        }
        sample = style_samples.get(style_id, {})
        if style_type == "FILL":
            hex_values = sample.get("hexValues", [])
            gradient_values = sample.get("gradientValues", [])
            color_styles.append({
                **base,
                "hex": hex_values[0] if hex_values else sample.get("hex"),
                "gradient": gradient_values[0] if gradient_values else sample.get("gradient"),
                "hexValues": hex_values,
                "gradientValues": gradient_values,
            })
        elif style_type == "TEXT":
            text_styles.append({**base, **sample})
        elif style_type == "EFFECT":
            effect_styles.append({**base, "effects": sample.get("effects", [])})

    return {
        "colorStyles": color_styles,
        "textStyles": text_styles,
        "effectStyles": effect_styles,
    }

def _collect_paint_style_sample(node: dict[str, Any], style_field_name: str) -> dict[str, Any]:
    hex_values: list[str] = []
    gradient_values: list[dict[str, Any]] = []
    for paint in _iter_style_paints(node, style_field_name):
        if not isinstance(paint, dict) or paint.get("visible") is False:
            continue
        if paint.get("type") == "SOLID":
            hex_val = paint_to_hex(paint)
            if hex_val and not (len(hex_val) == 9 and hex_val.endswith("00")):
                hex_values.append(hex_val)
        gradient = parse_gradient_paint(paint)
        if gradient:
            gradient_values.append(gradient)

    sample: dict[str, Any] = {}
    if hex_values:
        sample["hexValues"] = hex_values
    if gradient_values:
        sample["gradientValues"] = gradient_values
    return sample

def _iter_style_paints(node: dict[str, Any], style_field_name: str) -> Iterator[dict[str, Any]]:
    for field in _paint_fields_for_style_ref(style_field_name):
        raw_value = node.get(field)
        if isinstance(raw_value, list):
            for paint in raw_value:
                if isinstance(paint, dict):
                    yield paint
        elif field == "backgroundColor" and isinstance(raw_value, dict):
            yield {"type": "SOLID", "color": raw_value}

def _paint_fields_for_style_ref(style_field_name: str) -> tuple[str, ...]:
    key = style_field_name.lower()
    if key in {"fill", "fills"}:
        return ("fills",)
    if key in {"stroke", "strokes"}:
        return ("strokes",)
    if key in {"background", "backgroundcolor"}:
        return ("background", "backgroundColor")
    return ("fills", "strokes", "background", "backgroundColor")

def parse_variables(variables: dict[str, Any]) -> dict[str, Any]:
    meta = variables.get("meta", {})
    variable_collections: list[dict[str, Any]] = []

    raw_collections = meta.get("variableCollections", {})
    for coll in (raw_collections.values() if isinstance(raw_collections, dict) else []):
        modes = [
            {"modeId": m.get("modeId", ""), "name": m.get("name", "")}
            for m in coll.get("modes", [])
            if isinstance(m, dict)
        ]
        variable_collections.append(
            {
                "id": coll.get("id", ""),
                "name": coll.get("name", ""),
                "modes": modes,
                "defaultModeId": coll.get("defaultModeId", ""),
            }
        )

    parsed_variables: list[dict[str, Any]] = []
    raw_variables = meta.get("variables", {})
    collection_default_modes = {
        str(collection["id"]): str(collection.get("defaultModeId", ""))
        for collection in variable_collections
        if collection.get("id")
    }
    for var in (raw_variables.values() if isinstance(raw_variables, dict) else []):
        entry: dict[str, Any] = {
            "id": var.get("id", ""),
            "name": var.get("name", ""),
            "resolvedType": var.get("resolvedType", ""),
            "collectionId": var.get("variableCollectionId", ""),
            "valuesByMode": {},
        }
        for mode_id, raw_value in var.get("valuesByMode", {}).items():
            if isinstance(raw_value, dict) and raw_value.get("type") == "VARIABLE_ALIAS":
                alias_id = raw_value.get("id", "")
                entry["valuesByMode"][mode_id] = {"alias": alias_id, "aliasId": alias_id}
            elif isinstance(raw_value, dict) and var.get("resolvedType") == "COLOR":
                entry["valuesByMode"][mode_id] = {
                    "hex": _color_dict_to_hex(raw_value),
                    "raw": raw_value,
                }
            else:
                entry["valuesByMode"][mode_id] = raw_value
        parsed_variables.append(entry)

    variables_by_id = {str(var.get("id", "")): var for var in parsed_variables if var.get("id")}
    collections_by_id = {str(coll.get("id", "")): str(coll.get("name", "")) for coll in variable_collections}
    for variable in parsed_variables:
        for mode_id, value in variable.get("valuesByMode", {}).items():
            if not isinstance(value, dict) or not value.get("aliasId"):
                continue
            alias_id = str(value["aliasId"])
            value["aliasName"] = _variable_display_name(alias_id, variables_by_id, collections_by_id)
            resolved = _resolve_variable_value(alias_id, str(mode_id), variables_by_id, collection_default_modes, set())
            if isinstance(resolved, dict):
                if resolved.get("hex"):
                    value["resolvedHex"] = resolved["hex"]
                elif resolved.get("aliasName"):
                    value["resolvedAliasName"] = resolved["aliasName"]

    return {
        "collections": variable_collections,
        "variables": parsed_variables,
    }

def _variable_display_name(
    variable_id: str,
    variables_by_id: dict[str, dict[str, Any]],
    collections_by_id: dict[str, str],
) -> str:
    variable = variables_by_id.get(variable_id)
    if not variable:
        return variable_id
    collection_name = collections_by_id.get(str(variable.get("collectionId", "")), "")
    variable_name = str(variable.get("name", ""))
    return "/".join(part for part in (collection_name, variable_name) if part) or variable_id

def _resolve_variable_value(
    variable_id: str,
    mode_id: str,
    variables_by_id: dict[str, dict[str, Any]],
    collection_default_modes: dict[str, str],
    seen: set[str],
) -> Any:
    if variable_id in seen:
        return None
    seen.add(variable_id)
    variable = variables_by_id.get(variable_id)
    if not variable:
        return None
    values = variable.get("valuesByMode", {})
    if not isinstance(values, dict) or not values:
        return None
    value = values.get(mode_id)
    if value is None:
        default_mode = collection_default_modes.get(str(variable.get("collectionId", "")), "")
        value = values.get(default_mode) if default_mode else None
    if value is None:
        value = next(iter(values.values()))
    if isinstance(value, dict) and value.get("aliasId"):
        return _resolve_variable_value(str(value["aliasId"]), mode_id, variables_by_id, collection_default_modes, seen)
    return value
