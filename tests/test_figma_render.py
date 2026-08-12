from __future__ import annotations

import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from figma_render import FigmaRenderer


class _RenderApi:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, Path, str]] = []
        self.formats_by_id: dict[str, list[str]] = {}
        self.barrier: threading.Barrier | None = None

    def get_json(self, url: str) -> dict:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        image_format = query["format"][0]
        node_ids = query["ids"][0].split(",")
        if self.barrier is not None:
            self.barrier.wait(timeout=2)
        images: dict[str, str | None] = {}
        for node_id in node_ids:
            self.formats_by_id.setdefault(node_id, []).append(image_format)
            if node_id in {"1:1", "1:2"}:
                images[node_id] = None
            else:
                images[node_id] = f"https://cdn.example/{node_id}.{image_format}"
        return {"images": images}

    def download(self, url: str, output_path: Path, expected_format: str) -> None:
        self.downloads.append((url, output_path, expected_format))
        payload = b"<svg/>" if expected_format == "svg" else b"\x89PNG\r\n\x1a\n"
        output_path.write_bytes(payload)


class FigmaRendererTests(unittest.TestCase):
    def _directories(self, temporary: str) -> tuple[Path, Path]:
        output = Path(temporary) / "assets"
        raw = Path(temporary) / "raw"
        output.mkdir()
        raw.mkdir()
        return output, raw

    def test_dedup_downloads_once_and_maps_every_member(self) -> None:
        api = _RenderApi()
        with tempfile.TemporaryDirectory() as temporary:
            output, raw = self._directories(temporary)
            result = FigmaRenderer(api).render_assets(
                "FILE",
                [
                    {"id": "3:1", "name": "A", "dedupKey": "vec:A"},
                    {"id": "3:2", "name": "A copy", "dedupKey": "vec:A"},
                    {"id": "3:3", "name": "B", "dedupKey": "vec:B"},
                ],
                output,
                raw,
                [],
            )

        self.assertEqual(len(api.downloads), 2)
        self.assertEqual(set(result), {"3:1", "3:2", "3:3"})
        self.assertEqual(result["3:1"], result["3:2"])
        self.assertNotEqual(result["3:1"], result["3:3"])

    def test_shared_ancestor_fallback_keeps_svg_and_png_separate(self) -> None:
        api = _RenderApi()
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            output, raw = self._directories(temporary)
            result = FigmaRenderer(api).render_assets(
                "FILE",
                [
                    {
                        "id": "1:1",
                        "name": "Vector leaf",
                        "renderFallbackIds": [{"id": "9:9", "name": "Shared ancestor"}],
                    },
                    {
                        "id": "1:2",
                        "name": "Photo leaf",
                        "imageRefs": ["image-ref"],
                        "renderFallbackIds": [{"id": "9:9", "name": "Shared ancestor"}],
                    },
                ],
                output,
                raw,
                warnings,
                scale=2.0,
            )

        self.assertTrue(result["1:1"].endswith(".svg"))
        self.assertTrue(result["1:2"].endswith(".png"))
        self.assertEqual(sorted(api.formats_by_id["9:9"]), ["png", "svg"])
        self.assertEqual(warnings, [])

    def test_render_batches_overlap_instead_of_running_serially(self) -> None:
        api = _RenderApi()
        api.barrier = threading.Barrier(3)
        node_ids = [f"5:{index}" for index in range(201)]
        with tempfile.TemporaryDirectory() as temporary:
            output, raw = self._directories(temporary)
            result = FigmaRenderer(api).render_nodes(
                "FILE",
                node_ids,
                {node_id: {"name": node_id} for node_id in node_ids},
                output,
                raw,
                "svg",
                1.0,
                [],
            )

        self.assertEqual(len(result), 201)
        self.assertEqual(len(api.downloads), 201)

    def test_invalid_render_node_id_is_rejected_before_path_creation(self) -> None:
        api = _RenderApi()
        with tempfile.TemporaryDirectory() as temporary:
            output, raw = self._directories(temporary)
            with self.assertRaises(RuntimeError):
                FigmaRenderer(api).render_nodes(
                    "FILE",
                    ["../../escape"],
                    {"../../escape": {"name": "unsafe"}},
                    output,
                    raw,
                    "svg",
                    1.0,
                    [],
                )
        self.assertEqual(api.downloads, [])


if __name__ == "__main__":
    unittest.main()
