from __future__ import annotations

import json
import math
import re
import urllib.parse
from pathlib import Path
from typing import Any


GRADIENT_PAINT_TYPES = {
    "GRADIENT_LINEAR",
    "GRADIENT_RADIAL",
    "GRADIENT_ANGULAR",
    "GRADIENT_DIAMOND",
}


def resolve_figma_target(url: str | None, file_key: str | None, node_id: str | None) -> tuple[str, str]:
    parsed_key = file_key
    parsed_node = node_id

    if url:
        parsed = urllib.parse.urlparse(url)
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        for index, part in enumerate(parts):
            if part in {"file", "design", "proto"} and index + 1 < len(parts):
                parsed_key = parts[index + 1]
                break

        query = urllib.parse.parse_qs(parsed.query)
        node_values = query.get("node-id") or query.get("node_id")
        if node_values:
            parsed_node = node_values[0]

    if not parsed_key:
        raise ValueError("Missing Figma file key. Pass --url or --file-key.")
    if not parsed_node:
        raise ValueError("Missing Figma node id. Pass a frame URL with node-id or --node-id.")

    return parsed_key, normalize_node_id(parsed_node)

def normalize_node_id(value: str) -> str:
    decoded = urllib.parse.unquote(value).strip()
    return ";".join(_normalize_node_id_segment(segment) for segment in decoded.split(";"))

def _normalize_node_id_segment(segment: str) -> str:
    prefix = "I" if segment.startswith("I") else ""
    body = segment[1:] if prefix else segment
    if re.fullmatch(r"\d+-\d+", body):
        body = body.replace("-", ":")
    return prefix + body

def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return slug or "figma-handoff"

def iter_nodes(root: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        nodes.append(node)
        for child in node.get("children", []) or []:
            walk(child)

    walk(root)
    return nodes

def extract_text_style(style: dict[str, Any]) -> dict[str, Any]:
    return {
        "fontFamily": style.get("fontFamily"),
        "fontPostScriptName": style.get("fontPostScriptName"),
        "fontWeight": style.get("fontWeight"),
        "fontSize": round_number(style.get("fontSize")),
        "italic": style.get("italic"),
        "lineHeightPx": round_number(style.get("lineHeightPx")),
        "lineHeightPercent": round_number(style.get("lineHeightPercent")),
        "lineHeightPercentFontSize": round_number(style.get("lineHeightPercentFontSize")),
        "lineHeightUnit": style.get("lineHeightUnit"),
        "letterSpacing": round_number(style.get("letterSpacing")),
        "letterSpacingUnit": style.get("letterSpacingUnit"),
        "paragraphSpacing": round_number(style.get("paragraphSpacing")),
        "textCase": style.get("textCase"),
        "textAlignHorizontal": style.get("textAlignHorizontal"),
        "textAlignVertical": style.get("textAlignVertical"),
        "textAutoResize": style.get("textAutoResize"),
        "textDecoration": style.get("textDecoration"),
        "textTruncation": style.get("textTruncation"),
        "maxLines": style.get("maxLines"),
    }

def _color_dict_to_hex(color: dict[str, Any]) -> str | None:
    if not all(k in color for k in ("r", "g", "b")):
        return None
    return _color_to_hex(color["r"], color["g"], color["b"], color.get("a", 1))

def parse_gradient_paint(paint: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(paint, dict) or paint.get("visible") is False:
        return None
    paint_type = paint.get("type")
    if paint_type not in GRADIENT_PAINT_TYPES:
        return None

    paint_alpha = _alpha_value(paint.get("opacity", 1))
    stops: list[dict[str, Any]] = []
    for stop in paint.get("gradientStops", []) or []:
        if not isinstance(stop, dict):
            continue
        color = stop.get("color")
        hex_value = None
        if isinstance(color, dict) and all(k in color for k in ("r", "g", "b")):
            stop_alpha = _alpha_value(color.get("a", 1)) * paint_alpha
            hex_value = _color_to_hex(color["r"], color["g"], color["b"], stop_alpha)
        stops.append({
            "position": round_number(stop.get("position")),
            "hex": hex_value,
        })

    handles: list[dict[str, Any]] = []
    for handle in paint.get("gradientHandlePositions", []) or []:
        if not isinstance(handle, dict):
            continue
        handles.append({
            "x": round_number(handle.get("x")),
            "y": round_number(handle.get("y")),
        })

    result: dict[str, Any] = {
        "type": paint_type,
        "stops": stops,
        "handlePositions": handles,
    }
    angle_degrees = _linear_gradient_angle_degrees(handles) if paint_type == "GRADIENT_LINEAR" else None
    if angle_degrees is not None:
        result["angleDegrees"] = angle_degrees
    return result


def _linear_gradient_angle_degrees(handles: list[dict[str, Any]]) -> int | float | None:
    if len(handles) < 2:
        return None
    start = handles[0]
    end = handles[1]
    if not all(is_number(point.get(axis)) for point in (start, end) for axis in ("x", "y")):
        return None
    dx = float(end["x"]) - float(start["x"])
    dy = float(end["y"]) - float(start["y"])
    if abs(dx) < 0.000001 and abs(dy) < 0.000001:
        return None
    return round_number((math.degrees(math.atan2(dx, -dy)) + 360) % 360)

def paint_to_hex(paint: dict[str, Any]) -> str | None:
    color = paint.get("color")
    if not isinstance(color, dict):
        return None
    if not all(k in color for k in ("r", "g", "b")):
        return None
    layer_opacity = _alpha_value(paint.get("opacity", 1))
    color_alpha = _alpha_value(color.get("a", 1))
    return _color_to_hex(color["r"], color["g"], color["b"], layer_opacity * color_alpha)

def _color_to_hex(red: Any, green: Any, blue: Any, alpha: Any = 1) -> str | None:
    try:
        r = clamp_color(red)
        g = clamp_color(green)
        b = clamp_color(blue)
        a = _alpha_value(alpha)
    except (TypeError, ValueError):
        return None
    if a >= 0.995:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{clamp_color(a):02X}"

def _alpha_value(value: Any) -> float:
    if value is None:
        return 1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0

def clamp_color(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(255, round(numeric * 255)))

def round_number(value: Any) -> int | float | None:
    if not is_number(value):
        return None
    if abs(value - round(value)) < 0.001:
        return int(round(value))
    return round(value, 2)

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def format_number(value: Any) -> str:
    rounded = round_number(value)
    return str(rounded)

def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
