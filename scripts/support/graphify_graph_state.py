"""Compose Graphify integrity and freshness inspection results."""

from __future__ import annotations

from pathlib import Path

from support.graphify_graph_freshness import inspect_graph_freshness
from support.graphify_graph_integrity import inspect_graph_integrity


DEFAULT_GRAPH_STATE: dict[str, object] = {
    "project_head": None,
    "graph_built_at_commit": None,
    "graph_fresh": False,
    "graph_head_matches": False,
    "graph_head_comparison_ready": False,
    "graph_worktree_status_ready": False,
    "graph_source_dirty_count": 0,
    "graph_node_count": 0,
    "graph_malformed_node_count": 0,
    "graph_duplicate_node_id_count": 0,
    "graph_edge_count": 0,
    "graph_invalid_edge_count": 0,
    "graph_document_node_count": 0,
    "graph_code_node_count": 0,
    "graph_document_code_edge_count": 0,
    "graph_document_code_path_node_count": 0,
    "graph_knowledge_node_count": 0,
    "graph_knowledge_code_path_node_count": 0,
    "graph_manifest_stale_count": 0,
    "graph_integrity_ready": False,
    "graph_relationship_ready": False,
}


def inspect_project_graph_state(project_path: Path, graph_path: Path) -> dict[str, object]:
    state = dict(DEFAULT_GRAPH_STATE)
    integrity = inspect_graph_integrity(project_path, graph_path)
    if not integrity:
        return state
    state.update(integrity)
    state.update(
        inspect_graph_freshness(
            project_path,
            integrity.get("graph_built_at_commit"),
            float(integrity.get("graph_mtime") or 0),
            manifest_path=graph_path.parent / "manifest.json",
        )
    )
    state.pop("graph_mtime", None)
    return state
