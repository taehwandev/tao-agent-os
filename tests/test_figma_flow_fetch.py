from __future__ import annotations

import sys
import unittest
import urllib.parse
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from figma_flow_fetch import FigmaFlowFetcher


class FigmaFlowFetcherResilienceTests(unittest.TestCase):
    def test_one_failed_batch_does_not_discard_other_batches(self) -> None:
        class FakeApi:
            def get_json(self, url: str) -> dict:
                ids = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["ids"][0].split(",")
                if ids == ["1:1"]:
                    return {
                        "nodes": {
                            "1:1": {
                                "document": {
                                    "id": "1:1",
                                    "name": "Flow",
                                    "type": "SECTION",
                                    "children": [
                                        {
                                            "id": f"1:{index + 10}",
                                            "type": "FRAME",
                                            "reactions": [{"action": {"destinationId": f"2:{index}"}}],
                                        }
                                        for index in range(1, 102)
                                    ],
                                }
                            }
                        }
                    }
                if len(ids) == 100:
                    raise RuntimeError("Figma API failed (503).")
                return {
                    "nodes": {
                        ids[0]: {
                            "document": {"id": ids[0], "name": "Recovered", "type": "FRAME"}
                        }
                    }
                }

        warnings: list[str] = []
        raw, documents, _, _, _ = FigmaFlowFetcher(FakeApi()).fetch(
            "FILE",
            "1:1",
            max_flow_depth=1,
            warnings=warnings,
        )

        self.assertIn("1:1", documents)
        self.assertIn("2:101", documents)
        self.assertEqual(len(raw), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("batch 1", warnings[0])


if __name__ == "__main__":
    unittest.main()
