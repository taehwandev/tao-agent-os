from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

import tempfile
import unittest
import urllib.parse
from pathlib import Path

import figma_fetch
from figma_analyze import summarize_asset_candidates


class AssetDedupKeyTests(unittest.TestCase):
    def test_image_fill_key_uses_image_ref(self) -> None:
        nodes = [
            {"id": "1:1", "name": "photo", "type": "RECTANGLE",
             "fills": [{"type": "IMAGE", "imageRef": "REF_A"}]},
            {"id": "1:2", "name": "photo copy", "type": "RECTANGLE",
             "fills": [{"type": "IMAGE", "imageRef": "REF_A"}]},
        ]
        candidates = summarize_asset_candidates(nodes)
        keys = [c["dedupKey"] for c in candidates]
        self.assertTrue(all(k.startswith("img:") for k in keys))
        self.assertEqual(keys[0], keys[1], "same imageRef must share dedup key")

    def test_identical_vectors_share_key_but_recolored_differ(self) -> None:
        base = {"type": "VECTOR", "name": "ic_check", "size": {"x": 24, "y": 24},
                "strokes": [], "effects": []}
        red = {**base, "id": "2:1", "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0}}]}
        red_dup = {**base, "id": "2:2", "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0}}]}
        blue = {**base, "id": "2:3", "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 1}}]}
        candidates = {c["id"]: c["dedupKey"] for c in summarize_asset_candidates([red, red_dup, blue])}
        self.assertEqual(candidates["2:1"], candidates["2:2"], "identical vectors merge")
        self.assertNotEqual(candidates["2:1"], candidates["2:3"], "recolored vector must not merge")


class _FakeImageApi:
    """request_json/download_file 대체: 네트워크·실제 파일 없이 호출을 집계한다."""

    def __init__(self) -> None:
        self.downloaded: list[str] = []

    def request_json(self, url: str, token: str, timeout: int) -> dict:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        ids = query.get("ids", [""])[0].split(",") if query.get("ids") else []
        return {"images": {node_id: f"https://cdn/{node_id}.svg" for node_id in ids if node_id}}

    def download_file(self, url: str, output_path: Path, timeout: int, retries: int = 2) -> None:
        self.downloaded.append(str(output_path))
        output_path.write_text("<svg/>", encoding="utf-8")


class RenderAssetNodesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeImageApi()
        self._orig_request = figma_fetch.request_json
        self._orig_download = figma_fetch.download_file
        figma_fetch.request_json = self.fake.request_json
        figma_fetch.download_file = self.fake.download_file

    def tearDown(self) -> None:
        figma_fetch.request_json = self._orig_request
        figma_fetch.download_file = self._orig_download

    def _run(self, candidates: list[dict], max_assets=None):
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "assets"
            raw = Path(tmp) / "raw"
            out.mkdir()
            raw.mkdir()
            result = figma_fetch.render_asset_nodes(
                file_key="FK",
                asset_candidates=candidates,
                token="t",
                output_dir=out,
                raw_dir=raw,
                timeout=5,
                warnings=warnings,
                scale=2.0,
                max_assets=max_assets,
            )
        return result, warnings

    def test_dedup_downloads_once_but_maps_all_members(self) -> None:
        candidates = [
            {"id": "3:1", "name": "ic_a", "type": "VECTOR", "imageRefs": [], "dedupKey": "vec:A"},
            {"id": "3:2", "name": "ic_a", "type": "VECTOR", "imageRefs": [], "dedupKey": "vec:A"},
            {"id": "3:3", "name": "ic_b", "type": "VECTOR", "imageRefs": [], "dedupKey": "vec:B"},
        ]
        result, _ = self._run(candidates)
        self.assertEqual(len(self.fake.downloaded), 2, "one download per unique dedup key")
        self.assertEqual(set(result), {"3:1", "3:2", "3:3"}, "all node ids resolve to a file")
        self.assertEqual(result["3:1"], result["3:2"], "deduped members share the rep file")
        self.assertNotEqual(result["3:1"], result["3:3"])

    def test_multi_batch_resolution_covers_all(self) -> None:
        # 100개 초과 → 여러 /images 배치. 병렬 해석 후 전부 매핑돼야 한다.
        candidates = [
            {"id": f"5:{i}", "name": f"ic_{i}", "type": "VECTOR", "imageRefs": [], "dedupKey": f"vec:{i}"}
            for i in range(250)
        ]
        result, _ = self._run(candidates)
        self.assertEqual(len(self.fake.downloaded), 250, "all unique assets downloaded across batches")
        self.assertEqual(len(result), 250, "all node ids resolved")

    def test_max_assets_caps_and_warns(self) -> None:
        candidates = [
            {"id": f"4:{i}", "name": f"ic_{i}", "type": "VECTOR", "imageRefs": [], "dedupKey": f"vec:{i}"}
            for i in range(5)
        ]
        result, warnings = self._run(candidates, max_assets=2)
        self.assertEqual(len(self.fake.downloaded), 2, "cap limits rendered assets")
        self.assertTrue(any("Asset cap reached" in w for w in warnings), "cap must be reported, not silent")
        self.assertLessEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
