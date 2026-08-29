from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

import json
import tempfile
import unittest
import urllib.parse
from types import SimpleNamespace

from figma_api import _retry_delay_seconds
from figma_flow_fetch import FigmaFlowFetcher, _chunk_node_ids
from figma_render import FigmaRenderer
from figma_analyze import (
    summarize_colors,
    summarize_flow_interactions,
    summarize_gradients,
    summarize_layout_nodes,
    summarize_layout_metrics,
    summarize_text_styles,
    summarize_text_runs,
)
from figma_parse import build_referenced_styles, parse_variables
from figma_report import _format_gradient, build_manifest, build_summary, render_markdown
from figma_util import paint_to_hex, parse_gradient_paint, resolve_figma_target, round_number


class FigmaHandoffRegressionTests(unittest.TestCase):
    def test_resolve_url_and_alpha_composition(self) -> None:
        file_key, node_id = resolve_figma_target(
            "https://www.figma.com/design/FILE123/Name?node-id=10-20&m=dev",
            None,
            None,
        )

        self.assertEqual(file_key, "FILE123")
        self.assertEqual(node_id, "10:20")
        _, complex_node_id = resolve_figma_target(
            "https://www.figma.com/design/FILE123/Name?node-id=I422-10795%3B422-10793",
            None,
            None,
        )
        self.assertEqual(complex_node_id, "I422:10795;422:10793")
        self.assertEqual(
            paint_to_hex({
                "type": "SOLID",
                "opacity": 0.5,
                "color": {"r": 1, "g": 0, "b": 0, "a": 0.5},
            }),
            "#FF000040",
        )
        self.assertIsNone(round_number(True))

    def test_gradient_paint_and_summary_preserve_stops_and_handles(self) -> None:
        paint = {
            "type": "GRADIENT_LINEAR",
            "opacity": 0.5,
            "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
            "gradientStops": [
                {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 0.5}},
                {"position": 1, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
            ],
        }

        gradient = parse_gradient_paint(paint)
        self.assertIsNotNone(gradient)
        self.assertEqual(gradient["stops"][0]["hex"], "#FF000040")
        self.assertEqual(gradient["stops"][1]["hex"], "#0000FF80")
        self.assertEqual(gradient["angleDegrees"], 135)

        summary = summarize_gradients([{"name": "Box", "fills": [paint]}])
        self.assertEqual(summary[0]["count"], 1)
        self.assertEqual(summary[0]["sources"], ["Box (fills)"])
        self.assertIn("angle=135deg", _format_gradient(summary[0]))

    def test_text_and_layout_fields_include_implementation_critical_values(self) -> None:
        text_summary = summarize_text_styles([
            {
                "type": "TEXT",
                "name": "Title",
                "characters": "Hello",
                "style": {
                    "fontFamily": "Pretendard",
                    "fontPostScriptName": "Pretendard-Bold",
                    "fontWeight": 700,
                    "fontSize": 20,
                    "lineHeightPercentFontSize": 140,
                    "lineHeightUnit": "FONT_SIZE_%",
                    "letterSpacing": -0.4,
                    "letterSpacingUnit": "PERCENT",
                    "paragraphSpacing": 8,
                    "textDecoration": "UNDERLINE",
                    "textAlignHorizontal": "CENTER",
                },
            }
        ])

        self.assertEqual(text_summary[0]["letterSpacingUnit"], "PERCENT")
        self.assertEqual(text_summary[0]["lineHeightPercentFontSize"], 140)
        self.assertEqual(text_summary[0]["textDecoration"], "UNDERLINE")

        layout_summary = summarize_layout_metrics([
            {
                "layoutMode": "HORIZONTAL",
                "layoutWrap": "WRAP",
                "counterAxisSpacing": 12,
                "primaryAxisSizingMode": "AUTO",
                "counterAxisSizingMode": "FIXED",
                "layoutPositioning": "ABSOLUTE",
                "minWidth": 100,
                "maxHeight": 240,
            }
        ])

        self.assertEqual(layout_summary["counterAxisSpacing"][0]["value"], "12")
        self.assertEqual(layout_summary["primaryAxisSizingMode"][0]["value"], "AUTO")
        self.assertEqual(layout_summary["layoutPositioning"][0]["value"], "ABSOLUTE")

        layout_nodes = summarize_layout_nodes([
            {
                "id": "1:1",
                "name": "Root",
                "type": "FRAME",
                "layoutMode": "VERTICAL",
                "children": [
                    {
                        "id": "1:2",
                        "name": "Child",
                        "type": "FRAME",
                        "layoutAlign": "STRETCH",
                        "layoutGrow": 1,
                        "constraints": {"horizontal": "SCALE", "vertical": "MIN"},
                    }
                ],
            }
        ])
        self.assertEqual(layout_nodes[1]["parentId"], "1:1")
        self.assertEqual(layout_nodes[1]["layoutAlign"], "STRETCH")
        self.assertEqual(layout_nodes[1]["constraints"]["horizontal"], "SCALE")

        text_runs = summarize_text_runs([
            {
                "id": "1:3",
                "name": "Mixed",
                "type": "TEXT",
                "characters": "abcd",
                "style": {"fontFamily": "Pretendard", "fontSize": 14},
                "characterStyleOverrides": [0, 1, 1, 0],
                "styleOverrideTable": {"1": {"fontWeight": 700}},
            }
        ])
        self.assertEqual(text_runs[0]["range"], {"start": 1, "end": 3})
        self.assertEqual(text_runs[0]["text"], "bc")
        self.assertEqual(text_runs[0]["resolvedStyle"]["fontWeight"], 700)

    def test_summary_reports_variable_names_and_gradients(self) -> None:
        node = {
            "id": "1:2",
            "name": "Screen",
            "type": "FRAME",
            "absoluteBoundingBox": {"width": 100, "height": 200},
            "children": [
                {
                    "id": "1:3",
                    "name": "CTA",
                    "type": "RECTANGLE",
                    "fills": [
                        {
                            "type": "SOLID",
                            "color": {"r": 0, "g": 1, "b": 0, "a": 1},
                        },
                        {
                            "type": "GRADIENT_LINEAR",
                            "gradientStops": [
                                {"position": 0, "color": {"r": 0, "g": 1, "b": 0, "a": 1}},
                                {"position": 1, "color": {"r": 0, "g": 0, "b": 0, "a": 0}},
                            ],
                        },
                    ],
                    "boundVariables": {
                        "fills": [{"type": "VARIABLE_ALIAS", "id": "var-green"}],
                    },
                }
            ],
        }
        variables = {
            "meta": {
                "variableCollections": {
                    "collection": {
                        "id": "colors",
                        "name": "Colors",
                        "modes": [],
                        "defaultModeId": "",
                    }
                },
                "variables": {
                    "var-green": {
                        "id": "var-green",
                        "name": "Primary",
                        "resolvedType": "COLOR",
                        "variableCollectionId": "colors",
                        "valuesByMode": {},
                    }
                },
            }
        }

        summary = build_summary(
            file_key="FILE123",
            start_node_id="1:2",
            source_url=None,
            node_documents={"1:2": node},
            flow_edges=[],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables=variables,
            file_styles={},
            warnings=[],
        )

        self.assertEqual(summary["colors"][0]["boundVariableNames"], ["Colors/Primary"])
        self.assertEqual(summary["gradients"][0]["type"], "GRADIENT_LINEAR")
        markdown = render_markdown(summary)
        self.assertIn("## Gradient Candidates", markdown)
        self.assertIn("Colors/Primary", markdown)

    def test_variable_aliases_and_bound_variable_variants_are_resolved(self) -> None:
        variables = {
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
                    "var-primitive": {
                        "id": "var-primitive",
                        "name": "Primitive/Blue",
                        "resolvedType": "COLOR",
                        "variableCollectionId": "colors",
                        "valuesByMode": {"mode": {"r": 0, "g": 0, "b": 1, "a": 1}},
                    },
                    "var-semantic": {
                        "id": "var-semantic",
                        "name": "Semantic/Primary",
                        "resolvedType": "COLOR",
                        "variableCollectionId": "colors",
                        "valuesByMode": {
                            "mode": {"type": "VARIABLE_ALIAS", "id": "var-primitive"}
                        },
                    },
                },
            }
        }
        parsed = parse_variables(variables)
        semantic_value = parsed["variables"][1]["valuesByMode"]["mode"]
        self.assertEqual(semantic_value["aliasName"], "Colors/Primitive/Blue")
        self.assertEqual(semantic_value["resolvedHex"], "#0000FF")

        colors = summarize_colors(
            [
                {
                    "name": "Box",
                    "fills": [
                        {
                            "type": "SOLID",
                            "color": {"r": 0, "g": 0, "b": 1, "a": 1},
                            "boundVariables": {"color": {"id": "var-semantic"}},
                        }
                    ],
                },
                {
                    "name": "Bg",
                    "backgroundColor": {"r": 0, "g": 0, "b": 1, "a": 1},
                    "boundVariableIds": {"backgroundColor": "var-primitive"},
                },
            ],
            parsed,
        )
        self.assertEqual(colors[0]["boundVariableNames"], ["Colors/Semantic/Primary", "Colors/Primitive/Blue"])

    def test_referenced_color_styles_preserve_field_specific_paint_stacks(self) -> None:
        referenced = build_referenced_styles(
            {
                "fill-style": {"key": "fill-key", "name": "Fill", "styleType": "FILL"},
                "stroke-style": {"key": "stroke-key", "name": "Stroke", "styleType": "FILL"},
            },
            {
                "1:1": {
                    "id": "1:1",
                    "name": "Box",
                    "type": "RECTANGLE",
                    "styles": {"fill": "fill-style", "stroke": "stroke-style"},
                    "fills": [
                        {"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                        {
                            "type": "GRADIENT_LINEAR",
                            "gradientStops": [
                                {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                                {"position": 1, "color": {"r": 0, "g": 0, "b": 0, "a": 1}},
                            ],
                        },
                    ],
                    "strokes": [
                        {"type": "SOLID", "color": {"r": 0, "g": 1, "b": 0, "a": 1}},
                    ],
                }
            },
        )
        by_name = {style["name"]: style for style in referenced["colorStyles"]}
        self.assertEqual(by_name["Fill"]["hexValues"], ["#FF0000"])
        self.assertEqual(by_name["Fill"]["gradientValues"][0]["type"], "GRADIENT_LINEAR")
        self.assertEqual(by_name["Stroke"]["hexValues"], ["#00FF00"])

    def test_interaction_details_use_legacy_transition_destination_fallback(self) -> None:
        node = {
            "id": "1:2",
            "name": "Button",
            "type": "FRAME",
            "transitionNodeID": "2:1",
            "transitionDuration": 300,
            "transitionEasing": "EASE_OUT",
            "interactions": [
                {
                    "trigger": {"type": "ON_CLICK"},
                    "actions": [
                        {
                            "type": "NODE",
                            "destinationId": None,
                            "navigation": "NAVIGATE",
                            "transition": {
                                "type": "SMART_ANIMATE",
                                "duration": 0.3,
                                "easing": {"type": "EASE_OUT"},
                            },
                        }
                    ],
                }
            ],
        }

        interactions = summarize_flow_interactions([node])
        self.assertEqual(interactions[0]["toNodeId"], "2:1")
        self.assertEqual(interactions[0]["destinationSource"], "transitionNodeID")
        self.assertEqual(interactions[0]["triggerType"], "ON_CLICK")
        self.assertEqual(interactions[0]["navigation"], "NAVIGATE")
        self.assertEqual(interactions[0]["transition"]["type"], "SMART_ANIMATE")
        self.assertEqual(interactions[0]["transition"]["durationSeconds"], 0.3)
        self.assertEqual(interactions[0]["rawAction"]["type"], "NODE")

        summary = build_summary(
            file_key="FILE123",
            start_node_id="1:1",
            source_url=None,
            node_documents={
                "1:1": {
                    "id": "1:1",
                    "name": "Start",
                    "type": "FRAME",
                    "children": [
                        node,
                        {"id": "2:1", "name": "Next", "type": "FRAME", "children": []},
                    ],
                }
            },
            flow_edges=[{"fromNodeId": "1:2", "fromName": "Button", "toNodeId": "2:1"}],
            image_paths={},
            named_styles={},
            style_node_details={},
            variables={},
            file_styles={},
            warnings=[],
        )
        markdown = render_markdown(summary)
        self.assertEqual(summary["flowInteractions"][0]["toName"], "Next")
        self.assertIn("## Prototype Interaction Details", markdown)
        self.assertIn("SMART_ANIMATE", markdown)

        manifest = build_manifest(
            summary,
            SimpleNamespace(
                format="png",
                scale=2.0,
                max_flow_depth=0,
                no_images=True,
                include_image_fills=False,
            ),
        )
        self.assertEqual(manifest["tool"], "figma-handoff.py")
        self.assertEqual(manifest["schemaVersion"], 4)
        self.assertEqual(manifest["summary"]["flowInteractionCount"], 1)
        self.assertEqual(manifest["summary"]["componentCount"], 0)

    def test_flow_node_fetch_batches_large_pending_sets(self) -> None:
        calls: list[list[str]] = []

        class FakeApi:
            def get_json(self, url: str) -> dict:
                ids = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["ids"][0].split(",")
                calls.append(ids)
                nodes = {}
                for node_id in ids:
                    children = []
                    if node_id == "1:1":
                        children = [
                            {"id": "1:2", "name": "Button", "type": "FRAME", "transitionNodeID": "2:1"},
                            {"id": "1:3", "name": "Button", "type": "FRAME", "transitionNodeID": "2:2"},
                            {"id": "1:4", "name": "Button", "type": "FRAME", "transitionNodeID": "2:3"},
                            {"id": "1:5", "name": "Complex", "type": "FRAME", "transitionNodeID": "I2:4;3:5"},
                        ]
                    nodes[node_id] = {
                        "document": {"id": node_id, "name": node_id, "type": "FRAME", "children": children},
                        "styles": {},
                    }
                return {"nodes": nodes}

        warnings: list[str] = []
        _, documents, edges, _, _ = FigmaFlowFetcher(FakeApi()).fetch(
            "FILE123", "1:1", 1, warnings
        )

        self.assertEqual(warnings, [])
        self.assertEqual(calls, [["1:1"], ["2:1", "2:2", "2:3", "I2:4;3:5"]])
        self.assertIn("1:1", documents)
        self.assertIn("I2:4;3:5", documents)
        self.assertEqual(len(edges), 4)

    def test_fetch_collects_file_level_component_maps(self) -> None:
        class FakeApi:
            def get_json(self, url: str) -> dict:
                return {
                    "nodes": {
                        "1:1": {
                            "document": {
                                "id": "1:1",
                                "name": "Screen",
                                "type": "FRAME",
                                "children": [
                                    {"id": "1:2", "name": "Card", "type": "INSTANCE", "componentId": "10:100"},
                                ],
                            },
                            "styles": {},
                            "components": {"10:100": {"name": "Card/가로형", "componentSetId": "10:1"}},
                            "componentSets": {"10:1": {"name": "Card"}},
                        }
                    }
                }

        warnings: list[str] = []
        _, _, _, _, component_index = FigmaFlowFetcher(FakeApi()).fetch(
            "FILE123", "1:1", 0, warnings
        )

        self.assertEqual(warnings, [])
        self.assertEqual(component_index["components"]["10:100"]["name"], "Card/가로형")
        self.assertEqual(component_index["componentSets"]["10:1"]["name"], "Card")

    def test_render_nodes_writes_image_response_and_downloads_images(self) -> None:
        class FakeApi:
            def get_json(inner_self, url: str) -> dict:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                self.assertEqual(query["ids"], ["1:1"])
                self.assertEqual(query["format"], ["png"])
                return {"images": {"1:1": "https://example.com/frame.png"}}

            def download(inner_self, url: str, output_path: Path, expected_format: str) -> None:
                self.assertEqual(url, "https://example.com/frame.png")
                self.assertEqual(expected_format, "png")
                output_path.write_bytes(b"image")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "frames").mkdir()
            (base / "raw").mkdir()
            warnings: list[str] = []
            result = FigmaRenderer(FakeApi()).render_nodes(
                "FILE123",
                ["1:1"],
                {"1:1": {"name": "Frame"}},
                base / "frames",
                base / "raw",
                "png",
                2.0,
                warnings,
            )
            self.assertTrue((base / "raw" / "image-response.json").exists())
            image_metadata = json.loads((base / "raw" / "image-response.json").read_text(encoding="utf-8"))
            self.assertEqual(image_metadata["1:1"], {"rendered": True})
            self.assertNotIn("https://", json.dumps(image_metadata))
            self.assertTrue((base / "frames" / "frame__1-1.png").exists())

        self.assertEqual(warnings, [])
        self.assertTrue(result["1:1"].endswith("frame__1-1.png"))

    def test_layout_nodes_surface_visual_fidelity_fields(self) -> None:
        layout_nodes = summarize_layout_nodes([
            {
                "id": "1:1",
                "name": "Root",
                "type": "FRAME",
                "layoutMode": "VERTICAL",
                "children": [
                    {
                        "id": "1:2",
                        "name": "Overlay",
                        "type": "RECTANGLE",
                        "opacity": 0.35,
                        "blendMode": "MULTIPLY",
                        "isMask": True,
                        "maskType": "ALPHA",
                        "rotation": -90,
                        "size": {"x": 8.4, "y": 14.4},
                        "strokeWeight": 0.99,
                        "strokeAlign": "INSIDE",
                        "individualStrokeWeights": {"top": 1, "bottom": 0.5, "left": 0, "right": 0},
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 14.4, "height": 8.4},
                        "absoluteRenderBounds": {"x": -2, "y": -2, "width": 18.4, "height": 12.4},
                    }
                ],
            }
        ])
        overlay = layout_nodes[1]
        self.assertEqual(overlay["opacity"], 0.35)
        self.assertEqual(overlay["blendMode"], "MULTIPLY")
        self.assertEqual(overlay["isMask"], True)
        self.assertEqual(overlay["maskType"], "ALPHA")
        self.assertEqual(overlay["rotation"], -90)
        self.assertEqual(overlay["size"], {"x": 8.4, "y": 14.4})
        self.assertEqual(overlay["strokeWeight"], 0.99)
        self.assertEqual(overlay["strokeAlign"], "INSIDE")
        self.assertEqual(overlay["individualStrokeWeights"]["top"], 1)
        self.assertEqual(overlay["absoluteRenderBounds"]["width"], 18.4)

    def test_text_style_surfaces_vertical_align_and_truncation(self) -> None:
        text_summary = summarize_text_styles([
            {
                "type": "TEXT",
                "name": "Body",
                "characters": "Hi",
                "style": {
                    "fontFamily": "Pretendard",
                    "fontSize": 14,
                    "italic": True,
                    "textAlignVertical": "CENTER",
                    "textAutoResize": "HEIGHT",
                    "textTruncation": "ENDING",
                    "maxLines": 2,
                },
            }
        ])
        style = text_summary[0]
        self.assertEqual(style["italic"], True)
        self.assertEqual(style["textAlignVertical"], "CENTER")
        self.assertEqual(style["textAutoResize"], "HEIGHT")
        self.assertEqual(style["textTruncation"], "ENDING")
        self.assertEqual(style["maxLines"], 2)

    def test_render_asset_nodes_splits_vector_svg_and_image_png(self) -> None:
        formats_by_id: dict[str, str] = {}

        class FakeApi:
            def get_json(inner_self, url: str) -> dict:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                image_format = query["format"][0]
                if image_format == "png":
                    self.assertEqual(query["scale"], ["3.0"])
                else:
                    self.assertNotIn("scale", query)
                images = {}
                for node_id in query["ids"][0].split(","):
                    formats_by_id[node_id] = image_format
                    images[node_id] = f"https://example.com/{node_id}.{image_format}"
                return {"images": images}

            def download(inner_self, url: str, output_path: Path, expected_format: str) -> None:
                output_path.write_text("data", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "assets").mkdir()
            (base / "raw").mkdir()
            warnings: list[str] = []
            result = FigmaRenderer(FakeApi()).render_assets(
                "FILE123",
                [
                    {"id": "1:2", "name": "ic_player", "type": "VECTOR"},
                    {"id": "1:2", "name": "dup-ignored", "type": "VECTOR"},
                    {"id": "1:3", "name": "avatar", "type": "RECTANGLE", "imageRefs": ["ref1"]},
                ],
                base / "assets",
                base / "raw",
                warnings,
                3.0,
            )
            self.assertTrue((base / "assets" / "ic_player__1-2.svg").exists())
            self.assertTrue((base / "assets" / "avatar__1-3.png").exists())

        self.assertEqual(warnings, [])
        self.assertEqual(formats_by_id["1:2"], "svg")
        self.assertEqual(formats_by_id["1:3"], "png")
        self.assertTrue(result["1:2"].endswith("ic_player__1-2.svg"))
        self.assertTrue(result["1:3"].endswith("avatar__1-3.png"))

    def test_render_asset_nodes_falls_back_to_renderable_ancestor(self) -> None:
        class FakeApi:
            def get_json(self, url: str) -> dict:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                images = {
                    node_id: None if node_id == "1:9" else f"https://example.com/{node_id}.svg"
                    for node_id in query["ids"][0].split(",")
                }
                return {"images": images}

            def download(self, url: str, output_path: Path, expected_format: str) -> None:
                output_path.write_text("<svg/>", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "assets").mkdir()
            (base / "raw").mkdir()
            warnings: list[str] = []
            result = FigmaRenderer(FakeApi()).render_assets(
                "FILE123",
                [
                    {
                        "id": "1:9",
                        "name": "IconLeaf",
                        "type": "VECTOR",
                        "renderFallbackIds": [{"id": "1:8", "name": "IconBox"}],
                    }
                ],
                base / "assets",
                base / "raw",
                warnings,
                3.0,
            )
            self.assertTrue((base / "assets" / "iconbox__1-8.svg").exists())

        self.assertEqual(warnings, [])
        self.assertTrue(result["1:9"].endswith("iconbox__1-8.svg"))

    def test_chunk_node_ids_respects_query_length_and_retry_after_is_robust(self) -> None:
        chunks = _chunk_node_ids(
            ["I1:" + "x" * 40, "I2:" + "y" * 40, "I3:" + "z" * 40],
            max_batch_size=100,
            max_query_chars=70,
        )

        self.assertEqual(len(chunks), 3)
        self.assertEqual(_retry_delay_seconds("2", 0), 2.0)
        self.assertEqual(_retry_delay_seconds("not-a-date", 1), 3.0)


if __name__ == "__main__":
    unittest.main()
