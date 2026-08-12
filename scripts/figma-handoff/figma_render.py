from __future__ import annotations

import concurrent.futures
import re
import urllib.parse
from pathlib import Path
from typing import Any

from figma_api import API_BASE_URL, FigmaApi
from figma_util import normalize_node_id, slugify, write_json


_DOWNLOAD_WORKERS = 8
_RENDER_WORKERS = 4
_IMAGES_API_BATCH_SIZE = 100
_SAFE_NODE_ID = re.compile(r"^I?\d+:\d+(;I?\d+:\d+)*$")


class FigmaRenderer:
    """Resolve render URLs and download frames/assets through a bounded client."""

    def __init__(self, api: FigmaApi) -> None:
        self._api = api

    def render_nodes(
        self,
        file_key: str,
        node_ids: list[str],
        documents: dict[str, dict[str, Any]],
        output_dir: Path,
        raw_dir: Path,
        image_format: str,
        scale: float,
        warnings: list[str],
    ) -> dict[str, str]:
        names = {node_id: str(doc.get("name", node_id)) for node_id, doc in documents.items()}
        return _render_image_ids(
            self._api,
            file_key,
            node_ids,
            names,
            output_dir,
            raw_dir,
            image_format,
            scale,
            warnings,
            "image-response.json",
        )

    def render_assets(
        self,
        file_key: str,
        asset_candidates: list[dict[str, Any]],
        output_dir: Path,
        raw_dir: Path,
        warnings: list[str],
        scale: float = 3.0,
        max_assets: int | None = None,
    ) -> dict[str, str]:
        unique, representatives, members, names, formats = _dedupe_candidates(asset_candidates)
        if max_assets is not None and len(unique) > max_assets:
            warnings.append(
                f"Asset cap reached: rendered {max_assets} of {len(unique)} unique assets "
                f"(--max-assets={max_assets}); {len(unique) - max_assets} skipped."
            )
            unique = unique[:max_assets]

        discard: list[str] = []
        result: dict[str, str] = {}
        for image_format in ("svg", "png"):
            ids = [node_id for node_id, _ in unique if formats[node_id] == image_format]
            result.update(
                _render_image_ids(
                    self._api,
                    file_key,
                    ids,
                    names,
                    output_dir,
                    raw_dir,
                    image_format,
                    scale if image_format == "png" else 1.0,
                    discard,
                    f"asset-image-response-{image_format}.json",
                )
            )

        fallback_names: dict[tuple[str, str], str] = {}
        fallback_ids: dict[str, list[str]] = {"svg": [], "png": []}
        for node_id, candidate in unique:
            if node_id in result:
                continue
            image_format = formats[node_id]
            for ancestor in candidate.get("renderFallbackIds", []) or []:
                ancestor_id = normalize_node_id(str(ancestor.get("id", "")))
                key = (ancestor_id, image_format)
                if not _valid_node_id(ancestor_id) or key in fallback_names:
                    continue
                fallback_names[key] = str(ancestor.get("name", ancestor_id))
                fallback_ids[image_format].append(ancestor_id)

        fallback_result: dict[tuple[str, str], str] = {}
        for image_format in ("svg", "png"):
            ids = fallback_ids[image_format]
            if not ids:
                continue
            rendered = _render_image_ids(
                self._api,
                file_key,
                ids,
                {node_id: fallback_names[(node_id, image_format)] for node_id in ids},
                output_dir,
                raw_dir,
                image_format,
                scale if image_format == "png" else 1.0,
                discard,
                f"asset-fallback-response-{image_format}.json",
            )
            fallback_result.update({(node_id, image_format): path for node_id, path in rendered.items()})

        _apply_fallbacks(unique, formats, fallback_result, result)
        _propagate_dedup_results(representatives, members, result)
        for node_id, _ in unique:
            if node_id not in result:
                warnings.append(
                    "Asset not renderable standalone (leaf vector/glyph, Figma limitation): "
                    f"{names.get(node_id, node_id)} ({node_id})"
                )
        return result

