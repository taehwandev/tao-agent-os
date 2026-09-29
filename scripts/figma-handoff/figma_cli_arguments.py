from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from figma_util import slugify


_DEFAULT_WORK_DIR_NAME = ".figma-handoff-work"


class FigmaCliArguments:
    """Own argument parsing, semantic bounds, and dry-run projection."""

    def __init__(self, argv: list[str] | None) -> None:
        self.values = self._parser().parse_args(argv)
        self.error = self._validate()

    def output_dir(self, node_id: str) -> Path:
        name = slugify((self.values.name or "").strip() or f"node-{node_id.replace(':', '-')}")
        base = (
            Path(self.values.out).expanduser()
            if self.values.out
            else Path.cwd() / _DEFAULT_WORK_DIR_NAME
        )
        return base / name

    def print_plan(self, file_key: str, node_id: str, output_dir: Path) -> None:
        plan: dict[str, Any] = {
            "fileKey": file_key,
            "startNodeId": node_id,
            "outputDir": str(output_dir),
            "images": not self.values.no_images,
            "format": self.values.format,
            "scale": self.values.scale,
            "maxFlowDepth": self.values.max_flow_depth,
            "timeout": self.values.timeout,
            "exportAssets": self.values.export_assets,
            "maxAssets": self.values.max_assets,
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))

    def _validate(self) -> str | None:
        if not 0.01 <= self.values.scale <= 4.0:
            return "--scale must be between 0.01 and 4.0."
        if self.values.timeout <= 0:
            return "--timeout must be greater than zero."
        if self.values.max_flow_depth < 0:
            return "--max-flow-depth must not be negative."
        if self.values.max_assets is not None and self.values.max_assets < 0:
            return "--max-assets must not be negative."
        return None

    @staticmethod
    def _parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="Create a portable Figma handoff bundle.")
        parser.add_argument("--url")
        parser.add_argument("--file-key")
        parser.add_argument("--node-id")
        parser.add_argument("--name")
        parser.add_argument("--out")
        parser.add_argument("--token-env", default="FIGMA_TOKEN")
        parser.add_argument("--format", default="png", choices=["png", "jpg", "svg", "pdf"])
        parser.add_argument("--scale", default=2.0, type=float)
        parser.add_argument("--max-flow-depth", default=4, type=int)
        parser.add_argument("--timeout", default=60, type=int)
        parser.add_argument("--no-images", action="store_true")
        parser.add_argument("--include-image-fills", action="store_true")
        parser.add_argument("--export-assets", action="store_true")
        parser.add_argument("--max-assets", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")
        return parser
