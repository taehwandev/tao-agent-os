#!/usr/bin/env python3
"""Live smoke harness for a real Figma API handoff pipeline.

This is not an unittest target (the filename does not start with ``test``) and
requires network access plus a token. It returns SKIP (exit 0) when the token
environment variable is missing so offline CI remains independent.

Checks:
1. the tool exits successfully
2. design-summary.json passes figma_validate
3. frame downloads are valid PNGs at the requested scale
4. vectors export as SVG and image fills as PNG
5. image-fill recovery meets the configured threshold
6. the fidelity coverage report is produced

Usage: python3 live_smoke.py --url <frame-url> [--scale 3]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from figma_coverage import coverage_report  # noqa: E402
from figma_summary_validate import validate_summary  # noqa: E402
from figma_validation_report import format_report  # noqa: E402

TOOL = Path(__file__).parent / "figma-handoff.py"
IMAGE_FILL_MIN_PCT = 100  # Image fills must be fully recovered as PNG files.


def _png_size(path: Path) -> tuple[int, int] | None:
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def _frame_scale_failures(summary: dict, bundle_root: Path, scale: float) -> list[str]:
    failures: list[str] = []
    for screen in summary.get("screens", []) or []:
        image_path = screen.get("imagePath")
        width = screen.get("width")
        height = screen.get("height")
        if not image_path or not str(image_path).endswith(".png"):
            continue
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            failures.append(f"screen dimensions unavailable for scale check: {screen.get('id')}")
            continue
        size = _png_size(bundle_root / str(image_path))
        expected = (round(width * scale), round(height * scale))
        if size is None or any(abs(actual - target) > 1 for actual, target in zip(size, expected)):
            failures.append(f"frame scale mismatch for {screen.get('id')}: actual={size} expected={expected}")
    return failures


def _layout_coverage_failures(coverage: dict) -> list[str]:
    if coverage["screens"] and coverage["layoutNodes"]["total"] == 0:
        return ["layout coverage is empty for a non-empty handoff"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="figma-handoff live smoke harness")
    parser.add_argument("--url", default=os.environ.get("FIGMA_SMOKE_URL"))
    parser.add_argument("--scale", type=float, default=3.0)
    parser.add_argument("--token-env", default="FIGMA_TOKEN")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Schema + frame PNG + layout coverage only; skip asset export (fast on large flows).",
    )
    args = parser.parse_args()

    if not os.environ.get(args.token_env):
        print(f"SKIP: {args.token_env} is not set — live smoke needs network + token.")
        return 0
    if not args.url:
        parser.error("--url or FIGMA_SMOKE_URL is required when a token is available")

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="figma-smoke-"))
    try:
        command = [
            sys.executable, str(TOOL),
            "--url", args.url,
            "--name", "smoke",
            "--out", str(tmp),
            "--scale", str(args.scale),
            "--token-env", args.token_env,
        ]
        if not args.quick:
            command.append("--export-assets")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        print(result.stdout.strip()[-600:])
        if result.returncode != 0:
            print(result.stderr.strip()[-800:], file=sys.stderr)
            print("FAIL: tool exited non-zero")
            return 1

        out = tmp / "smoke"
        summary = json.loads((out / "summary" / "design-summary.json").read_text(encoding="utf-8"))

        problems = validate_summary(summary)
        if problems:
            failures.append(f"schema violations: {problems}")

        frames = sorted((out / "frames").glob("*.png"))
        if not frames:
            failures.append("no frame PNG downloaded")
        for frame in frames:
            size = _png_size(frame)
            if not size:
                failures.append(f"invalid PNG: {frame.name}")
            elif size[0] <= 0 or size[1] <= 0:
                failures.append(f"empty PNG dimensions: {frame.name} {size}")

        failures.extend(_frame_scale_failures(summary, out, args.scale))

        assets = out / "assets"
        svgs = list(assets.glob("*.svg")) if assets.exists() else []
        pngs = list(assets.glob("*.png")) if assets.exists() else []
        if not args.quick:
            if not svgs:
                failures.append("no vector SVG assets exported (asset split broken?)")

        cov = coverage_report(summary)
        failures.extend(_layout_coverage_failures(cov))
        asset = cov["assets"]
        if not args.quick and asset["imageFillTotal"]:
            pct = asset["imageFillWithPath"] * 100 // asset["imageFillTotal"]
            if pct < IMAGE_FILL_MIN_PCT:
                failures.append(
                    f"image-fill recovery {asset['imageFillWithPath']}/{asset['imageFillTotal']} "
                    f"({pct}%) < {IMAGE_FILL_MIN_PCT}%"
                )

        print(format_report(problems, cov))
        print(f"frames={len(frames)} (for example: {_png_size(frames[0]) if frames else None}) "
              f"assets: svg={len(svgs)} png={len(pngs)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("LIVE SMOKE FAILURES:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("LIVE SMOKE PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
