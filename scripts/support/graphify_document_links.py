"""Deterministic project-document to source-file Graphify relationships."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from support.graphify_contract import PROJECT_GRAPH_PATH


EDGE_ORIGIN = "tao_explicit_path"
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".java", ".js", ".kt",
    ".kts", ".mjs", ".py", ".rs", ".sh", ".swift", ".ts", ".tsx",
}
DOCUMENT_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:\.?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)"
)


def repair_project_document_links(
    project_path: Path, *, dry_run: bool = False
) -> dict[str, object]:
    graph_path = project_path / PROJECT_GRAPH_PATH
    result: dict[str, object] = {
        "graph_path": str(graph_path),
        "document_files_scanned": 0,
        "explicit_source_paths_found": 0,
        "document_source_edges": 0,
        "changed": False,
        "ready": False,
    }
    if not graph_path.is_file():
        return result
    try:
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    nodes = payload.get("nodes")
    links = payload.get("links", payload.get("edges"))
    if not isinstance(nodes, list) or not isinstance(links, list):
        return result

    source_nodes: dict[str, list[dict[str, object]]] = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        source = _normalize_relative(str(node.get("source_file") or ""))
        if source:
            source_nodes.setdefault(source, []).append(node)

    code_targets = {
        source: _select_file_node(candidates, source)
        for source, candidates in source_nodes.items()
        if Path(source).suffix.lower() in CODE_SUFFIXES
    }
    code_targets = {key: value for key, value in code_targets.items() if value}
    existing = {
        (str(edge.get("source")), str(edge.get("target")), str(edge.get("relation")))
        for edge in links
        if isinstance(edge, dict) and edge.get("_origin") != EDGE_ORIGIN
    }
    retained = [
        edge
        for edge in links
        if not isinstance(edge, dict) or edge.get("_origin") != EDGE_ORIGIN
    ]
    generated: list[dict[str, object]] = []
    scanned = 0
    cited_paths: set[str] = set()
    for source, candidates in source_nodes.items():
        if Path(source).suffix.lower() not in DOCUMENT_SUFFIXES:
            continue
        document_path = project_path / source
        if not document_path.is_file():
            continue
        try:
            content = document_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        document_node = _select_document_node(candidates)
        if not document_node:
            continue
        for match in PATH_PATTERN.finditer(content):
            cited = _normalize_relative(match.group(1).strip("`'\"()[]{}<>.,:;"))
            resolved = cited
            target = code_targets.get(resolved)
            if not target:
                resolved = posixpath.normpath(
                    (Path(source).parent / cited).as_posix()
                )
                target = code_targets.get(resolved)
            if not target:
                continue
            cited_paths.add(resolved)
            key = (str(document_node["id"]), str(target["id"]), "references")
            if key in existing:
                continue
            existing.add(key)
            generated.append(
                {
                    "source": document_node["id"],
                    "target": target["id"],
                    "relation": "references",
                    "context": "explicit project-relative source path",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": source,
                    "source_location": None,
                    "weight": 1.0,
                    "_origin": EDGE_ORIGIN,
                }
            )

    updated_links = retained + generated
    changed = updated_links != links
    result.update(
        {
            "document_files_scanned": scanned,
            "explicit_source_paths_found": len(cited_paths),
            "document_source_edges": len(generated),
            "changed": changed,
            "ready": bool(generated),
        }
    )
    if changed and not dry_run:
        payload["links" if "links" in payload else "edges"] = updated_links
        temporary = graph_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(graph_path)
    return result


def _select_file_node(
    candidates: list[dict[str, object]], source: str
) -> dict[str, object] | None:
    basename = Path(source).name.lower()
    ranked = sorted(
        candidates,
        key=lambda node: (
            str(node.get("file_type") or "") != "code",
            str(node.get("source_location") or "") not in {"L1", "1"},
            str(node.get("label") or "").lower() != basename,
            len(str(node.get("id") or "")),
        ),
    )
    return ranked[0] if ranked else None


def _select_document_node(
    candidates: list[dict[str, object]],
) -> dict[str, object] | None:
    ranked = sorted(
        candidates,
        key=lambda node: (
            str(node.get("file_type") or "") != "document",
            str(node.get("source_location") or "") not in {"L1", "1"},
            len(str(node.get("id") or "")),
        ),
    )
    return ranked[0] if ranked else None


def _normalize_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")
