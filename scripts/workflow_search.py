"""Natural-language document search for workflow.py.

Pinned Wikimap provides deterministic section retrieval. Tao Agent OS keeps
policy facets and its local document graph on top so explicit workflow rules
remain stronger than lexical ranking and Graphify remains project-structural.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from workflow_doc_graph import expand_doc_matches
from workflow_search_facets import facet_docs, query_terms
from workflow_wikimap import WIKIMAP_VERSION, search_wikimap
from support.stage_timing import stage


RAW_TERM_WEIGHT = 2
EXPANDED_TERM_WEIGHT = 1
GRAPH_RELATION_BOOST = 12
GRAPH_SEED_LIMIT = 12
POLICY_FACET_BASE_SCORE = 1_000
WIKIMAP_RANK_BASE_SCORE = 500


@dataclass(frozen=True)
class SearchOutcome:
    """Document results plus the backend state used to produce them."""

    results: List[Dict[str, object]]
    backend: str
    backend_version: str = ""
    fallback_reason: str = ""
    weak: bool = False
    partial: bool = False
    fused: bool = False


def _parse_index_descriptions(root: Path) -> Dict[str, str]:
    """Return path → one-line description extracted from index.md."""
    index_path = root / "index.md"
    if not index_path.exists():
        return {}
    lines = index_path.read_text(encoding="utf-8", errors="ignore").split("\n")

    # Join indented continuation lines onto the preceding bullet line.
    joined: List[str] = []
    for line in lines:
        if joined and not line.startswith("-") and line.startswith("  ") and line.strip():
            joined[-1] = joined[-1].rstrip() + " " + line.strip()
        else:
            joined.append(line)

    path_re = re.compile(r"`([^`]+\.md)`")
    descriptions: Dict[str, str] = {}
    for line in joined:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        paths = path_re.findall(stripped)
        if not paths:
            continue
        # Description = bullet content with all backtick-quoted items removed.
        desc = path_re.sub("", stripped.lstrip("-").strip()).strip().rstrip(":,").strip()
        for p in paths:
            descriptions.setdefault(p, desc)
    return descriptions


def search_docs(root: Path, query: str, max_results: int = 8) -> List[Dict[str, object]]:
    """Return docs ranked by natural-language relevance to *query*."""
    return search_docs_outcome(root, query, max_results=max_results).results


def search_docs_outcome(root: Path, query: str, max_results: int = 8) -> SearchOutcome:
    """Return ranked docs and the concrete retrieval backend state."""

    with stage("doc_search"):
        return _search_docs_outcome(root, query, max_results)


def _search_docs_outcome(root: Path, query: str, max_results: int = 8) -> SearchOutcome:
    raw_terms, expanded_terms, matched_facets, doc_boosts = query_terms(query)
    if not raw_terms and not expanded_terms and not doc_boosts:
        return SearchOutcome(
            results=[],
            backend="wikimap",
            backend_version=WIKIMAP_VERSION,
        )

    queries = [query]
    if expanded_terms:
        queries.append(" ".join(expanded_terms))
    wikimap = search_wikimap(root, queries, max(max_results * 2, GRAPH_SEED_LIMIT))
    if wikimap.available:
        results = _wikimap_results(
            root,
            wikimap.results,
            matched_facets,
            doc_boosts,
            max_results,
        )
        return SearchOutcome(
            results=results,
            backend="wikimap",
            backend_version=WIKIMAP_VERSION,
            weak=wikimap.weak,
            partial=wikimap.partial,
            fused=wikimap.fused,
        )

    results = _legacy_search_docs(
        root,
        raw_terms,
        expanded_terms,
        matched_facets,
        doc_boosts,
        max_results,
    )
    for item in results:
        item["search_backend"] = "legacy"
    return SearchOutcome(
        results=results,
        backend="legacy",
        fallback_reason=wikimap.error,
    )


def _legacy_search_docs(
    root: Path,
    raw_terms: Sequence[str],
    expanded_terms: Sequence[str],
    matched_facets: Sequence[str],
    doc_boosts: dict[str, int],
    max_results: int,
) -> List[Dict[str, object]]:
    """Preserve the previous in-process scorer as an offline recovery path."""

    descriptions = _parse_index_descriptions(root)
    documents: dict[str, Dict[str, object]] = {}
    results: List[Dict[str, object]] = []

    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(root))
        if rel.startswith("scripts/"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        title = ""
        headings: List[str] = []
        body_lines: List[str] = []
        in_frontmatter = False

        for i, line in enumerate(text.split("\n")):
            if i == 0 and line.strip() == "---":
                in_frontmatter = True
                continue
            if in_frontmatter:
                if line.strip() == "---":
                    in_frontmatter = False
                continue
            if line.startswith("# ") and not title:
                title = line[2:].strip()
            elif line.startswith("## ") or line.startswith("### "):
                headings.append(line.lstrip("#").strip())
            else:
                body_lines.append(line)

        index_desc = descriptions.get(rel, "")
        lower_desc = index_desc.lower()
        lower_title = title.lower()
        lower_headings = " ".join(headings).lower()
        lower_body = " ".join(body_lines)[:2000].lower()

        score = doc_boosts.get(rel, 0)
        score += _score_terms(raw_terms, RAW_TERM_WEIGHT, lower_desc, lower_title, lower_headings, lower_body)
        score += _score_terms(expanded_terms, EXPANDED_TERM_WEIGHT, lower_desc, lower_title, lower_headings, lower_body)

        documents[rel] = {
            "path": rel,
            "title": title,
            "description": index_desc,
            "score": score,
            "matched_facets": [facet for facet in matched_facets if rel in facet_docs(facet)],
        }
        if score > 0:
            results.append(documents[rel])

    _append_graph_expansions(root, descriptions, documents, results, doc_boosts, max_results)
    results.sort(key=lambda x: (-int(x["score"]), str(x["path"])))
    return results[:max_results]


def _wikimap_results(
    root: Path,
    matches: Sequence[dict[str, object]],
    matched_facets: Sequence[str],
    doc_boosts: dict[str, int],
    max_results: int,
) -> List[Dict[str, object]]:
    descriptions = _parse_index_descriptions(root)
    documents: dict[str, Dict[str, object]] = {}
    results: List[Dict[str, object]] = []

    for rank, match in enumerate(matches):
        rel = str(match.get("path") or "")
        item = _document_item(root, rel, descriptions, matched_facets)
        if not item:
            continue
        item.update(
            {
                "score": WIKIMAP_RANK_BASE_SCORE - rank,
                "search_backend": "wikimap",
                "line": int(match.get("line") or 0),
                "heading": str(match.get("heading") or ""),
                "matched_lines": list(match.get("matched") or []),
                "rank_sources": str(match.get("sources") or ""),
            }
        )
        documents[rel] = item
        results.append(item)

    for rel, boost in doc_boosts.items():
        item = documents.get(rel) or _document_item(root, rel, descriptions, matched_facets)
        if not item:
            continue
        item["score"] = max(int(item.get("score") or 0), POLICY_FACET_BASE_SCORE + boost)
        item["search_backend"] = "wikimap"
        if rel not in documents:
            documents[rel] = item
            results.append(item)

    _append_graph_expansions(root, descriptions, documents, results, doc_boosts, max_results)
    results.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return results[:max_results]


def _append_graph_expansions(
    root: Path,
    descriptions: dict[str, str],
    documents: dict[str, Dict[str, object]],
    results: List[Dict[str, object]],
    doc_boosts: dict[str, int],
    max_results: int,
) -> None:
    seed_candidates = list(doc_boosts) or [str(item["path"]) for item in results[:GRAPH_SEED_LIMIT]]
    seed_docs = _unique_strings(seed_candidates)
    if not seed_docs:
        return
    result_paths = {str(item["path"]) for item in results}
    # The graph walk that turns search hits into their neighbours.
    with stage("doc_graph_expand"):
        graph_matches = expand_doc_matches(
            root,
            seed_docs,
            max_depth=1,
            max_docs=max(max_results * 2, GRAPH_SEED_LIMIT),
        )
    for match in graph_matches:
        path = str(match["path"])
        item = documents.get(path) or _document_item(root, path, descriptions, ())
        if not item:
            continue
        depth = int(match.get("depth") or 1)
        item["score"] = int(item.get("score") or 0) + max(1, GRAPH_RELATION_BOOST - depth)
        reasons = item.setdefault("graph_reasons", [])
        if isinstance(reasons, list):
            reasons.append(f"{match['relation']} via {match['source']}")
        if path not in result_paths:
            results.append(item)
            result_paths.add(path)
            documents[path] = item


def _document_item(
    root: Path,
    rel: str,
    descriptions: dict[str, str],
    matched_facets: Sequence[str],
) -> Dict[str, object] | None:
    if not rel or rel.startswith("scripts/"):
        return None
    path = root / rel
    if not path.is_file() or path.suffix.lower() != ".md":
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return {
        "path": rel,
        "title": _first_title(text),
        "description": descriptions.get(rel, ""),
        "score": 0,
        "matched_facets": [facet for facet in matched_facets if rel in facet_docs(facet)],
    }


def _first_title(text: str) -> str:
    in_frontmatter = False
    for index, line in enumerate(text.splitlines()):
        if index == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
            continue
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _unique_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _score_terms(
    terms: Sequence[str],
    weight: int,
    lower_desc: str,
    lower_title: str,
    lower_headings: str,
    lower_body: str,
) -> int:
    score = 0
    for term in terms:
        if term in lower_desc:
            score += 4 * weight
        if term in lower_title:
            score += 3 * weight
        if term in lower_headings:
            score += 2 * weight
        if term in lower_body:
            score += weight
    return score


def print_query_results(query: str, results: List[Dict[str, object]]) -> None:
    print(f'# Tao Agent OS Document Query: "{query}"')
    print()
    if not results:
        print("No matching documents found.")
        print()
        print("Try broader terms or run `workflow.py list` to browse available concerns.")
        return
    backend = str(results[0].get("search_backend") or "")
    if backend:
        print(f"Backend: {backend}")
        print()
    print(f"Top {len(results)} result(s):")
    print()
    for item in results:
        label = item.get("description") or item.get("title") or item["path"]
        facets = item.get("matched_facets")
        suffix = ""
        if isinstance(facets, list) and facets:
            suffix = f" (matched facets: {', '.join(str(facet) for facet in facets)})"
        graph_reasons = item.get("graph_reasons")
        if isinstance(graph_reasons, list) and graph_reasons:
            suffix += f" (graph: {', '.join(str(reason) for reason in graph_reasons[:2])})"
        location = ""
        if item.get("line"):
            location = f":{item['line']}"
        heading = str(item.get("heading") or "")
        if heading:
            suffix += f" (section: {heading})"
        print(f"- `{item['path']}{location}` — {label}{suffix}")
    print()
    print("To get a structured route:")
    print(
        "  python3 <TAO_ROOT>/scripts/workflow.py route <command>"
        ' --request "<request>"'
    )


__all__ = ["SearchOutcome", "print_query_results", "search_docs", "search_docs_outcome"]