def _render_image_ids(
    api: FigmaApi,
    file_key: str,
    node_ids: list[str],
    name_by_id: dict[str, str],
    output_dir: Path,
    raw_dir: Path,
    image_format: str,
    scale: float,
    warnings: list[str],
    response_filename: str,
) -> dict[str, str]:
    normalized_ids = [normalize_node_id(str(node_id)) for node_id in node_ids]
    if any(not _valid_node_id(node_id) for node_id in normalized_ids):
        raise RuntimeError("Figma render request contained an invalid node id.")
    if not normalized_ids:
        return {}
    batches = [
        normalized_ids[index : index + _IMAGES_API_BATCH_SIZE]
        for index in range(0, len(normalized_ids), _IMAGES_API_BATCH_SIZE)
    ]

    def resolve(batch: list[str]) -> tuple[dict[str, str | None], str | None]:
        query = {"ids": ",".join(batch), "format": image_format}
        if image_format in {"png", "jpg"}:
            query["scale"] = str(scale)
        try:
            response = api.get_json(
                f"{API_BASE_URL}/images/{file_key}?{urllib.parse.urlencode(query)}"
            )
        except RuntimeError as error:
            return {}, f"Render API failed: {error}"
        images = response.get("images", {})
        if not isinstance(images, dict):
            return {}, "Render API returned a malformed images object."
        return {
            normalize_node_id(str(node_id)): url if isinstance(url, str) else None
            for node_id, url in images.items()
        }, None

    image_urls: dict[str, str | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_RENDER_WORKERS, len(batches))) as pool:
        for images, error in pool.map(resolve, batches):
            if error:
                warnings.append(error)
            image_urls.update(images)
    write_json(
        raw_dir / response_filename,
        {node_id: {"rendered": bool(url)} for node_id, url in image_urls.items()},
    )
    for node_id, url in image_urls.items():
        if not url:
            warnings.append(f"Figma did not render image for node {node_id}.")

    def download(item: tuple[str, str]) -> tuple[str, str | None, str | None]:
        node_id, url = item
        try:
            path = _output_path(output_dir, name_by_id.get(node_id, node_id), node_id, image_format)
            api.download(url, path, image_format)
            return node_id, str(path), None
        except RuntimeError as error:
            return node_id, None, f"Image download failed for node {node_id}: {error}"

    downloadable = [(node_id, url) for node_id, url in image_urls.items() if url]
    result: dict[str, str] = {}
    if downloadable:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(_DOWNLOAD_WORKERS, len(downloadable))) as pool:
            for node_id, path, error in pool.map(download, downloadable):
                if path:
                    result[node_id] = path
                elif error:
                    warnings.append(error)
    return result


def _dedupe_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[
    list[tuple[str, dict[str, Any]]],
    dict[str, str],
    dict[str, list[str]],
    dict[str, str],
    dict[str, str],
]:
    unique: list[tuple[str, dict[str, Any]]] = []
    seen_nodes: set[str] = set()
    representatives: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    formats: dict[str, str] = {}
    for candidate in candidates:
        node_id = normalize_node_id(str(candidate.get("id", "")))
        if not _valid_node_id(node_id) or node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        key = str(candidate.get("dedupKey") or node_id)
        members.setdefault(key, []).append(node_id)
        if key in representatives:
            continue
        representatives[key] = node_id
        unique.append((node_id, candidate))
        names[node_id] = str(candidate.get("name", node_id))
        formats[node_id] = "png" if candidate.get("imageRefs") else "svg"
    return unique, representatives, members, names, formats


def _apply_fallbacks(
    unique: list[tuple[str, dict[str, Any]]],
    formats: dict[str, str],
    fallback_result: dict[tuple[str, str], str],
    result: dict[str, str],
) -> None:
    for node_id, candidate in unique:
        if node_id in result:
            continue
        image_format = formats[node_id]
        for ancestor in candidate.get("renderFallbackIds", []) or []:
            key = (normalize_node_id(str(ancestor.get("id", ""))), image_format)
            if key in fallback_result:
                result[node_id] = fallback_result[key]
                break


def _propagate_dedup_results(
    representatives: dict[str, str],
    members: dict[str, list[str]],
    result: dict[str, str],
) -> None:
    for key, node_ids in members.items():
        representative_path = result.get(representatives[key])
        if representative_path:
            result.update({node_id: representative_path for node_id in node_ids})


def _valid_node_id(node_id: str) -> bool:
    return bool(_SAFE_NODE_ID.fullmatch(node_id))


def _output_path(output_dir: Path, name: str, node_id: str, image_format: str) -> Path:
    safe_id = node_id.replace(":", "-").replace(";", "_")
    candidate = output_dir / f"{slugify(name)}__{safe_id}.{image_format}"
    root = output_dir.resolve()
    try:
        candidate.resolve().relative_to(root)
    except ValueError as error:
        raise RuntimeError("Generated asset path escaped the output directory.") from error
    return candidate
