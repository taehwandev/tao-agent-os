#!/usr/bin/env python3
"""라이브 스모크 하네스 — 실제 Figma 호출로 1:1 파이프라인을 빽빽하게 검증한다.

unittest 대상이 아니며(파일명이 test*.py 아님) 네트워크·토큰이 필요하다.
토큰 환경변수가 없으면 SKIP(exit 0)해서 오프라인 CI를 깨지 않는다.

검증 항목:
1. 도구 실행 성공(exit 0)
2. design-summary.json 스키마 통과(figma_validate)
3. 프레임이 유효한 PNG로 다운로드됨(--scale 배율 반영 확인)
4. asset이 벡터→SVG / 이미지 fill→PNG로 분기 export됨
5. 이미지 fill(사진/아바타) 복구율이 임계치 이상
6. 충실도 커버리지 리포트 출력

usage: FIGMA_TOKEN=... python3 live_smoke.py --url <frame url> [--scale 3]
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
from figma_validate import coverage_report, format_report, validate_summary  # noqa: E402

TOOL = Path(__file__).parent / "figma-handoff.py"
IMAGE_FILL_MIN_PCT = 100  # 사진/아바타는 PNG로 항상 복구되어야 한다.


def _png_size(path: Path) -> tuple[int, int] | None:
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


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

        assets = out / "assets"
        svgs = list(assets.glob("*.svg")) if assets.exists() else []
        pngs = list(assets.glob("*.png")) if assets.exists() else []
        if not args.quick:
            if not svgs:
                failures.append("no vector SVG assets exported (asset split broken?)")

        cov = coverage_report(summary)
        asset = cov["assets"]
        if not args.quick and asset["imageFillTotal"]:
            pct = asset["imageFillWithPath"] * 100 // asset["imageFillTotal"]
            if pct < IMAGE_FILL_MIN_PCT:
                failures.append(
                    f"image-fill recovery {asset['imageFillWithPath']}/{asset['imageFillTotal']} "
                    f"({pct}%) < {IMAGE_FILL_MIN_PCT}%"
                )

        print(format_report(problems, cov))
        print(f"frames={len(frames)} (예: {_png_size(frames[0]) if frames else None}) "
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
