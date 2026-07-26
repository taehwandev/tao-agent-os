"""Parse Graphify output and measure structural relationship integrity."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from support.graphify_input_inspection import normalize_relative_path, project_knowledge_files


CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".java", ".js", ".kt",
    ".kts", ".mjs", ".py", ".rs", ".sh", ".swift", ".ts", ".tsx",
}
KNOWLEDGE_DOCUMENT_SUFFIXES = {
    ".json", ".md", ".mdx", ".rst", ".toml", ".txt", ".yaml", ".yml",
}


def inspect_graph_integrity(project_path: Path, graph_path: Path) -> dict[str, object]:
    payload = _read_graph(graph_path)
    if payload is None:
        return {}
    nodes, edges = payload
    node_types, node_sources, malformed_nodes, duplicate_nodes = _index_nodes(nodes)
    adjacency, invalid_edges, direct_edges = _index_edges(edges, node_types)
    relationship = _relationship_metrics(
        project_path, node_types, node_sources, adjacency
    )
    return {
        "graph_built_at_commit": payload.built_at_commit,
        "graph_mtime": graph_path.stat().st_mtime,
        "graph_node_count": len(node_types),
        "graph_malformed_node_count": malformed_nodes,
        "graph_duplicate_node_id_count": duplicate_nodes,
        "graph_edge_count": len(edges),
        "graph_invalid_edge_count": invalid_edges,
        "graph_document_code_edge_count": direct_edges,
        "graph_integrity_ready": bool(node_types)
        and malformed_nodes == 0
        and duplicate_nodes == 0
        and invalid_edges == 0,
        **relationship,
    }


def repair_graph_integrity(graph_path: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Remove only edges that cannot represent a valid graph relationship."""
    try:
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "graph_path": str(graph_path),
            "ready": False,
            "removed_edge_count": 0,
            "reason": "graph is missing or invalid JSON",
        }

    nodes = payload.get("nodes")
    edge_key = "links" if isinstance(payload.get("links"), list) else "edges"
    edges = payload.get(edge_key)
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return {
            "graph_path": str(graph_path),
            "ready": False,
            "removed_edge_count": 0,
            "reason": "graph nodes or edges are not lists",
        }

    node_ids = {
        str(node["id"])
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }
    valid_edges: list[dict[str, object]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids or source == target:
            continue
        valid_edges.append(edge)

    removed = len(edges) - len(valid_edges)
    if removed and not dry_run:
        payload[edge_key] = valid_edges
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=graph_path.parent,
                prefix=f".{graph_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
                temp_path = Path(handle.name)
            os.replace(temp_path, graph_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return {
        "graph_path": str(graph_path),
        "ready": True,
        "removed_edge_count": removed,
        "edge_count": len(valid_edges),
        "dry_run": dry_run,
    }


class _GraphPayload(tuple):
    built_at_commit: object

    def __new__(cls, nodes: list[object], edges: list[object], built_at_commit: object):
        value = super().__new__(cls, (nodes, edges))
        value.built_at_commit = built_at_commit
        return value


def _read_graph(graph_path: Path) -> _GraphPayload | None:
    if not graph_path.is_file():
        return None
    try:
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    nodes = payload.get("nodes")
    edges = payload.get("links", payload.get("edges"))
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None
    return _GraphPayload(nodes, edges, payload.get("built_at_commit"))


def _index_nodes(
    nodes: list[object],
) -> tuple[dict[str, str], dict[str, str], int, int]:
    node_types: dict[str, str] = {}
    node_sources: dict[str, str] = {}
    malformed = 0
    duplicates = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            malformed += 1
            continue
        node_id = str(node["id"])
        if node_id in node_types:
            duplicates += 1
            continue
        node_type = str(node.get("file_type") or "")
        if not node_type:
            malformed += 1
            continue
        node_types[node_id] = node_type
        if node.get("source_file"):
            node_sources[node_id] = normalize_relative_path(str(node["source_file"]))
    return node_types, node_sources, malformed, duplicates


def _index_edges(
    edges: list[object], node_types: dict[str, str]
) -> tuple[dict[str, set[str]], int, int]:
    adjacency = {node_id: set() for node_id in node_types}
    invalid = 0
    direct = 0
    for edge in edges:
        if not isinstance(edge, dict):
            invalid += 1
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_types or target not in node_types or source == target:
            invalid += 1
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
        if {node_types[source], node_types[target]} == {"code", "document"}:
            direct += 1
    return adjacency, invalid, direct


def _relationship_metrics(
    project_path: Path,
    node_types: dict[str, str],
    node_sources: dict[str, str],
    adjacency: dict[str, set[str]],
) -> dict[str, object]:
    document_nodes = sum(value == "document" for value in node_types.values())
    code_nodes = {
        node_id
        for node_id, value in node_types.items()
        if value == "code" and Path(node_sources.get(node_id, "")).suffix.lower() in CODE_SUFFIXES
    }
    connected = _nodes_connected_to(adjacency, code_nodes)
    document_path_nodes = sum(
        node_types[node_id] == "document" and node_id in connected for node_id in node_types
    )
    knowledge_documents = {
        path.relative_to(project_path).as_posix()
        for path in project_knowledge_files(project_path)
        if path.suffix.lower() in KNOWLEDGE_DOCUMENT_SUFFIXES
    }
    knowledge_nodes = {
        node_id for node_id, source in node_sources.items() if source in knowledge_documents
    }
    knowledge_paths = len(knowledge_nodes & connected)
    if code_nodes and knowledge_documents:
        ready = bool(knowledge_nodes and knowledge_paths)
    elif document_nodes and code_nodes:
        ready = document_path_nodes > 0
    else:
        ready = bool(node_types)
    return {
        "graph_document_node_count": document_nodes,
        "graph_code_node_count": len(code_nodes),
        "graph_document_code_path_node_count": document_path_nodes,
        "graph_knowledge_node_count": len(knowledge_nodes),
        "graph_knowledge_code_path_node_count": knowledge_paths,
        "graph_relationship_ready": ready,
    }


def _nodes_connected_to(
    adjacency: dict[str, set[str]], starts: set[str]
) -> set[str]:
    visited = set(starts)
    pending = list(starts)
    while pending:
        node_id = pending.pop()
        for neighbor in adjacency.get(node_id, ()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            pending.append(neighbor)
    return visited
