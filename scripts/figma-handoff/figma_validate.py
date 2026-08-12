#!/usr/bin/env python3
"""design-summary.json 검증기 + 충실도 커버리지 리포트.

두 가지를 제공한다:
- validate_summary(summary): 스키마/불변식 위반 목록 (빈 리스트 = 통과)
- coverage_report(summary): 1:1 충실도 정량 지표 (이미지/asset 복구율, 필드 채움, 경고 분류)

네트워크 없이 동작하며, 오프라인 테스트·라이브 스모크·CLI에서 공용으로 쓴다.
CLI: python3 figma_validate.py <design-summary.json>  (위반 있으면 exit 1)
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

_HEX_RE = re.compile(r"^#[0-9A-F]{6}([0-9A-F]{2})?$")
_REQUIRED_TOP_KEYS = (
    "meta",
    "screens",
    "flowEdges",
    "flowInteractions",
    "designTokens",
    "components",
    "componentBlueprints",
    "colors",
    "gradients",
    "textStyles",
    "textRuns",
    "effects",
    "layoutMetrics",
    "layoutNodes",
    "assetCandidates",
    "assetInventory",
    "warnings",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_summary(summary: dict[str, Any]) -> list[str]:
    """구조/불변식 위반을 문자열 목록으로 반환. 빈 리스트면 통과."""
    problems: list[str] = []

    def require(cond: bool, message: str) -> None:
        if not cond:
            problems.append(message)

    require(isinstance(summary, dict), "summary is not an object")
    if not isinstance(summary, dict):
        return problems

    for key in _REQUIRED_TOP_KEYS:
        require(key in summary, f"missing top-level key: {key}")

    meta = summary.get("meta", {})
    require(isinstance(meta, dict) and bool(meta.get("fileKey")), "meta.fileKey missing")
    require(isinstance(meta, dict) and bool(meta.get("startNodeId")), "meta.startNodeId missing")
    require(isinstance(meta, dict) and bool(meta.get("generatedAt")), "meta.generatedAt missing")

    for i, screen in enumerate(summary.get("screens", []) or []):
        require(bool(screen.get("id")), f"screens[{i}].id missing")

    for i, color in enumerate(summary.get("colors", []) or []):
        hex_value = color.get("hex")
        require(
            isinstance(hex_value, str) and bool(_HEX_RE.match(hex_value)),
            f"colors[{i}].hex invalid: {hex_value!r}",
        )

    for i, gradient in enumerate(summary.get("gradients", []) or []):
        for j, stop in enumerate(gradient.get("stops", []) or []):
            pos = stop.get("position")
            if pos is not None:
                require(
                    _is_number(pos) and -0.001 <= pos <= 1.001,
                    f"gradients[{i}].stops[{j}].position out of [0,1]: {pos!r}",
                )

    for i, node in enumerate(summary.get("layoutNodes", []) or []):
        require(bool(node.get("id")), f"layoutNodes[{i}].id missing")
        require("type" in node, f"layoutNodes[{i}].type missing")
        opacity = node.get("opacity")
        if opacity is not None:
            require(
                _is_number(opacity) and -0.001 <= opacity <= 1.001,
                f"layoutNodes[{i}].opacity out of [0,1]: {opacity!r}",
            )
        stroke = node.get("strokeWeight")
        if stroke is not None:
            require(_is_number(stroke) and stroke >= 0, f"layoutNodes[{i}].strokeWeight invalid: {stroke!r}")
        box = node.get("absoluteBoundingBox")
        if box is not None:
            require(
                isinstance(box, dict) and all(_is_number(box.get(k)) for k in ("x", "y", "width", "height")),
                f"layoutNodes[{i}].absoluteBoundingBox malformed",
            )

    for i, style in enumerate(summary.get("textStyles", []) or []):
        size = style.get("fontSize")
        if size is not None:
            require(_is_number(size) and size > 0, f"textStyles[{i}].fontSize invalid: {size!r}")

    for i, asset in enumerate(summary.get("assetCandidates", []) or []):
        require(bool(asset.get("id")), f"assetCandidates[{i}].id missing")

    for i, comp in enumerate(summary.get("components", []) or []):
        require(bool(comp.get("componentId")), f"components[{i}].componentId missing")
        count = comp.get("usageCount")
        require(
            _is_number(count) and count >= 1,
            f"components[{i}].usageCount invalid: {count!r}",
        )

    for i, bp in enumerate(summary.get("componentBlueprints", []) or []):
        require(bool(bp.get("componentId")), f"componentBlueprints[{i}].componentId missing")
        require(isinstance(bp.get("structure"), list), f"componentBlueprints[{i}].structure not a list")

    for i, icon in enumerate(summary.get("assetInventory", []) or []):
        require(bool(icon.get("dedupKey")), f"assetInventory[{i}].dedupKey missing")
        count = icon.get("usageCount")
        require(
            _is_number(count) and count >= 1,
            f"assetInventory[{i}].usageCount invalid: {count!r}",
        )

    tokens = summary.get("designTokens", {})
    require(isinstance(tokens, dict) and "variables" in tokens, "designTokens.variables missing")

    return problems


def coverage_report(summary: dict[str, Any]) -> dict[str, Any]:
    """1:1 충실도 정량 지표. render 후(assetPath 존재)면 복구율까지 의미가 있다."""
    layout_nodes = summary.get("layoutNodes", []) or []

    def count_with(field: str) -> int:
        return sum(1 for n in layout_nodes if n.get(field) is not None)

    assets = summary.get("assetCandidates", []) or []
    uniq: dict[str, dict[str, Any]] = {}
    for asset in assets:
        aid = asset.get("id")
        if aid and aid not in uniq:
            uniq[aid] = asset
    asset_values = list(uniq.values())
    image_fills = [a for a in asset_values if a.get("imageRefs")]

    warnings = summary.get("warnings", []) or []
    warn_asset = sum(1 for w in warnings if "not renderable standalone" in w)
    warn_vars = sum(1 for w in warnings if "Variables" in w or "variables" in w)

    variables = summary.get("designTokens", {}).get("variables", {}).get("variables", []) or []

    components = summary.get("components", []) or []
    inventory = summary.get("assetInventory", []) or []

    return {
        "screens": len(summary.get("screens", []) or []),
        "components": {
            "total": len(components),
            "instances": sum(c.get("usageCount", 0) for c in components),
            "withVariant": sum(1 for c in components if c.get("variantProperties")),
            "blueprints": len(summary.get("componentBlueprints", []) or []),
        },
        "layoutNodes": {
            "total": len(layout_nodes),
            "withOpacity": count_with("opacity"),
            "withStrokeWeight": count_with("strokeWeight"),
            "withRotation": count_with("rotation"),
            "withRenderBounds": count_with("absoluteRenderBounds"),
            "withConstraints": count_with("constraints"),
        },
        "colors": len(summary.get("colors", []) or []),
        "gradients": len(summary.get("gradients", []) or []),
        "textStyles": len(summary.get("textStyles", []) or []),
        "textRuns": len(summary.get("textRuns", []) or []),
        "effects": len(summary.get("effects", []) or []),
        "assets": {
            "total": len(asset_values),
            "withPath": sum(1 for a in asset_values if a.get("assetPath")),
            "imageFillTotal": len(image_fills),
            "imageFillWithPath": sum(1 for a in image_fills if a.get("assetPath")),
            "withFallbackChain": sum(1 for a in asset_values if a.get("renderFallbackIds")),
            "withNearestComponent": sum(1 for a in asset_values if a.get("nearestComponentName")),
        },
        "iconInventory": {
            "unique": len(inventory),
            "nameUnclear": sum(1 for i in inventory if i.get("nameUnclear")),
            "namedByComponent": sum(1 for i in inventory if i.get("nameUnclear") and i.get("nearestComponentName")),
        },
        "variables": {
            "count": len(variables),
            "enterpriseAvailable": len(variables) > 0,
        },
        "warnings": {
            "total": len(warnings),
            "assetNotRenderable": warn_asset,
            "variables": warn_vars,
            "other": len(warnings) - warn_asset - warn_vars,
        },
    }


def format_report(problems: list[str], coverage: dict[str, Any]) -> str:
    lines: list[str] = ["# figma-handoff 검증 리포트", ""]
    if problems:
        lines.append(f"## ❌ 스키마 위반 {len(problems)}건")
        lines.extend(f"- {p}" for p in problems)
    else:
        lines.append("## ✅ 스키마 위반 없음")
    lines.append("")
    lines.append("## 충실도 커버리지")
    a = coverage["assets"]
    ln = coverage["layoutNodes"]
    w = coverage["warnings"]
    img_pct = (a["imageFillWithPath"] * 100 // a["imageFillTotal"]) if a["imageFillTotal"] else 100
    asset_pct = (a["withPath"] * 100 // a["total"]) if a["total"] else 0
    c = coverage["components"]
    lines.extend([
        f"- 화면(screens): {coverage['screens']}",
        f"- 컴포넌트: {c['total']}종 (인스턴스 {c['instances']}개 / variant 보유 {c['withVariant']}종 / 청사진 {c['blueprints']}개)",
        f"- layoutNodes: {ln['total']} (opacity {ln['withOpacity']} / stroke {ln['withStrokeWeight']} "
        f"/ rotation {ln['withRotation']} / renderBounds {ln['withRenderBounds']})",
        f"- 색 {coverage['colors']} / 그라데이션 {coverage['gradients']} / 텍스트 {coverage['textStyles']} "
        f"/ textRun {coverage['textRuns']} / effect {coverage['effects']}",
        f"- 이미지 fill 복구: {a['imageFillWithPath']}/{a['imageFillTotal']} ({img_pct}%)",
        f"- 전체 asset 복구: {a['withPath']}/{a['total']} ({asset_pct}%), fallback 체인 보유 {a['withFallbackChain']}",
        f"- 고유 아이콘: {coverage['iconInventory']['unique']}개 (이름불명확 {coverage['iconInventory']['nameUnclear']} / "
        f"그중 컴포넌트명 복구 {coverage['iconInventory']['namedByComponent']}), asset의 컴포넌트 연결 {a['withNearestComponent']}",
        f"- variables: {coverage['variables']['count']} (Enterprise 접근 {'O' if coverage['variables']['enterpriseAvailable'] else 'X'})",
        f"- warnings: 총 {w['total']} (asset 미렌더 {w['assetNotRenderable']} / variables {w['variables']} / 기타 {w['other']})",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 figma_validate.py <design-summary.json>", file=sys.stderr)
        return 2
    try:
        summary = json.loads(open(argv[1], encoding="utf-8").read())
    except (OSError, ValueError) as error:
        print(f"ERROR: cannot read summary: {error}", file=sys.stderr)
        return 2
    problems = validate_summary(summary)
    print(format_report(problems, coverage_report(summary)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
