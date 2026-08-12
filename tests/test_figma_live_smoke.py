from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from live_smoke import _frame_scale_failures, _layout_coverage_failures


def _write_png_header(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", width, height))


class FigmaLiveSmokePolicyTests(unittest.TestCase):
    def test_frame_scale_accepts_one_pixel_tolerance_and_rejects_real_mismatch(self) -> None:
        summary = {
            "screens": [
                {"id": "1:1", "width": 100, "height": 200, "imagePath": "frames/screen.png"}
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            image = bundle / "frames" / "screen.png"
            _write_png_header(image, 201, 399)
            self.assertEqual(_frame_scale_failures(summary, bundle, 2), [])

            _write_png_header(image, 150, 400)
            failures = _frame_scale_failures(summary, bundle, 2)

        self.assertEqual(len(failures), 1)
        self.assertIn("frame scale mismatch", failures[0])

    def test_nonempty_handoff_requires_layout_coverage(self) -> None:
        self.assertEqual(
            _layout_coverage_failures({"screens": 1, "layoutNodes": {"total": 0}}),
            ["layout coverage is empty for a non-empty handoff"],
        )
        self.assertEqual(
            _layout_coverage_failures({"screens": 1, "layoutNodes": {"total": 1}}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
