from __future__ import annotations

import re
import urllib.parse
from typing import Any

from figma_api import API_BASE_URL, FigmaApi
from figma_util import iter_nodes, normalize_node_id


_TRANSITION_KEYS = {"transitionnodeid", "destinationid", "destinationnodeid"}
_NODES_API_BATCH_SIZE = 100
_NODES_API_MAX_QUERY_CHARS = 7000


class FigmaFlowFetcher:
    """Fetch a prototype flow while keeping traversal and API batching together."""

    def __init__(self, api: FigmaApi) -> None:
        self._api = api

    def fetch(
        self,
        file_key: str,
        start_node_id: str,
        max_flow_depth: int,
        warnings: list[str],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        list[dict[str, str]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        visited: set[str] = set()
        pending = [start_node_id]
        raw_responses: list[dict[str, Any]] = []
        documents: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []
        file_styles: dict[str, dict[str, Any]] = {}
        file_components: dict[str, Any] = {}
        file_component_sets: dict[str, Any] = {}

        for depth in range(max_flow_depth + 1):
            ids_to_fetch = [node_id for node_id in pending if node_id not in visited]
            if not ids_to_fetch:
                break
            next_pending: list[str] = []
            for batch_index, batch in enumerate(_chunk_node_ids(ids_to_fetch), start=1):
                try:
                    response = self._api.get_json(_nodes_url(file_key, batch))
                except RuntimeError as error:
                    warnings.append(
                        f"Figma nodes fetch failed at depth {depth} batch {batch_index}: {error}"
                    )
                    continue
                raw_responses.append(response)
                if response.get("error") or str(response.get("status", "")).startswith(("4", "5")):
                    warnings.append(
                        f"Figma nodes API returned an error response at depth {depth} "
                        f"batch {batch_index}: status={response.get('status')}"
                    )
                    continue
                _merge_response(
                    response,
                    depth,
                    max_flow_depth,
                    visited,
                    documents,
                    edges,
                    file_styles,
                    file_components,
                    file_component_sets,
                    next_pending,
                    warnings,
                )
            pending = next_pending

        component_index = {
            "components": file_components,
            "componentSets": file_component_sets,
        }
        return raw_responses, documents, _dedupe_edges(edges), file_styles, component_index


def _merge_response(
    response: dict[str, Any],
    depth: int,
    max_flow_depth: int,
    visited: set[str],
    documents: dict[str, dict[str, Any]],
    edges: list[dict[str, str]],
    file_styles: dict[str, dict[str, Any]],
    file_components: dict[str, Any],
    file_component_sets: dict[str, Any],
    next_pending: list[str],
    warnings: list[str],
) -> None:
    nodes = response.get("nodes", {})
    if not isinstance(nodes, dict):
        warnings.append("Figma nodes API returned a malformed nodes object.")
        return
    for requested_id, node_payload in nodes.items():
        normalized_requested_id = normalize_node_id(str(requested_id))
        visited.add(normalized_requested_id)
        if not isinstance(node_payload, dict):
            warnings.append(f"Node {normalized_requested_id} was not returned by Figma.")
            continue
        document = node_payload.get("document")
        if not isinstance(document, dict):
            warnings.append(f"Node {normalized_requested_id} has no document payload.")
            continue
        document_id = normalize_node_id(str(document.get("id", normalized_requested_id)))
        visited.add(document_id)
        documents[document_id] = document
        _merge_mapping(file_styles, node_payload.get("styles"), normalize_keys=True)
        _merge_mapping(file_components, node_payload.get("components"))
        _merge_mapping(file_component_sets, node_payload.get("componentSets"))
        for edge in _collect_flow_edges(document):
            edges.append(edge)
            target_id = edge["toNodeId"]
            if depth < max_flow_depth and target_id not in visited and target_id not in next_pending:
                next_pending.append(target_id)


def _merge_mapping(target: dict[str, Any], value: Any, normalize_keys: bool = False) -> None:
    if not isinstance(value, dict):
        return
    if normalize_keys:
        target.update({normalize_node_id(str(key)): item for key, item in value.items()})
    else:
        target.update(value)


def _nodes_url(file_key: str, node_ids: list[str]) -> str:
    query = urllib.parse.urlencode({"ids": ",".join(node_ids)})
    return f"{API_BASE_URL}/files/{file_key}/nodes?{query}"


def _chunk_node_ids(
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


def _collect_flow_edges(root: dict[str, Any]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for node in iter_nodes(root):
        node_id = normalize_node_id(str(node.get("id", "")))
        if not node_id:
            continue
        shallow = {key: value for key, value in node.items() if key != "children"}
        for target_id in _find_transition_ids(shallow):
            if target_id != node_id:
                edges.append(
                    {
                        "fromNodeId": node_id,
                        "fromName": str(node.get("name", "")),
                        "toNodeId": target_id,
                    }
                )
    return edges


def _find_transition_ids(value: Any) -> list[str]:
    found: list[str] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                lower_key = str(key).lower()
                if isinstance(child, str) and _is_transition_key(lower_key) and _looks_like_node_id(child):
                    found.append(normalize_node_id(child))
                else:
                    walk(child)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(value)
    return list(dict.fromkeys(found))


def _is_transition_key(key: str) -> bool:
    return key in _TRANSITION_KEYS or ("destination" in key and "id" in key)


def _looks_like_node_id(value: str) -> bool:
    return bool(re.fullmatch(r"I?\d+[:\-]\d+(;I?\d+[:\-]\d+)*", value))


def _dedupe_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for edge in edges:
        key = (edge["fromNodeId"], edge["toNodeId"])
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result
