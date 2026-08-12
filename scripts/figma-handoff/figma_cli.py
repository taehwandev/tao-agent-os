from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from figma_api import FigmaApi
from figma_bundle_output import FigmaBundleOutput
from figma_cli_arguments import FigmaCliArguments
from figma_flow_fetch import FigmaFlowFetcher
from figma_metadata_fetch import FigmaMetadataFetcher
from figma_render import FigmaRenderer
from figma_summary import build_summary
from figma_util import normalize_node_id, resolve_figma_target, write_json


_RENDERABLE_TYPES = {
    "FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE", "GROUP", "SECTION", "RECTANGLE",
}


class FigmaHandoffCli:
    """Validate CLI intent and delegate one handoff-bundle build."""

    def run(self, argv: list[str] | None = None) -> int:
        arguments = FigmaCliArguments(argv)
        if arguments.error:
            print(f"ERROR: {arguments.error}", file=sys.stderr)
            return 2
        try:
            file_key, node_id = resolve_figma_target(
                arguments.values.url, arguments.values.file_key, arguments.values.node_id
            )
        except ValueError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        output_dir = arguments.output_dir(node_id)
        if arguments.values.dry_run:
            arguments.print_plan(file_key, node_id, output_dir)
            return 0
        token = os.environ.get(arguments.values.token_env)
        if not token:
            print(f"ERROR: Set {arguments.values.token_env} before running this command.", file=sys.stderr)
            return 2
        return _execute(arguments.values, file_key, node_id, output_dir, token)

    @staticmethod
    def portable_paths(paths: dict[str, str], bundle_dir: Path) -> dict[str, str]:
        return FigmaBundleOutput(bundle_dir).portable_paths(paths)


def _execute(args: Any, file_key: str, node_id: str, output_dir: Path, token: str) -> int:
    output = FigmaBundleOutput(output_dir)
    raw_dir, frames_dir, _ = output.create_directories()
    warnings: list[str] = []
    api = FigmaApi(token, args.timeout)
    raw_responses, documents, edges, file_styles, components = FigmaFlowFetcher(api).fetch(
        file_key, node_id, args.max_flow_depth, warnings
    )
    write_json(raw_dir / "nodes.json", raw_responses)
    if node_id not in documents:
        print(
            f"ERROR: Figma start node {node_id} was not fetched. "
            f"Raw node response was written to {raw_dir / 'nodes.json'}.",
            file=sys.stderr,
        )
        return 1

    renderer = FigmaRenderer(api)
    image_paths: dict[str, str] = {}
    if not args.no_images:
        render_ids = [key for key, value in documents.items() if value.get("type") in _RENDERABLE_TYPES]
        image_paths = output.portable_paths(
            renderer.render_nodes(
                file_key, render_ids, documents, frames_dir, raw_dir,
                args.format, args.scale, warnings,
            )
        )
    metadata = FigmaMetadataFetcher(api)
    if args.include_image_fills:
        try:
            write_json(raw_dir / "image-fills.json", metadata.image_fills(file_key))
        except RuntimeError as error:
            warnings.append(f"Image fills fetch failed: {error}")
    named_styles = metadata.named_styles(file_key, warnings)
    variables = metadata.variables(file_key, warnings)
    write_json(raw_dir / "styles.json", named_styles)
    write_json(raw_dir / "variables.json", variables)
    style_details = _style_details(metadata, file_key, named_styles, documents, warnings)
    write_json(raw_dir / "style-nodes.json", style_details)
    summary = build_summary(
        file_key=file_key, start_node_id=node_id, source_url=args.url,
        node_documents=documents, flow_edges=edges, image_paths=image_paths,
        named_styles=named_styles, style_node_details=style_details, variables=variables,
        file_styles=file_styles, warnings=warnings, component_index=components,
    )
    output.persist(summary, warnings, args)
    asset_paths = _render_assets(renderer, args, file_key, summary, output, raw_dir, warnings)
    problems = output.persist(summary, warnings, args)
    output.report(image_paths, asset_paths, warnings, problems)
    return 0


def _render_assets(
    renderer: FigmaRenderer,
    args: Any,
    file_key: str,
    summary: dict[str, Any],
    output: FigmaBundleOutput,
    raw_dir: Path,
    warnings: list[str],
) -> dict[str, str]:
    if not args.export_assets:
        return {}
    assets_dir = output.root / "assets"
    assets_dir.mkdir(exist_ok=True)
    paths = output.portable_paths(
        renderer.render_assets(
            file_key, summary.get("assetCandidates", []), assets_dir, raw_dir,
            warnings, args.scale, args.max_assets,
        )
    )
    for candidate in summary.get("assetCandidates", []):
        if candidate.get("id") in paths:
            candidate["assetPath"] = paths[candidate["id"]]
    return paths


def _style_details(
    metadata: FigmaMetadataFetcher,
    file_key: str,
    named_styles: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    styles = named_styles.get("meta", {}).get("styles", [])
    ids = [normalize_node_id(str(item.get("node_id", ""))) for item in styles if item.get("node_id")]
    details = {item: documents[item] for item in ids if item in documents}
    details.update(metadata.style_node_details(file_key, [item for item in ids if item not in documents], warnings))
    return details
