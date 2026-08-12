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

__all__ = ["StyleParser"]


def _iter_named_styles(
    named_styles: dict[str, Any],
    style_node_details: dict[str, dict[str, Any]],
    style_type: str,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for style in named_styles.get("meta", {}).get("styles", []):
        if style.get("style_type") != style_type:
            continue
        node_id = normalize_node_id(style.get("node_id", ""))
        yield {
            "key": style.get("key", ""),
            "name": style.get("name", ""),
            "description": style.get("description", ""),
            "nodeId": node_id,
        }, style_node_details.get(node_id, {})


def _parse_named_color_styles(
    named_styles: dict[str, Any], style_node_details: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for base, document in _iter_named_styles(named_styles, style_node_details, "FILL"):
        gradients = [
            gradient
            for gradient in (parse_gradient_paint(paint) for paint in (document.get("fills") or []))
            if gradient
        ]
        hex_values = [
            paint_to_hex(paint)
            for paint in (document.get("fills") or [])
            if isinstance(paint, dict) and paint.get("type") == "SOLID" and paint.get("visible") is not False
        ]
        result.append({**base, "hexValues": [value for value in hex_values if value], "gradientValues": gradients})
    return result


def _parse_named_text_styles(
    named_styles: dict[str, Any], style_node_details: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {**base, **extract_text_style(document.get("style") or {})}
        for base, document in _iter_named_styles(named_styles, style_node_details, "TEXT")
    ]


def _parse_effect_entry(effect: dict[str, Any]) -> dict[str, Any]:
    effect_type = effect.get("type", "")
    entry: dict[str, Any] = {"type": effect_type}
    if effect_type in {"DROP_SHADOW", "INNER_SHADOW"}:
        color = effect.get("color")
        entry.update(
            {
                "color": _color_dict_to_hex(color) if isinstance(color, dict) else None,
                "offsetX": round_number(effect.get("offset", {}).get("x")),
                "offsetY": round_number(effect.get("offset", {}).get("y")),
                "radius": round_number(effect.get("radius")),
                "spread": round_number(effect.get("spread")),
            }
        )
    elif effect_type in {"LAYER_BLUR", "BACKGROUND_BLUR"}:
        entry["radius"] = round_number(effect.get("radius"))
    return entry


def _parse_named_effect_styles(
    named_styles: dict[str, Any], style_node_details: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for base, document in _iter_named_styles(named_styles, style_node_details, "EFFECT"):
        effects = [
            _parse_effect_entry(effect)
            for effect in (document.get("effects") or [])
            if isinstance(effect, dict) and effect.get("visible") is not False
        ]
        result.append({**base, "effects": effects})
    return result


def _build_referenced_styles(
    file_styles: dict[str, dict[str, Any]],
    node_documents: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    style_samples: dict[str, dict[str, Any]] = {}
    for document in node_documents.values():
        for node in iter_nodes(document):
            references = node.get("styles")
            if not isinstance(references, dict):
                continue
            for field_name, raw_style_id in references.items():
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
                    style = node.get("style") or {}
                    if style.get("fontFamily"):
                        style_samples[style_id] = extract_text_style(style)
                elif style_type == "EFFECT":
                    effects = [
                        _parse_effect_entry(effect)
                        for effect in (node.get("effects") or [])
                        if isinstance(effect, dict) and effect.get("visible") is not False
                    ]
                    if effects:
                        style_samples[style_id] = {"effects": effects}

    catalogs: dict[str, list[dict[str, Any]]] = {"colorStyles": [], "textStyles": [], "effectStyles": []}
    seen_keys: set[str] = set()
    seen_names: dict[str, set[str]] = defaultdict(set)
    sorted_items = sorted(
        file_styles.items(),
        key=lambda item: (item[1].get("name", ""), 0 if normalize_node_id(item[0]) in style_samples else 1),
    )
    for raw_id, metadata in sorted_items:
        style_key = metadata.get("key", "")
        if style_key and style_key in seen_keys:
            continue
        if style_key:
            seen_keys.add(style_key)
        style_type = metadata.get("styleType", "")
        style_name = metadata.get("name", "")
        if style_name and style_name in seen_names[style_type]:
            continue
        if style_name:
            seen_names[style_type].add(style_name)
        style_id = normalize_node_id(raw_id)
        base = {
            "nodeId": style_id,
            "key": style_key,
            "name": style_name,
            "remote": metadata.get("remote", False),
        }
        sample = style_samples.get(style_id, {})
        if style_type == "FILL":
            hex_values = sample.get("hexValues", [])
            gradients = sample.get("gradientValues", [])
            catalogs["colorStyles"].append(
                {
                    **base,
                    "hex": hex_values[0] if hex_values else sample.get("hex"),
                    "gradient": gradients[0] if gradients else sample.get("gradient"),
                    "hexValues": hex_values,
                    "gradientValues": gradients,
                }
            )
        elif style_type == "TEXT":
            catalogs["textStyles"].append({**base, **sample})
        elif style_type == "EFFECT":
            catalogs["effectStyles"].append({**base, "effects": sample.get("effects", [])})
    return catalogs


def _collect_paint_style_sample(node: dict[str, Any], style_field_name: str) -> dict[str, Any]:
    hex_values: list[str] = []
    gradients: list[dict[str, Any]] = []
    for paint in _iter_style_paints(node, style_field_name):
        if paint.get("visible") is False:
            continue
        if paint.get("type") == "SOLID":
            hex_value = paint_to_hex(paint)
            if hex_value and not (len(hex_value) == 9 and hex_value.endswith("00")):
                hex_values.append(hex_value)
        gradient = parse_gradient_paint(paint)
        if gradient:
            gradients.append(gradient)
    sample: dict[str, Any] = {}
    if hex_values:
        sample["hexValues"] = hex_values
    if gradients:
        sample["gradientValues"] = gradients
    return sample


def _iter_style_paints(node: dict[str, Any], style_field_name: str) -> Iterator[dict[str, Any]]:
    for field in _paint_fields_for_style_ref(style_field_name):
        raw_value = node.get(field)
        if isinstance(raw_value, list):
            yield from (paint for paint in raw_value if isinstance(paint, dict))
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


class StyleParser:
    """Named and referenced style parsing family."""

    build_referenced_styles = staticmethod(_build_referenced_styles)
    parse_named_color_styles = staticmethod(_parse_named_color_styles)
    parse_named_effect_styles = staticmethod(_parse_named_effect_styles)
    parse_named_text_styles = staticmethod(_parse_named_text_styles)
