from __future__ import annotations

import concurrent.futures
import re
import urllib.parse
from pathlib import Path
from typing import Any

from figma_api import API_BASE_URL, download_file, request_json
from figma_util import iter_nodes, normalize_node_id, slugify, write_json

_DOWNLOAD_WORKERS = 8
_RENDER_WORKERS = 4


RENDERABLE_TYPES = {
    "FRAME",
    "COMPONENT",
    "COMPONENT_SET",
    "INSTANCE",
    "GROUP",
    "SECTION",
    "RECTANGLE",
}
TRANSITION_KEYS = {
    "transitionnodeid",
    "destinationid",
    "destinationnodeid",
}
_NODES_API_BATCH_SIZE = 100
_NODES_API_MAX_QUERY_CHARS = 7000
_IMAGES_API_BATCH_SIZE = 100


def fetch_image_fills(file_key: str, token: str, timeout: int) -> dict[str, Any]:
    return request_json(f"{API_BASE_URL}/files/{file_key}/images", token, timeout)


def fetch_flow_nodes(
    file_key: str,
    start_node_id: str,
    token: str,
    max_flow_depth: int,
    timeout: int,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, str]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    visited: set[str] = set()
    pending: list[str] = [start_node_id]
    raw_responses: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    file_styles: dict[str, dict[str, Any]] = {}
    file_components: dict[str, Any] = {}
    file_component_sets: dict[str, Any] = {}

    for _depth in range(max_flow_depth + 1):
        ids_to_fetch = [node_id for node_id in pending if node_id not in visited]
        if not ids_to_fetch:
            break

        next_pending: list[str] = []
        for batch_index, batch in enumerate(chunk_node_ids(ids_to_fetch), start=1):
            url = build_nodes_url(file_key, batch)
            try:
                response = request_json(url, token, timeout)
            except RuntimeError as error:
                warnings.append(f"Figma nodes fetch failed at depth {_depth} batch {batch_index}: {error}")
                continue
            raw_responses.append(response)

            if response.get("error") or str(response.get("status", "")).startswith(("4", "5")):
                warnings.append(
                    f"Figma nodes API returned an error response at depth {_depth} batch {batch_index}: "
                    f"status={response.get('status')} error={response.get('err', response.get('error'))}"
                )
                continue

            for requested_id, node_payload in response.get("nodes", {}).items():
                normalized_requested_id = normalize_node_id(requested_id)
                visited.add(normalized_requested_id)

                if not node_payload:
                    warnings.append(f"Node {normalized_requested_id} was not returned by Figma.")
                    continue

                document = node_payload.get("document")
                if not isinstance(document, dict):
                    warnings.append(f"Node {normalized_requested_id} has no document payload.")
                    continue

                document_id = normalize_node_id(str(document.get("id", normalized_requested_id)))
                visited.add(document_id)
                documents[document_id] = document

                payload_styles = node_payload.get("styles", {})
                if isinstance(payload_styles, dict):
                    file_styles.update({normalize_node_id(k): v for k, v in payload_styles.items()})

                # File-level component definitions are included in node_payload.
                # Keep componentId -> metadata and componentSetId -> metadata.
                payload_components = node_payload.get("components")
                if isinstance(payload_components, dict):
                    file_components.update(payload_components)
                payload_component_sets = node_payload.get("componentSets")
                if isinstance(payload_component_sets, dict):
                    file_component_sets.update(payload_component_sets)

                for edge in collect_flow_edges(document):
                    edges.append(edge)
                    if _depth < max_flow_depth:
                        target_id = edge["toNodeId"]
                        if target_id not in visited and target_id not in next_pending:
                            next_pending.append(target_id)

        pending = next_pending

    component_index = {"components": file_components, "componentSets": file_component_sets}
    return raw_responses, documents, dedupe_edges(edges), file_styles, component_index


def build_nodes_url(file_key: str, node_ids: list[str]) -> str:
    return f"{API_BASE_URL}/files/{file_key}/nodes?{urllib.parse.urlencode({'ids': ','.join(node_ids)})}"


