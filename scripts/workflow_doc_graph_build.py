"""Build the local Tao Agent OS document graph."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from support.project_tree import git_ignored, iter_project_files
from workflow_common import ROOT, unique
from workflow_doc_graph_refs import frontmatter_doc_refs, markdown_doc_refs
from workflow_doc_surface_rules import rule_docs, rule_list, string_list
from workflow_doc_surfaces import RULES_FILE, load_doc_surface_rules
from workflow_skill_paths import canonical_doc_path
from support.stage_timing import stage


def build_doc_graph(root: Path = ROOT) -> dict[str, list[dict[str, object]]]:
    """Return a path -> edge list graph for local Markdown guidance."""
    return _build_doc_graph(str(root.resolve()))


@lru_cache(maxsize=4)
def _build_doc_graph(root_text: str) -> dict[str, list[dict[str, object]]]:
    root = Path(root_text)
    with stage("doc_graph_build"):
        return _graph_for(root)


def _graph_for(root: Path) -> dict[str, list[dict[str, object]]]:
    graph: dict[str, list[dict[str, object]]] = {}
    docs = _markdown_docs(root)
    for rel in docs:
        graph.setdefault(rel, [])

    _add_markdown_edges(root, docs, graph)
    _add_legacy_alias_edges(docs, graph)
    _add_surface_rule_edges(root, graph)
    return graph


def clear_doc_graph_cache() -> None:
    """Clear graph cache for tests or long-lived processes after docs change."""
    _build_doc_graph.cache_clear()


def graph_summary(root: Path = ROOT) -> dict[str, int]:
    """Return a small graph size summary for diagnostics."""
    graph = build_doc_graph(root)
    edge_count = sum(len(edges) for edges in graph.values())
    return {
        "nodes": len(graph),
        "edges": edge_count,
        "surface_rules": _surface_rule_count(root),
    }


def _markdown_docs(root: Path) -> set[str]:
    """Collect the guidance documents: the tracked ones and the new ones.

    Excluding `.tao` after the walk still descended into it, and in an
    integrated checkout that is a second copy of the repository: 885 files
    found to keep 495. The graph is built inside workflow validation, which
    the review hook runs before it can report, so the walk is something a
    person waits for.

    Git-ignored files are dropped for a second reason. 140 of the 498
    documents this walk found were generated reports -- 6.09 MB of the 8.08 MB
    it read, contributing 5 of 3105 edges. The wikimap search already excludes
    them by name; the graph disagreeing with it was the defect. Ignored is the
    right test rather than untracked: a guidance document being written should
    route before it is committed.
    """

    docs = {
        path.relative_to(root).as_posix()
        for path in iter_project_files(root, "*.md")
    }
    return docs - git_ignored(root, docs)


def _add_markdown_edges(root: Path, docs: set[str], graph: dict[str, list[dict[str, object]]]) -> None:
    for rel in sorted(docs):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for target in markdown_doc_refs(root, rel, text, docs):
            _add_edge(graph, rel, target, "markdown:link", "Markdown document reference", 30)
        for relation, target in frontmatter_doc_refs(root, rel, text, docs):
            _add_edge(graph, rel, target, relation, "Frontmatter document relation", 80)


def _add_legacy_alias_edges(docs: set[str], graph: dict[str, list[dict[str, object]]]) -> None:
    for rel in sorted(docs):
        canonical = canonical_doc_path(rel)
        if canonical == rel or canonical not in docs:
            continue
        _add_edge(
            graph,
            rel,
            canonical,
            "legacy-alias:canonical-skill",
            "Legacy flat alias maps to canonical SKILL.md",
            90,
        )
        _add_edge(
            graph,
            canonical,
            rel,
            "legacy-alias:flat-path",
            "Canonical SKILL.md has a temporary legacy flat alias",
            20,
        )


def _add_surface_rule_edges(root: Path, graph: dict[str, list[dict[str, object]]]) -> None:
    rules = load_doc_surface_rules(root)
    for name, docs in _doc_sets(rules).items():
        _connect_group(graph, docs, f"surface:doc_set:{name}", f"Shared document set `{name}`", 45)
    for key, label, weight in (
        ("request_intents", "request_intent", 40),
        ("path_surfaces", "path_surface", 35),
    ):
        for rule in rule_list(rules, key):
            name = str(rule.get("name") or label)
            _connect_group(
                graph,
                rule_docs(rules, rule),
                f"surface:{label}:{name}",
                str(rule.get("reason") or f"Shared {label} rule `{name}`"),
                weight,
            )


def _connect_group(
    graph: dict[str, list[dict[str, object]]],
    docs: Iterable[str],
    relation: str,
    reason: str,
    weight: int,
) -> None:
    members = unique(doc for doc in docs if doc)
    for source in members:
        for target in members:
            if source != target:
                _add_edge(graph, source, target, relation, reason, weight)


def _add_edge(
    graph: dict[str, list[dict[str, object]]],
    source: str,
    target: str,
    relation: str,
    reason: str,
    weight: int,
) -> None:
    if not source or not target or source == target:
        return
    edges = graph.setdefault(source, [])
    for edge in edges:
        if edge["target"] == target and edge["relation"] == relation:
            return
    edges.append({"target": target, "relation": relation, "reason": reason, "weight": weight})


def _doc_sets(rules: dict[str, Any]) -> dict[str, list[str]]:
    raw = rules.get("doc_sets")
    if not isinstance(raw, dict):
        return {}
    return {str(name): string_list(value) for name, value in raw.items()}


def _surface_rule_count(root: Path) -> int:
    rules_path = root / RULES_FILE
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(rule_list(rules, "request_intents")) + len(rule_list(rules, "path_surfaces"))
