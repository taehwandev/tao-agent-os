from __future__ import annotations

import urllib.parse
from typing import Any

from figma_api import API_BASE_URL, FigmaApi
from figma_util import normalize_node_id


_NODES_API_BATCH_SIZE = 100
_NODES_API_MAX_QUERY_CHARS = 7000


class FigmaMetadataFetcher:
    """Fetch optional file metadata without making Dev Mode a hard dependency."""

    def __init__(self, api: FigmaApi) -> None:
        self._api = api

    def image_fills(self, file_key: str) -> dict[str, Any]:
        return self._api.get_json(f"{API_BASE_URL}/files/{file_key}/images")

    def style_node_details(
        self,
        file_key: str,
        style_node_ids: list[str],
        warnings: list[str],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for batch in _chunk_node_ids(style_node_ids):
            try:
                response = self._api.get_json(_nodes_url(file_key, batch))
            except RuntimeError as error:
                warnings.append(f"Style node detail fetch failed: {error}")
                continue
            nodes = response.get("nodes", {})
            if not isinstance(nodes, dict):
                warnings.append("Style node detail fetch returned a malformed nodes object.")
                continue
            for node_id, payload in nodes.items():
                document = payload.get("document") if isinstance(payload, dict) else None
                if isinstance(document, dict):
                    result[normalize_node_id(str(node_id))] = document
        return result

    def named_styles(self, file_key: str, warnings: list[str]) -> dict[str, Any]:
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
                result = self._api.get_json(url)
            except RuntimeError as error:
                if first_result is None:
                    warnings.append(f"Named styles fetch failed: {error}")
                    return {}
                warnings.append(
                    f"Named styles pagination stopped after {len(all_styles)} styles: {error}"
                )
                break
            if first_result is None:
                first_result = result
            meta = result.get("meta", {})
            page_styles = meta.get("styles", []) if isinstance(meta, dict) else []
            if isinstance(page_styles, list):
                all_styles.extend(item for item in page_styles if isinstance(item, dict))
            cursor = meta.get("cursor") if isinstance(meta, dict) else None
            next_after = cursor.get("after") if isinstance(cursor, dict) else None
            if not next_after:
                break
            after = str(next_after)
            if after in seen_cursors:
                warnings.append("Named styles pagination stopped because Figma returned a repeated cursor.")
                break
            seen_cursors.add(after)
        if first_result is None:
            return {}
        merged = dict(first_result)
        merged_meta = dict(merged.get("meta", {})) if isinstance(merged.get("meta"), dict) else {}
        merged_meta["styles"] = all_styles
        merged_meta.pop("cursor", None)
        merged["meta"] = merged_meta
        return merged

    def variables(self, file_key: str, warnings: list[str]) -> dict[str, Any]:
        try:
            return self._api.get_json(f"{API_BASE_URL}/files/{file_key}/variables/local")
        except RuntimeError as error:
            if "(403)" in str(error):
                warnings.append(
                    "Variables fetch skipped: current access or plan cannot read /variables/local. "
                    "The handoff remains usable without Dev Mode variables."
                )
            else:
                warnings.append(f"Variables fetch failed: {error}")
            return {}


def _nodes_url(file_key: str, node_ids: list[str]) -> str:
    query = urllib.parse.urlencode({"ids": ",".join(node_ids)})
    return f"{API_BASE_URL}/files/{file_key}/nodes?{query}"


def _chunk_node_ids(node_ids: list[str]) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for node_id in node_ids:
        candidate = [*current, node_id]
        encoded_length = len(urllib.parse.urlencode({"ids": ",".join(candidate)}))
        if current and (
            len(candidate) > _NODES_API_BATCH_SIZE
            or encoded_length > _NODES_API_MAX_QUERY_CHARS
        ):
            chunks.append(current)
            current = [node_id]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
