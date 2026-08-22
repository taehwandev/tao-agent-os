"""Build the local Tao Agent OS document graph."""

from __future__ import annotations

import hashlib
import json
import os
import sys
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


CACHE_GENERATIONS = 3


def build_doc_graph(root: Path = ROOT) -> dict[str, list[dict[str, object]]]:
    """Return a path -> edge list graph for local Markdown guidance."""
    return _build_doc_graph(str(root.resolve()))


@lru_cache(maxsize=4)
def _build_doc_graph(root_text: str) -> dict[str, list[dict[str, object]]]:
    root = Path(root_text)
    with stage("doc_graph_build"):
        docs = _markdown_docs(root)
        key = _document_key(root, docs)
        cached = _read_cached_graph(root, key)
        if cached is not None:
            return cached
        graph = _graph_for(root, docs)
        _write_cached_graph(root, key, graph)
        return graph


def _graph_for(root: Path, docs: set[str]) -> dict[str, list[dict[str, object]]]:
    graph: dict[str, list[dict[str, object]]] = {}
    for rel in docs:
        graph.setdefault(rel, [])

    _add_markdown_edges(root, docs, graph)
    _add_legacy_alias_edges(docs, graph)
    _add_surface_rule_edges(root, graph)
    return graph


def _document_key(root: Path, docs: set[str]) -> str:
    """Digest every input the graph is built from, and nothing else.

    Keyed on the inputs rather than on the worktree, because a worktree
    signature changes with every source edit -- and between a start and the
    review that follows it, an agent has edited source. A key that tracks the
    inputs is a key that can hit.

    The inputs are the guidance documents *and* the surface rules file, which
    contributes the `doc_set`, request-intent and path-surface edges. Leaving
    it out was a stale hit: changing only the rules file changed the graph and
    not the key.

    Size and modification time rather than content: reading the 2 MB the build
    reads is the cost the cache exists to avoid.
    """

    digest = hashlib.sha256()
    digest.update(_builder_digest().encode("ascii"))
    for rel in [*sorted(docs), RULES_FILE]:
        path = root / rel
        try:
            # Follow the link: the build reads through it, so the key must
            # measure what the build reads. Two tracked documents in this
            # repository are symlinks into a pruned directory, whose targets
            # a walk never visits -- with `lstat` here, editing one of those
            # targets changed the graph and not the key.
            stat = path.stat()
            # Where it points is part of the input too, in case a retarget
            # lands on a file with the same size and time. Read inside the
            # same guard: a link can vanish between the two calls, and this
            # function may never be the reason a build fails.
            link = os.readlink(path) if path.is_symlink() else ""
        except FileNotFoundError:
            # A project may have no surface rules, and a document may be a
            # broken link the build skips. Both are states the graph depends
            # on, and neither is a reason to stop caching.
            digest.update(rel.encode("utf-8", "surrogateescape"))
            digest.update(b"\0absent\0")
            continue
        except OSError:
            return ""
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode("ascii"))
        if link:
            digest.update(b"\0link\0")
            digest.update(link.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


# The modules whose code decides what edges exist. A graph built by an older
# one must not be served after they change, and a version constant is a thing
# to forget: their own source is the version. A new builder module belongs in
# this list.
BUILDER_MODULES = (
    "workflow_doc_graph_build",
    "workflow_doc_graph_refs",
    "workflow_doc_surface_rules",
    "workflow_doc_surfaces",
    "workflow_skill_paths",
)


@lru_cache(maxsize=1)
def _builder_digest() -> str:
    """Digest the code that produces the graph, so a change to it invalidates.

    Content rather than modification time: a checkout that rewrites these
    files without changing them should not throw the cache away.
    """

    digest = hashlib.sha256()
    for name in BUILDER_MODULES:
        module = sys.modules.get(name)
        source = getattr(module, "__file__", None)
        if not source:
            return "unversioned"
        try:
            digest.update(Path(source).read_bytes())
        except OSError:
            return "unversioned"
    return digest.hexdigest()


def _cache_directory(root: Path) -> Path | None:
    """The run-state cache, only where run state already exists.

    `.tao` carries its own ignore file, so writing under it stays out of the
    repository. A project that has never run a hook has no `.tao`, and creating
    one here could put a 750 KB file into someone's next commit.
    """

    state = root / ".tao"
    return state / "cache" / "doc-graph" if state.is_dir() else None


def _read_cached_graph(root: Path, key: str) -> dict[str, list[dict[str, object]]] | None:
    directory = _cache_directory(root)
    if not key or directory is None:
        return None
    try:
        payload = json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_cached_graph(root: Path, key: str, graph: dict[str, list[dict[str, object]]]) -> None:
    """Store this generation, and keep the cache from growing without bound."""

    directory = _cache_directory(root)
    if not key or directory is None:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{key}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(graph, sort_keys=True), encoding="utf-8")
        temporary.replace(directory / f"{key}.json")
        _prune_cache(directory)
    except OSError:
        # A cache that cannot be written is a build, not a failure.
        return


def _prune_cache(directory: Path) -> None:
    generations = sorted(
        directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for stale in generations[CACHE_GENERATIONS:]:
        try:
            stale.unlink()
        except OSError:
            continue


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
