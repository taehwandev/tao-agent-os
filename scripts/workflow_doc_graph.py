"""Public document graph expansion API for workflow routing and search."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from workflow_common import ROOT, unique
from workflow_doc_graph_build import build_doc_graph, clear_doc_graph_cache, graph_summary
from workflow_doc_graph_refs import frontmatter_required_doc_refs, normalize_doc_seed


def expand_doc_paths(
    root: Path,
    seed_docs: Iterable[str],
    *,
    max_depth: int = 1,
    max_docs: int = 24,
    relation_prefixes: tuple[str, ...] | None = None,
) -> list[str]:
    """Return seed docs followed by graph-related docs."""
    seeds = _seed_docs(root, seed_docs)
    matches = expand_doc_matches(
        root,
        seeds,
        max_depth=max_depth,
        max_docs=max_docs,
        relation_prefixes=relation_prefixes,
    )
    return unique([*seeds, *(str(match["path"]) for match in matches)])


def expand_doc_matches(
    root: Path,
    seed_docs: Iterable[str],
    *,
    max_depth: int = 1,
    max_docs: int = 24,
    relation_prefixes: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    """Return graph expansion matches for seed docs."""
    graph = build_doc_graph(root)
    seeds = _seed_docs(root, seed_docs)
    seen = set(seeds)
    queue: list[tuple[str, int]] = [(seed, 0) for seed in seeds]
    matches: list[dict[str, object]] = []

    while queue and len(matches) < max_docs:
        source, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for edge in sorted(graph.get(source, []), key=_edge_sort_key):
            relation = str(edge["relation"])
            if relation_prefixes and not relation.startswith(relation_prefixes):
                continue
            target = str(edge["target"])
            if target in seen:
                continue
            seen.add(target)
            matches.append(
                {
                    "path": target,
                    "source": source,
                    "depth": depth + 1,
                    "relation": relation,
                    "reason": str(edge.get("reason") or ""),
                    "weight": int(edge.get("weight") or 0),
                }
            )
            queue.append((target, depth + 1))
            if len(matches) >= max_docs:
                break
    return matches


def graph_required_docs(matches: Iterable[dict[str, object]]) -> list[str]:
    """Return docs connected by explicit required-doc relations."""
    return unique(
        str(match["path"])
        for match in matches
        if str(match.get("relation") or "").startswith("frontmatter:requires")
    )


def expand_required_doc_matches(
    root: Path,
    seed_docs: Iterable[str],
    *,
    max_depth: int = 4,
    max_docs: int = 24,
) -> list[dict[str, object]]:
    """Follow explicit ``requires_docs`` frontmatter from selected sources.

    Unlike ``expand_doc_matches``, this reads only selected documents and their
    declared dependencies. It does not build or traverse the corpus graph.
    """

    seeds = _seed_docs(root, seed_docs)
    seen = set(seeds)
    queue: list[tuple[str, int]] = [(seed, 0) for seed in seeds]
    matches: list[dict[str, object]] = []
    while queue and len(matches) < max_docs:
        source, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            text = (root / source).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for target in frontmatter_required_doc_refs(root, source, text):
            if target in seen:
                continue
            seen.add(target)
            matches.append(
                {
                    "path": target,
                    "source": source,
                    "depth": depth + 1,
                    "relation": "frontmatter:requires",
                    "reason": "Explicit required-document frontmatter",
                    "weight": 80,
                }
            )
            queue.append((target, depth + 1))
            if len(matches) >= max_docs:
                break
    return matches


def _seed_docs(root: Path, seed_docs: Iterable[str]) -> list[str]:
    seeds: list[str] = []
    for doc in seed_docs:
        seed = normalize_doc_seed(root, doc)
        if seed:
            seeds.append(seed)
    return unique(seeds)


def _edge_sort_key(edge: dict[str, object]) -> tuple[int, str, str]:
    return (-int(edge.get("weight") or 0), str(edge.get("relation") or ""), str(edge.get("target") or ""))


__all__ = [
    "ROOT",
    "build_doc_graph",
    "clear_doc_graph_cache",
    "expand_doc_matches",
    "expand_doc_paths",
    "expand_required_doc_matches",
    "graph_required_docs",
    "graph_summary",
]
