from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from figma_cli import FigmaHandoffCli


class FigmaCliFailureTests(unittest.TestCase):
    def test_failed_authenticated_fetch_reports_safe_cause(self) -> None:
        cases = (
            (
                urllib.error.HTTPError(
                    "https://api.figma.com/v1/files/FILE/nodes",
                    403,
                    "Forbidden",
                    {},
                    io.BytesIO(b"private-response-body"),
                ),
                "Figma API failed (403).",
            ),
            (
                urllib.error.URLError("private-network-detail"),
                "Figma API request failed (network error).",
            ),
        )
        for error, expected_cause in cases:
            with self.subTest(cause=expected_cause), tempfile.TemporaryDirectory() as temporary:
                stderr = io.StringIO()
                opener = mock.Mock()
                opener.open.side_effect = error
                with mock.patch.dict(os.environ, {"FIGMA_TOKEN": "synthetic-token"}), mock.patch(
                    "figma_api.urllib.request.build_opener", return_value=opener
                ), mock.patch("figma_api.time.sleep"), contextlib.redirect_stderr(stderr):
                    exit_code = FigmaHandoffCli().run([
                        "--url", "https://www.figma.com/design/FILE/Example?node-id=1-2",
                        "--out", temporary,
                        "--name", "failed-node",
                        "--max-flow-depth", "0",
                    ])

                self.assertEqual(exit_code, 1)
                self.assertIn(expected_cause, stderr.getvalue())
                self.assertIn("Figma start node 1:2 was not fetched", stderr.getvalue())
                for private_value in ("synthetic-token", "private-response-body", "private-network-detail"):
                    self.assertNotIn(private_value, stderr.getvalue())
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url, "https://api.figma.com/v1/files/FILE/nodes?ids=1%3A2")
                self.assertEqual(request.get_header("X-figma-token"), "synthetic-token")
                raw_nodes = Path(temporary) / "failed-node" / "raw" / "nodes.json"
                self.assertEqual(json.loads(raw_nodes.read_text()), [])
                self.assertFalse((raw_nodes.parent.parent / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
