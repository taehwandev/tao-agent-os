from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from figma_metadata_fetch import FigmaMetadataFetcher


class _DeniedVariablesApi:
    def get_json(self, url: str) -> dict:
        if url.endswith("/variables/local"):
            raise RuntimeError("Figma API failed (403).")
        return {}


class FigmaMetadataFetcherTests(unittest.TestCase):
    def test_dev_mode_variables_denial_keeps_handoff_available(self) -> None:
        warnings: list[str] = []

        result = FigmaMetadataFetcher(_DeniedVariablesApi()).variables("FILE", warnings)

        self.assertEqual(result, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("without Dev Mode variables", warnings[0])
        self.assertNotIn("token", warnings[0].lower())


if __name__ == "__main__":
    unittest.main()
