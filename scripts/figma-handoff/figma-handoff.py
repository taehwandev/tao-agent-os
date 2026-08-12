#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Python isolated mode (-I) omits the script directory from sys.path.
# Bootstrap only this tool directory so sibling modules remain self-contained.
TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from figma_fetch import (
    RENDERABLE_TYPES,
    fetch_flow_nodes,
    fetch_image_fills,
    fetch_named_styles,
    fetch_style_node_details,
    fetch_variables,
    render_asset_nodes,
    render_nodes,
)
from figma_report import build_manifest, build_summary, render_markdown
from figma_util import normalize_node_id, resolve_figma_target, slugify, write_json
from figma_validate import validate_summary


DEFAULT_WORK_DIR_NAME = ".figma-handoff-work"


def bundle_relative_paths(paths: dict[str, str], bundle_dir: Path) -> dict[str, str]:
    """Return portable POSIX paths and reject files outside the bundle root."""
    root = bundle_dir.resolve()
    result: dict[str, str] = {}
    for node_id, raw_path in paths.items():
        try:
            relative = Path(raw_path).resolve().relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"Generated file escaped the bundle root for node {node_id}.") from error
        result[node_id] = relative.as_posix()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a portable Figma handoff bundle for UI implementation."
    )
    parser.add_argument("--url", help="Figma frame URL. Example: https://www.figma.com/design/<fileKey>/...?node-id=1-2")
    parser.add_argument("--file-key", help="Figma file key. Used when --url is not provided.")
    parser.add_argument("--node-id", help="Figma node id. Used when --url is not provided.")
    parser.add_argument("--name", help="Output bundle name. Defaults to the node id.")
    parser.add_argument(
        "--out",
        help=f"Base output directory. Default: <current-working-directory>/{DEFAULT_WORK_DIR_NAME}",
    )
    parser.add_argument("--token-env", default="FIGMA_TOKEN", help="Environment variable containing the Figma token.")
    parser.add_argument("--format", default="png", choices=["png", "jpg", "svg", "pdf"], help="Rendered frame format.")
    parser.add_argument("--scale", default=2.0, type=float, help="Image scale for png/jpg exports. Figma supports 0.01...4.")
    parser.add_argument("--max-flow-depth", default=4, type=int, help="Prototype transition traversal depth from the start node.")
    parser.add_argument("--timeout", default=60, type=int, help="Network timeout in seconds.")
    parser.add_argument("--no-images", action="store_true", help="Fetch JSON only; skip rendered frame downloads.")
    parser.add_argument(
        "--include-image-fills",
        action="store_true",
        help="Also fetch file-level image fill URLs. This can be large, so it is off by default.",
    )
    parser.add_argument(
        "--export-assets",
        action="store_true",
        help="Render each icon/vector asset candidate to an individual SVG under assets/. Off by default.",
    )
    parser.add_argument(
        "--max-assets",
        type=int,
        default=None,
        help="Cap the number of unique assets rendered (after dedup). Skipped assets are reported as a warning.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse inputs and print the planned output without network calls.")
    args = parser.parse_args()

    try:
        file_key, start_node_id = resolve_figma_target(args.url, args.file_key, args.node_id)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    bundle_name = slugify((args.name or "").strip() or f"node-{start_node_id.replace(':', '-')}")
    output_base = Path(args.out).expanduser() if args.out else Path.cwd() / DEFAULT_WORK_DIR_NAME
    output_dir = output_base / bundle_name

    if args.dry_run:
        print(
            json.dumps(
                {
                    "fileKey": file_key,
                    "startNodeId": start_node_id,
                    "outputDir": str(output_dir),
                    "images": not args.no_images,
                    "format": args.format,
                    "scale": args.scale,
                    "maxFlowDepth": args.max_flow_depth,
                    "exportAssets": args.export_assets,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    token = os.environ.get(args.token_env)
    if not token:
        print(f"ERROR: Set {args.token_env} before running this command.", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    frames_dir = output_dir / "frames"
    summary_dir = output_dir / "summary"
    raw_dir.mkdir(exist_ok=True)
    frames_dir.mkdir(exist_ok=True)
    summary_dir.mkdir(exist_ok=True)

    warnings: list[str] = []
    raw_node_responses, node_documents, flow_edges, file_styles, component_index = fetch_flow_nodes(
        file_key=file_key,
        start_node_id=start_node_id,
        token=token,
        max_flow_depth=max(args.max_flow_depth, 0),
        timeout=args.timeout,
        warnings=warnings,
    )

    write_json(raw_dir / "nodes.json", raw_node_responses)
    if start_node_id not in node_documents:
        print(
            f"ERROR: Figma start node {start_node_id} was not fetched. "
            f"Raw node response was written to {raw_dir / 'nodes.json'}.",
            file=sys.stderr,
        )
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        return 1

    image_paths: dict[str, str] = {}
    if not args.no_images:
        render_ids = [
            node_id
            for node_id, document in node_documents.items()
            if document.get("type") in RENDERABLE_TYPES
        ]
        image_paths = render_nodes(
            file_key=file_key,
            node_ids=render_ids,
            documents=node_documents,
            token=token,
            output_dir=frames_dir,
            raw_dir=raw_dir,
            image_format=args.format,
            scale=args.scale,
            timeout=args.timeout,
            warnings=warnings,
        )
        image_paths = bundle_relative_paths(image_paths, output_dir)

    if args.include_image_fills:
        try:
            image_fills = fetch_image_fills(file_key, token, args.timeout)
            write_json(raw_dir / "image-fills.json", image_fills)
        except RuntimeError as error:
            warnings.append(f"Image fills fetch failed: {error}")

    named_styles = fetch_named_styles(file_key, token, args.timeout, warnings)
    write_json(raw_dir / "styles.json", named_styles)

    variables = fetch_variables(file_key, token, args.timeout, warnings)
    write_json(raw_dir / "variables.json", variables)

    style_node_ids = [
        normalize_node_id(s.get("node_id", ""))
        for s in named_styles.get("meta", {}).get("styles", [])
        if s.get("node_id")
    ]
    missing_style_node_ids = [nid for nid in style_node_ids if nid not in node_documents]
    style_node_details: dict[str, dict[str, Any]] = {
        nid: node_documents[nid] for nid in style_node_ids if nid in node_documents
    }
    fetched_details = fetch_style_node_details(file_key, missing_style_node_ids, token, args.timeout, warnings)
    style_node_details.update(fetched_details)
    write_json(raw_dir / "style-nodes.json", style_node_details)

    summary = build_summary(
        file_key=file_key,
        start_node_id=start_node_id,
        source_url=args.url,
        node_documents=node_documents,
        flow_edges=flow_edges,
        image_paths=image_paths,
        named_styles=named_styles,
        style_node_details=style_node_details,
        variables=variables,
        file_styles=file_styles,
        warnings=warnings,
        component_index=component_index,
    )
    def persist_summary() -> list[str]:
        problems = validate_summary(summary)
        summary["warnings"] = warnings + [f"schema: {problem}" for problem in problems]
        write_json(summary_dir / "design-summary.json", summary)
        (summary_dir / "design-handoff.md").write_text(render_markdown(summary), encoding="utf-8")
        write_json(output_dir / "manifest.json", build_manifest(summary, args))
        return problems

    # asset 렌더는 오래 걸릴 수 있으므로, 그 전에 summary/handoff/manifest를 먼저 기록한다.
    # 이후 단계가 중단돼도 구현 기준 산출물은 유효하게 남는다(부분 성공).
    persist_summary()

    asset_paths: dict[str, str] = {}
    if args.export_assets:
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        asset_paths = render_asset_nodes(
            file_key=file_key,
            asset_candidates=summary.get("assetCandidates", []),
            token=token,
            output_dir=assets_dir,
            raw_dir=raw_dir,
            timeout=args.timeout,
            warnings=warnings,
            scale=args.scale,
            max_assets=args.max_assets,
        )
        asset_paths = bundle_relative_paths(asset_paths, output_dir)
        for candidate in summary.get("assetCandidates", []):
            path = asset_paths.get(candidate.get("id", ""))
            if path:
                candidate["assetPath"] = path

    schema_problems = persist_summary()
    if schema_problems:
        print(f"WARNING: design-summary.json failed {len(schema_problems)} schema check(s). See warnings.", file=sys.stderr)

    print(f"Created Figma handoff bundle: {output_dir}")
    print(f"- {summary_dir / 'design-handoff.md'}")
    print(f"- {summary_dir / 'design-summary.json'}")
    if image_paths:
        print(f"- {frames_dir} ({len(image_paths)} rendered frame files)")
    if asset_paths:
        print(f"- {output_dir / 'assets'} ({len(asset_paths)} rendered asset files)")
    if warnings:
        print(f"Warnings: {len(warnings)}. See design-handoff.md.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
