"""오프라인 충실도 하네스.

모든 까다로운 케이스(회전=라디안, opacity, stroke, mask, blendMode, 이미지 fill,
벡터+조상 폴백, 그라데이션 각도, 변수 alias, 텍스트 run/단위)를 담은 합성 노드 트리를
실제 파이프라인(build_summary)에 통과시킨 뒤, figma_validate로 스키마·충실도를 조인다.
네트워크를 쓰지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

import unittest

from figma_report import build_summary, render_markdown
from figma_coverage import coverage_report
from figma_summary_validate import validate_summary


def _fixture_documents() -> dict[str, dict]:
    screen = {
        "id": "1:1",
        "name": "Screen",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 375, "height": 812},
        "layoutMode": "VERTICAL",
        "counterAxisAlignContent": "AUTO",
        "clipsContent": True,
        "children": [
            {
                "id": "1:2",
                "name": "Title",
                "type": "TEXT",
                "characters": "Hello",
                "characterStyleOverrides": [0, 1, 1, 0],
                "styleOverrideTable": {"1": {"fontWeight": 400}},
                "style": {
                    "fontFamily": "Pretendard",
                    "fontPostScriptName": "Pretendard-Bold",
                    "fontWeight": 700,
                    "fontSize": 20,
                    "italic": True,
                    "lineHeightPercentFontSize": 140,
                    "lineHeightUnit": "FONT_SIZE_%",
                    "letterSpacing": -0.4,
                    "letterSpacingUnit": "PERCENT",
                    "textAlignHorizontal": "CENTER",
                    "textAlignVertical": "TOP",
                    "textAutoResize": "HEIGHT",
                },
                "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
            },
            {
                "id": "1:3",
                "name": "Overlay",
                "type": "RECTANGLE",
                "opacity": 0.35,
                "blendMode": "MULTIPLY",
                "isMask": False,
                "rotation": 3.14,
                "size": {"x": 100, "y": 50},
                "relativeTransform": [[1, 0, 10], [0, 1, 20]],
                "strokeWeight": 0.99,
                "strokeAlign": "INSIDE",
                "individualStrokeWeights": {"top": 1, "right": 0, "bottom": 0.5, "left": 0},
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
                "absoluteRenderBounds": {"x": -4, "y": -4, "width": 108, "height": 58},
                "fills": [{"type": "SOLID", "opacity": 0.8, "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                "strokes": [{"type": "SOLID", "color": {"r": 0.5, "g": 0.5, "b": 0.5, "a": 1}}],
                "effects": [
                    {
                        "type": "DROP_SHADOW",
                        "color": {"r": 0, "g": 0, "b": 0, "a": 0.25},
                        "offset": {"x": 0, "y": 2},
                        "radius": 8,
                        "spread": 0,
                        "visible": True,
                    }
                ],
            },
            {
                "id": "1:4",
                "name": "Avatar",
                "type": "RECTANGLE",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 32, "height": 32},
                "fills": [{"type": "IMAGE", "imageRef": "abc123"}],
            },
            {
                "id": "1:5",
                "name": "Gradient",
                "type": "RECTANGLE",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 100},
                "fills": [
                    {
                        "type": "GRADIENT_LINEAR",
                        "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
                        "gradientStops": [
                            {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                            {"position": 1, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
                        ],
                    }
                ],
            },
            {
                "id": "1:6",
                "name": "IconBox",
                "type": "INSTANCE",
                "children": [
                    {
                        "id": "1:7",
                        "name": "IconLeaf",
                        "type": "VECTOR",
                        "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                    }
                ],
            },
            {
                "id": "1:9",
                "name": "Hidden",
                "type": "RECTANGLE",
                "visible": False,
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 20},
                "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}}],
            },
            {
                "id": "1:8",
                "name": "CTA",
                "type": "RECTANGLE",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 48},
                "fills": [
                    {
                        "type": "SOLID",
                        "color": {"r": 0, "g": 1, "b": 0, "a": 1},
                        "boundVariables": {"color": {"id": "var-primary"}},
                    }
                ],
            },
        ],
    }
    return {"1:1": screen}


def _fixture_variables() -> dict:
    return {
        "meta": {
            "variableCollections": {
                "colors": {
                    "id": "colors",
                    "name": "Colors",
                    "modes": [{"modeId": "mode", "name": "Default"}],
                    "defaultModeId": "mode",
                }
            },
            "variables": {
                "var-primary": {
                    "id": "var-primary",
                    "name": "Primary",
                    "resolvedType": "COLOR",
                    "variableCollectionId": "colors",
                    "valuesByMode": {"mode": {"r": 0, "g": 1, "b": 0, "a": 1}},
                }
            },
        }
    }


class FidelityHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = build_summary(
            file_key="FILE123",
            start_node_id="1:1",
            source_url="https://figma.com/design/FILE123/x?node-id=1-1",
            node_documents=_fixture_documents(),
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables=_fixture_variables(),
            file_styles={},
            warnings=[],
        )

    def test_summary_passes_schema_validation(self) -> None:
        self.assertEqual(validate_summary(self.summary), [])

    def test_visual_fidelity_fields_surfaced(self) -> None:
        overlay = next(n for n in self.summary["layoutNodes"] if n.get("name") == "Overlay")
        self.assertEqual(overlay["opacity"], 0.35)
        self.assertEqual(overlay["blendMode"], "MULTIPLY")
        self.assertEqual(overlay["rotation"], 3.14)
        self.assertEqual(overlay["strokeWeight"], 0.99)
        self.assertEqual(overlay["strokeAlign"], "INSIDE")
        self.assertEqual(overlay["size"], {"x": 100, "y": 50})
        self.assertIn("absoluteRenderBounds", overlay)
        self.assertEqual(overlay["individualStrokeWeights"]["bottom"], 0.5)

    def test_node_visibility_surfaced(self) -> None:
        hidden = next(n for n in self.summary["layoutNodes"] if n.get("name") == "Hidden")
        self.assertEqual(hidden["visible"], False)
        overlay = next(n for n in self.summary["layoutNodes"] if n.get("name") == "Overlay")
        self.assertNotIn("visible", overlay)

    def test_text_fields_and_runs(self) -> None:
        title = next(s for s in self.summary["textStyles"] if s.get("italic"))
        self.assertEqual(title["textAlignVertical"], "TOP")
        self.assertEqual(title["textAutoResize"], "HEIGHT")
        self.assertEqual(title["lineHeightPercentFontSize"], 140)
        run = self.summary["textRuns"][0]
        self.assertEqual(run["text"], "el")
        self.assertEqual(run["resolvedStyle"]["fontWeight"], 400)

    def test_gradient_and_color_and_variable(self) -> None:
        gradient = self.summary["gradients"][0]
        self.assertEqual(gradient["type"], "GRADIENT_LINEAR")
        self.assertEqual(gradient["angleDegrees"], 135)
        green = next(c for c in self.summary["colors"] if c["hex"] == "#00FF00")
        self.assertIn("Colors/Primary", green["boundVariableNames"])

    def test_asset_split_and_fallback(self) -> None:
        by_name = {a["name"]: a for a in self.summary["assetCandidates"]}
        self.assertIn("abc123", by_name["Avatar"]["imageRefs"])
        icon = by_name["IconLeaf"]
        fallback_ids = [f["id"] for f in icon.get("renderFallbackIds", [])]
        self.assertIn("1:6", fallback_ids)  # 조상 IconBox로 폴백
        self.assertNotIn("1:1", fallback_ids)  # 화면 프레임은 제외

    def test_coverage_report_numbers(self) -> None:
        cov = coverage_report(self.summary)
        self.assertEqual(cov["assets"]["imageFillTotal"], 1)
        self.assertGreaterEqual(cov["assets"]["withFallbackChain"], 1)
        self.assertGreaterEqual(cov["layoutNodes"]["withOpacity"], 1)
        self.assertGreaterEqual(cov["layoutNodes"]["withRotation"], 1)
        self.assertGreaterEqual(cov["layoutNodes"]["withRenderBounds"], 1)
        self.assertTrue(cov["variables"]["metadataAvailable"])


class ComponentCatalogTests(unittest.TestCase):
    """인스턴스/컴포넌트 정체성이 summary에 보존되는지 (이전엔 버려지던 정보)."""

    def _documents(self) -> dict[str, dict]:
        def instance(node_id: str, name: str, cid: str, variant: str) -> dict:
            return {
                "id": node_id,
                "name": name,
                "type": "INSTANCE",
                "componentId": cid,
                "componentProperties": {
                    "type": {"value": variant, "type": "VARIANT"},
                    "label": {"value": "x", "type": "TEXT"},
                },
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 40},
            }

        return {
            "1:1": {
                "id": "1:1",
                "name": "ScreenA",
                "type": "FRAME",
                "children": [
                    instance("1:10", "Card", "10:100", "가로형"),
                    instance("1:11", "Card", "10:100", "가로형"),
                    instance("1:12", "Chip", "20:200", "on"),
                ],
            },
            "2:1": {
                "id": "2:1",
                "name": "ScreenB",
                "type": "FRAME",
                "children": [
                    instance("2:10", "Card", "10-100", "세로형"),
                    # file components 맵에 없는 컴포넌트 → name은 인스턴스 이름으로 폴백.
                    {
                        "id": "2:11",
                        "name": "Weird Vector",
                        "type": "INSTANCE",
                        "componentId": "30:300",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 20, "height": 20},
                    },
                    # componentId 없는 인스턴스(detached 등) → 카탈로그에서 제외.
                    {"id": "2:12", "name": "Detached", "type": "INSTANCE"},
                ],
            },
        }

    def _component_index(self) -> dict:
        return {
            "components": {
                "10:100": {"name": "Card/가로형", "componentSetId": "10:1", "remote": False},
                "20:200": {"name": "Chip", "remote": True, "description": "선택 칩"},
            },
            "componentSets": {"10:1": {"name": "Card"}},
        }

    def setUp(self) -> None:
        self.summary = build_summary(
            file_key="FILE123",
            start_node_id="1:1",
            source_url=None,
            node_documents=self._documents(),
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables={},
            file_styles={},
            warnings=[],
            component_index=self._component_index(),
        )

    def test_schema_passes(self) -> None:
        self.assertEqual(validate_summary(self.summary), [])

    def test_catalog_dedup_and_usage(self) -> None:
        catalog = {c["componentId"]: c for c in self.summary["components"]}
        # 두 화면에 걸친 Card 인스턴스 3개(colon/dash 표기 혼용)가 하나로 묶인다.
        card = catalog["10:100"]
        self.assertEqual(card["usageCount"], 3)
        self.assertEqual(sorted(card["usedInScreens"]), ["1:1", "2:1"])
        self.assertEqual(card["name"], "Card/가로형")
        self.assertEqual(card["componentSetName"], "Card")
        self.assertEqual(card["variantProperties"], {"type": "가로형"})
        # 사용 횟수 내림차순 정렬(work-list).
        self.assertEqual(self.summary["components"][0]["componentId"], "10:100")

    def test_remote_and_missing_meta(self) -> None:
        chip = next(c for c in self.summary["components"] if c["componentId"] == "20:200")
        self.assertTrue(chip["remote"])
        self.assertEqual(chip["description"], "선택 칩")

    def test_per_node_identity_surfaced(self) -> None:
        node = next(n for n in self.summary["layoutNodes"] if n["id"] == "1:10")
        self.assertEqual(node["componentId"], "10:100")
        self.assertEqual(node["componentProperties"], {"type": "가로형", "label": "x"})

    def test_orphan_falls_back_and_missing_id_ignored(self) -> None:
        catalog = {c["componentId"]: c for c in self.summary["components"]}
        # 맵에 없는 컴포넌트: 이름은 인스턴스 이름으로 폴백, componentSet 정보는 없음.
        orphan = catalog["30:300"]
        self.assertEqual(orphan["name"], "Weird Vector")
        self.assertNotIn("componentSetName", orphan)
        self.assertNotIn("variantProperties", orphan)
        # componentId 없는 인스턴스는 어떤 카탈로그 항목도 만들지 않는다.
        self.assertEqual(len(self.summary["components"]), 3)

    def test_markdown_renders_component_worklist(self) -> None:
        md = render_markdown(self.summary)
        self.assertIn("## Components (usage order", md)
        self.assertIn("Card", md)  # variant 멤버는 componentSetName을 주 라벨로 노출
        self.assertIn("x3", md)  # 최상위 Card 사용횟수

    def test_coverage_counts_components(self) -> None:
        cov = coverage_report(self.summary)
        self.assertEqual(cov["components"]["total"], 3)
        self.assertEqual(cov["components"]["instances"], 5)
        self.assertEqual(cov["components"]["withVariant"], 2)


class AssetInventoryTests(unittest.TestCase):
    """고유 아이콘 dedup + 이름 없는 벡터의 컴포넌트명 backfill."""

    def _vector(self, node_id: str, name: str, color: dict) -> dict:
        return {
            "id": node_id,
            "name": name,
            "type": "VECTOR",
            "size": {"x": 24, "y": 24},
            "fills": [{"type": "SOLID", "color": color}],
        }

    def setUp(self) -> None:
        black = {"r": 0, "g": 0, "b": 0, "a": 1}
        blue = {"r": 0, "g": 0, "b": 1, "a": 1}
        documents = {
            "1:1": {
                "id": "1:1",
                "name": "Screen",
                "type": "FRAME",
                "children": [
                    # 이름 있는 컴포넌트 안의 generic 벡터 2개(동일 시그니처) → 한 항목으로 dedup.
                    {
                        "id": "1:10",
                        "name": "SearchButton",
                        "type": "INSTANCE",
                        "componentId": "40:400",
                        "children": [self._vector("1:11", "Vector", black)],
                    },
                    {
                        "id": "1:20",
                        "name": "SearchButton",
                        "type": "INSTANCE",
                        "componentId": "40:400",
                        "children": [self._vector("1:21", "Vector", black)],
                    },
                    # 컴포넌트 밖의 이름 명확한 벡터.
                    self._vector("1:30", "Logo", blue),
                ],
            }
        }
        self.summary = build_summary(
            file_key="FILE123",
            start_node_id="1:1",
            source_url=None,
            node_documents=documents,
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables={},
            file_styles={},
            warnings=[],
            component_index={"components": {"40:400": {"name": "Icon/Search"}}, "componentSets": {}},
        )

    def test_schema_passes(self) -> None:
        self.assertEqual(validate_summary(self.summary), [])

    def test_dedup_groups_identical_icons(self) -> None:
        inv = self.summary["assetInventory"]
        self.assertEqual(len(inv), 2)  # (동일 Vector 2개 → 1) + Logo
        vector_group = next(i for i in inv if i["nameUnclear"])
        self.assertEqual(vector_group["usageCount"], 2)
        self.assertEqual(sorted(vector_group["nodeIds"]), ["1:11", "1:21"])

    def test_generic_name_recovered_from_component(self) -> None:
        vector_group = next(i for i in self.summary["assetInventory"] if i["nameUnclear"])
        # 대표 이름이 generic("Vector") 대신 포함 컴포넌트 이름으로 복구.
        self.assertEqual(vector_group["name"], "Icon/Search")
        self.assertEqual(vector_group["nearestComponentName"], "Icon/Search")
        logo = next(i for i in self.summary["assetInventory"] if not i["nameUnclear"])
        self.assertEqual(logo["name"], "Logo")
        self.assertNotIn("nearestComponentName", logo)

    def test_asset_candidate_carries_nearest_component(self) -> None:
        by_id = {a["id"]: a for a in self.summary["assetCandidates"]}
        self.assertEqual(by_id["1:11"]["nearestComponentName"], "Icon/Search")
        self.assertNotIn("nearestComponentName", by_id["1:30"])

    def test_coverage_counts_icons(self) -> None:
        cov = coverage_report(self.summary)
        self.assertEqual(cov["iconInventory"]["unique"], 2)
        self.assertEqual(cov["iconInventory"]["nameUnclear"], 1)
        self.assertEqual(cov["iconInventory"]["namedByComponent"], 1)


class ComponentBlueprintTests(unittest.TestCase):
    """컴포넌트 청사진: 대표 선택 + 중첩 인스턴스 경계 + asset 바인딩."""

    def _documents(self) -> dict[str, dict]:
        rich_card = {
            "id": "1:10",
            "name": "Frame 1410104639",
            "type": "INSTANCE",
            "componentId": "50:500",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 335, "height": 450},
            "children": [
                {
                    "id": "1:11",
                    "name": "image",
                    "type": "RECTANGLE",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 335, "height": 225},
                    "fills": [{"type": "IMAGE", "imageRef": "photo-abc"}],
                },
                {"id": "1:12", "name": "title", "type": "TEXT", "characters": "낯선 도시에서 발견한 리듬"},
                {
                    "id": "1:13",
                    "name": "LeftActions",
                    "type": "FRAME",
                    "children": [
                        {"id": "1:14", "name": "avatar", "type": "VECTOR", "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}]},
                        {
                            "id": "1:15",
                            "name": "Icon/HeartToggle",
                            "type": "INSTANCE",
                            "componentId": "17:981",
                            "children": [
                                {"id": "1:16", "name": "heartGlyph", "type": "VECTOR", "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}}]},
                            ],
                        },
                        {"id": "1:17", "name": "Count", "type": "TEXT", "characters": "213"},
                    ],
                },
            ],
        }
        sparse_card = {
            "id": "2:10",
            "name": "Frame 1410104640",
            "type": "INSTANCE",
            "componentId": "50:500",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 335, "height": 450},
            "children": [
                {"id": "2:11", "name": "image", "type": "RECTANGLE", "fills": [{"type": "IMAGE", "imageRef": "photo-xyz"}]},
            ],
        }
        return {"1:1": {"id": "1:1", "name": "Page", "type": "FRAME", "children": [rich_card, sparse_card]}}

    def setUp(self) -> None:
        self.summary = build_summary(
            file_key="FILE123",
            start_node_id="1:1",
            source_url=None,
            node_documents=self._documents(),
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables={},
            file_styles={},
            warnings=[],
            component_index={"components": {"50:500": {"name": "Feed/Card"}}, "componentSets": {}},
        )

    def _card_blueprint(self) -> dict:
        return next(b for b in self.summary["componentBlueprints"] if b["componentId"] == "50:500")

    def test_schema_passes(self) -> None:
        self.assertEqual(validate_summary(self.summary), [])

    def test_representative_is_richest_instance(self) -> None:
        bp = self._card_blueprint()
        self.assertEqual(bp["representativeInstanceId"], "1:10")  # 자식 많은 쪽
        self.assertEqual(bp["usageCount"], 2)
        self.assertEqual(bp["name"], "Feed/Card")
        self.assertEqual(bp["size"], {"w": 335, "h": 450})

    def test_structure_and_text_captured(self) -> None:
        names = [item["name"] for item in self._card_blueprint()["structure"]]
        self.assertEqual(names, ["image", "title", "LeftActions", "avatar", "Icon/HeartToggle", "Count"])
        title = next(i for i in self._card_blueprint()["structure"] if i["name"] == "title")
        self.assertEqual(title["text"], "낯선 도시에서 발견한 리듬")

    def test_nested_instance_is_boundary(self) -> None:
        struct = self._card_blueprint()["structure"]
        heart = next(i for i in struct if i["name"] == "Icon/HeartToggle")
        self.assertEqual(heart["componentId"], "17:981")  # 참조로만
        # 중첩 인스턴스 내부(heartGlyph)는 카드 청사진에 펼쳐지지 않는다.
        self.assertNotIn("heartGlyph", [i["name"] for i in struct])

    def test_asset_dedup_key_bound(self) -> None:
        image = next(i for i in self._card_blueprint()["structure"] if i["name"] == "image")
        self.assertTrue(image.get("assetDedupKey", "").startswith("img:"))

    def test_coverage_counts_blueprints(self) -> None:
        cov = coverage_report(self.summary)
        # 카드(50:500) + HeartToggle(17:981, heartGlyph 자식 보유) = 2
        self.assertEqual(cov["components"]["blueprints"], 2)


if __name__ == "__main__":
    unittest.main()