def chunk_node_ids(
    node_ids: list[str],
    max_batch_size: int = _NODES_API_BATCH_SIZE,
    max_query_chars: int = _NODES_API_MAX_QUERY_CHARS,
) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for node_id in node_ids:
        candidate = [*current, node_id]
        encoded_length = len(urllib.parse.urlencode({"ids": ",".join(candidate)}))
        if current and (len(candidate) > max_batch_size or encoded_length > max_query_chars):
            chunks.append(current)
            current = [node_id]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def collect_flow_edges(root: dict[str, Any]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []

    for node in iter_nodes(root):
        node_id = normalize_node_id(str(node.get("id", "")))
        if not node_id:
            continue

        shallow = {key: value for key, value in node.items() if key != "children"}
        for target_id in find_transition_ids(shallow):
            if target_id == node_id:
                continue
            edges.append(
                {
                    "fromNodeId": node_id,
                    "fromName": str(node.get("name", "")),
                    "toNodeId": target_id,
                }
            )

    return edges

def find_transition_ids(value: Any) -> list[str]:
    found: list[str] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                if isinstance(child, str) and is_transition_key(key.lower()) and looks_like_node_id(child):
                    found.append(normalize_node_id(child))
                else:
                    walk(child)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(value)
    return list(dict.fromkeys(found))

def is_transition_key(key: str) -> bool:
    return key in TRANSITION_KEYS or ("destination" in key and "id" in key)

def looks_like_node_id(value: str) -> bool:
    return bool(re.match(r"^I?\d+[:\-]\d+(;I?\d+[:\-]\d+)*$", value))

def dedupe_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for edge in edges:
        key = (edge["fromNodeId"], edge["toNodeId"])
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result

def fetch_style_node_details(
    file_key: str,
    style_node_ids: list[str],
    token: str,
    timeout: int,
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    if not style_node_ids:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for batch in chunk_node_ids(style_node_ids):
        url = build_nodes_url(file_key, batch)
        try:
            response = request_json(url, token, timeout)
            for node_id, payload in response.get("nodes", {}).items():
                if payload:
                    doc = payload.get("document")
                    if isinstance(doc, dict):
                        result[normalize_node_id(node_id)] = doc
        except RuntimeError as error:
            warnings.append(f"Style node detail fetch failed: {error}")
    return result

def fetch_named_styles(
    file_key: str,
    token: str,
    timeout: int,
    warnings: list[str],
) -> dict[str, Any]:
    all_styles: list[dict[str, Any]] = []
    first_result: dict[str, Any] | None = None
    after: str | None = None
    seen_cursors: set[str] = set()

    while True:
        query = {"page_size": "1000"}
        if after:
            query["after"] = after
        url = f"{API_BASE_URL}/files/{file_key}/styles?{urllib.parse.urlencode(query)}"
        try:
            result = request_json(url, token, timeout)
        except RuntimeError as error:
            if first_result is not None:
                warnings.append(f"Named styles pagination stopped after {len(all_styles)} styles: {error}")
                break
            warnings.append(f"Named styles fetch failed: {error}")
            return {}

        if first_result is None:
            first_result = result

        meta = result.get("meta", {})
        if isinstance(meta, dict):
            page_styles = meta.get("styles", [])
            if isinstance(page_styles, list):
                all_styles.extend([style for style in page_styles if isinstance(style, dict)])
            cursor = meta.get("cursor")
        else:
            cursor = None

        next_after = cursor.get("after") if isinstance(cursor, dict) else None
        if not next_after:
            break
        next_after = str(next_after)
        if next_after in seen_cursors:
            warnings.append("Named styles pagination stopped because Figma returned a repeated cursor.")
            break
        seen_cursors.add(next_after)
        after = next_after

    if first_result is None:
        return {}

    merged = dict(first_result)
    merged_meta = dict(merged.get("meta", {})) if isinstance(merged.get("meta"), dict) else {}
    merged_meta["styles"] = all_styles
    merged_meta.pop("cursor", None)
    merged["meta"] = merged_meta
    return merged

def fetch_variables(
    file_key: str,
    token: str,
    timeout: int,
    warnings: list[str],
) -> dict[str, Any]:
    try:
        return request_json(f"{API_BASE_URL}/files/{file_key}/variables/local", token, timeout)
    except RuntimeError as error:
        if "(403)" in str(error):
            warnings.append(
                "Variables fetch skipped: /variables/local requires a Figma Enterprise Plan. "
                "Design token variables will not be included in this handoff."
            )
        else:
            warnings.append(f"Variables fetch failed: {error}")
        return {}

def render_nodes(
    file_key: str,
    node_ids: list[str],
    documents: dict[str, dict[str, Any]],
    token: str,
    output_dir: Path,
    raw_dir: Path,
    image_format: str,
    scale: float,
    timeout: int,
    warnings: list[str],
) -> dict[str, str]:
    name_by_id = {node_id: str(doc.get("name", node_id)) for node_id, doc in documents.items()}
    return _render_image_ids(
        file_key=file_key,
        node_ids=node_ids,
        name_by_id=name_by_id,
        token=token,
        output_dir=output_dir,
        raw_dir=raw_dir,
        image_format=image_format,
        scale=scale,
        timeout=timeout,
        warnings=warnings,
        response_filename="image-response.json",
    )


def render_asset_nodes(
    file_key: str,
    asset_candidates: list[dict[str, Any]],
    token: str,
    output_dir: Path,
    raw_dir: Path,
    timeout: int,
    warnings: list[str],
    scale: float = 3.0,
    max_assets: int | None = None,
) -> dict[str, str]:
    """Render icon, vector, and image-fill candidates as individual files.

    Unlike screen-frame rendering, this extracts nodes inside a frame by id.
    Image-fill nodes become PNG because Figma may not render them as SVG; pure
    vectors and boolean operations become SVG. Deeply nested leaf vectors and
    system glyphs can return null because Figma does not support standalone
    rendering; the tool records those cases as warnings.
    """
    # Render one representative per dedupKey and map the remaining instances to
    # its result, avoiding repeated downloads of the same icon.
    uniq: list[tuple[str, dict[str, Any]]] = []
    seen_nodes: set[str] = set()
    rep_by_key: dict[str, str] = {}
    members_by_key: dict[str, list[str]] = {}
    name_by_id: dict[str, str] = {}
    origin_format: dict[str, str] = {}
    for candidate in asset_candidates:
        node_id = normalize_node_id(str(candidate.get("id", "")))
        if not node_id or node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        key = str(candidate.get("dedupKey") or node_id)
        members_by_key.setdefault(key, []).append(node_id)
        if key in rep_by_key:
            continue
        rep_by_key[key] = node_id
        uniq.append((node_id, candidate))
        name_by_id[node_id] = str(candidate.get("name", node_id))
        origin_format[node_id] = "png" if candidate.get("imageRefs") else "svg"

    # Cap unique assets when requested and report every skipped item.
    if max_assets is not None and max_assets >= 0 and len(uniq) > max_assets:
        skipped = len(uniq) - max_assets
        warnings.append(
            f"Asset cap reached: rendered {max_assets} of {len(uniq)} unique assets "
            f"(--max-assets={max_assets}); {skipped} skipped."
        )
        uniq = uniq[:max_assets]

    def render_group(ids: list[str], names: dict[str, str], image_format: str, response_filename: str, sink: list[str]) -> dict[str, str]:
        return _render_image_ids(
            file_key=file_key,
            node_ids=ids,
            name_by_id=names,
            token=token,
            output_dir=output_dir,
            raw_dir=raw_dir,
            image_format=image_format,
            scale=scale if image_format in {"png", "jpg"} else 1.0,
            timeout=timeout,
            warnings=sink,
            response_filename=response_filename,
        )

    # Pass 1: render each candidate in its native format; null is not final yet.
    discard: list[str] = []
    result: dict[str, str] = {}
    result.update(render_group(
        [nid for nid, _ in uniq if origin_format[nid] == "svg"],
        name_by_id, "svg", "asset-image-response-svg.json", discard,
    ))
    result.update(render_group(
        [nid for nid, _ in uniq if origin_format[nid] == "png"],
        name_by_id, "png", "asset-image-response-png.json", discard,
    ))

    # Pass 2: try the ancestor fallback chain for candidates that did not render.
    fallback_name: dict[str, str] = {}
    fallback_ids: dict[str, list[str]] = {"svg": [], "png": []}
    for node_id, candidate in uniq:
        if node_id in result:
            continue
        image_format = origin_format[node_id]
        for ancestor in candidate.get("renderFallbackIds", []) or []:
            ancestor_id = normalize_node_id(str(ancestor.get("id", "")))
            if not ancestor_id or ancestor_id in fallback_name:
                continue
            fallback_name[ancestor_id] = str(ancestor.get("name", ancestor_id))
            fallback_ids[image_format].append(ancestor_id)

    fallback_result: dict[str, str] = {}
    for image_format, response_filename in (("svg", "asset-fallback-response-svg.json"), ("png", "asset-fallback-response-png.json")):
        if fallback_ids[image_format]:
            fallback_result.update(render_group(
                fallback_ids[image_format], fallback_name, image_format, response_filename, discard,
            ))

    for node_id, candidate in uniq:
        if node_id in result:
            continue
        for ancestor in candidate.get("renderFallbackIds", []) or []:
            ancestor_id = normalize_node_id(str(ancestor.get("id", "")))
            if ancestor_id in fallback_result:
                result[node_id] = fallback_result[ancestor_id]
                break

    # Propagate the representative result to every node id in the dedup group.
    for key, members in members_by_key.items():
        rep_path = result.get(rep_by_key[key])
        if rep_path is None:
            continue
        for member_id in members:
            if member_id != rep_by_key[key]:
                result[member_id] = rep_path

    # Report only nodes that remain unavailable after fallback attempts.
    for node_id, _ in uniq:
        if node_id not in result:
            warnings.append(
                f"Asset not renderable standalone (leaf vector/glyph, Figma limitation): "
                f"{name_by_id.get(node_id, node_id)} ({node_id})"
            )
    return result


def _render_image_ids(
    file_key: str,
    node_ids: list[str],
    name_by_id: dict[str, str],
    token: str,
    output_dir: Path,
    raw_dir: Path,
    image_format: str,
    scale: float,
    timeout: int,
    warnings: list[str],
    response_filename: str,
) -> dict[str, str]:
    if not node_ids:
        return {}

    clamped_scale = max(0.01, min(4.0, scale))
    batches = [
        (i // _IMAGES_API_BATCH_SIZE + 1, node_ids[i : i + _IMAGES_API_BATCH_SIZE])
        for i in range(0, len(node_ids), _IMAGES_API_BATCH_SIZE)
    ]

    def _resolve(item: tuple[int, list[str]]) -> tuple[dict[str, Any], str | None]:
        batch_no, batch = item
        query: dict[str, str] = {"ids": ",".join(batch), "format": image_format}
        if image_format in {"png", "jpg"}:
            query["scale"] = str(clamped_scale)
        try:
            response = request_json(
                f"{API_BASE_URL}/images/{file_key}?{urllib.parse.urlencode(query)}", token, timeout
            )
        except RuntimeError as error:
            return {}, f"Render API failed for batch {batch_no}: {error}"
        return response.get("images", {}), None

    # Figma server-side render calls are latency-bound, so run batches in parallel
    # with deliberately low concurrency to leave room for rate limits.
    all_image_urls: dict[str, str | None] = {}
    if batches:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(_RENDER_WORKERS, len(batches))
        ) as pool:
            for images, error in pool.map(_resolve, batches):
                if error:
                    warnings.append(error)
                    continue
                all_image_urls.update({
                    normalize_node_id(k): v for k, v in images.items()
                })

    # Figma render URLs are signed and short-lived. The downloaded files are the useful
    # artifact, so persist only availability metadata instead of credential-like URLs.
    write_json(
        raw_dir / response_filename,
        {node_id: {"rendered": bool(image_url)} for node_id, image_url in all_image_urls.items()},
    )

    for node_id, image_url in all_image_urls.items():
        if not image_url:
            warnings.append(f"Figma did not render image for node {node_id}.")

    downloadable = [(nid, url) for nid, url in all_image_urls.items() if url]

    def _download(item: tuple[str, str]) -> tuple[str, str | None, str | None]:
        node_id, image_url = item
        node_name = name_by_id.get(node_id, node_id)
        file_name = f"{slugify(node_name)}__{node_id.replace(':', '-')}.{image_format}"
        file_path = output_dir / file_name
        try:
            download_file(image_url, file_path, timeout)
            return node_id, str(file_path), None
        except RuntimeError as error:
            return node_id, None, f"Image download failed for node {node_id}: {error}"

    # Downloads are I/O-bound; use a small thread pool to avoid serial round trips.
    result: dict[str, str] = {}
    if downloadable:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(_DOWNLOAD_WORKERS, len(downloadable))
        ) as pool:
            for node_id, file_path, error in pool.map(_download, downloadable):
                if file_path:
                    result[node_id] = file_path
                elif error:
                    warnings.append(error)

    return result
