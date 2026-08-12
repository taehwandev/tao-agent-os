from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"))

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from figma_api import USER_AGENT, download_file


TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
CLI = TOOL_DIR / "figma-handoff.py"
LIVE_SMOKE = TOOL_DIR / "live_smoke.py"


def _load_cli_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("figma_handoff_cli", CLI)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {CLI}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StandaloneCliTests(unittest.TestCase):
    def test_dry_run_works_from_an_unrelated_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--url",
                    "https://www.figma.com/design/FILE_KEY/Example?node-id=1-2",
                    "--name",
                    "Portable Screen",
                    "--dry-run",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["fileKey"], "FILE_KEY")
            self.assertEqual(plan["startNodeId"], "1:2")
            self.assertEqual(
                Path(plan["outputDir"]).resolve(),
                (Path(tmp) / ".figma-handoff-work" / "portable-screen").resolve(),
            )

    def test_dry_run_works_in_python_isolated_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(CLI),
                    "--url",
                    "https://www.figma.com/design/FILE_KEY/Example?node-id=1-2",
                    "--name",
                    "Isolated Screen",
                    "--dry-run",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["fileKey"], "FILE_KEY")
            self.assertEqual(plan["startNodeId"], "1:2")
            self.assertEqual(
                Path(plan["outputDir"]).resolve(),
                (Path(tmp) / ".figma-handoff-work" / "isolated-screen").resolve(),
            )

    def test_live_smoke_skips_without_a_token_or_default_team_url(self) -> None:
        env = os.environ.copy()
        env.pop("FIGMA_TOKEN", None)
        env.pop("FIGMA_SMOKE_URL", None)
        result = subprocess.run(
            [sys.executable, str(LIVE_SMOKE)],
            cwd=tempfile.gettempdir(),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SKIP", result.stdout)

    def test_http_identity_is_agent_os_owned(self) -> None:
        self.assertEqual(USER_AGENT, "agent-os-figma-handoff/1.0")

    def test_generated_paths_are_bundle_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            frame = bundle / "frames" / "screen.png"
            frame.parent.mkdir(parents=True)
            frame.write_bytes(b"png")

            result = _load_cli_module().bundle_relative_paths({"1:2": str(frame)}, bundle)

        self.assertEqual(result, {"1:2": "frames/screen.png"})

    def test_generated_paths_cannot_escape_the_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            bundle.mkdir()
            outside = Path(tmp) / "outside.png"
            outside.write_bytes(b"png")

            with self.assertRaises(RuntimeError):
                _load_cli_module().bundle_relative_paths({"1:2": str(outside)}, bundle)


class DownloadErrorSafetyTests(unittest.TestCase):
    def test_signed_download_url_is_not_repeated_in_errors(self) -> None:
        signed_url = "https://cdn.example.invalid/file.svg?signature=top-secret"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "figma_api.urllib.request.urlopen",
                side_effect=urllib.error.URLError("timed out"),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    download_file(signed_url, Path(tmp) / "asset.svg", timeout=1, retries=0)

        message = str(raised.exception)
        self.assertNotIn(signed_url, message)
        self.assertNotIn("top-secret", message)


if __name__ == "__main__":
    unittest.main()
