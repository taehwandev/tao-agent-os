"""Validate guidance nodes and the frontmatter relations that connect documents.

A node is one small guidance file under an `<area>/nodes/` directory. Routes
start from nodes named by `workflow-doc-surfaces.json` and reach the rest
through the nodes' own `requires`, `refines` and `verified_by` frontmatter, so
a broken or circular relation silently changes what an agent is told to read.
These checks make those failures visible in workflow validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from support.project_tree import git_ignored
from workflow_doc_graph_refs import (
    INLINE_DOC_RE,
    PROMOTING_RELATIONS,
    VERIFICATION_RELATION,
    frontmatter_relation_raw_refs,
    resolve_doc_ref,
)


NODE_MAX_BODY_LINES = 120
NODE_TRIGGER_KEYS = ("use_when", "skip_when")
NODE_VERIFICATION_HEADING = "## Verification"
_CHECKED_RELATIONS = (*PROMOTING_RELATIONS, VERIFICATION_RELATION)


def is_node_doc(relative: str) -> bool:
    parts = Path(relative).parts
    return len(parts) >= 2 and parts[-2] == "nodes" and relative.endswith(".md")


def node_graph_failures(root: Path, docs: Iterable[str], entry_docs: Iterable[str]) -> list[str]:
    """Return node-contract, dangling-relation, orphan and cycle failures.

    ``docs`` is every guidance document under validation, relative to
    ``root``. ``entry_docs`` are documents a route can select directly; a node
    reached by none of them and by no other document is an orphan.
    """

    listed = set(docs)
    # Git-ignored copies (nested worktrees under .claude/worktrees, generated
    # output) are not guidance: their relative links resolve to the real
    # documents, so every node in a copy would read as an orphan.
    doc_set = listed - git_ignored(root, listed)
    texts = {doc: _read(root / doc) for doc in sorted(doc_set)}
    failures: list[str] = []
    promoting: dict[str, list[str]] = {}
    referenced: set[str] = set(entry_docs)

    for doc, text in texts.items():
        for relation, raw in frontmatter_relation_raw_refs(text):
            target = resolve_doc_ref(root, doc, raw, doc_set)
            if relation not in _CHECKED_RELATIONS:
                if target:
                    referenced.add(target)
                continue
            if not target:
                failures.append(f"{doc}: {relation.split(':', 1)[1]} target does not exist: {raw}")
                continue
            referenced.add(target)
            if relation in PROMOTING_RELATIONS:
                promoting.setdefault(doc, []).append(target)
        for raw in INLINE_DOC_RE.findall(text):
            target = resolve_doc_ref(root, doc, raw, doc_set)
            if target:
                referenced.add(target)
        for raw in re.findall(r"\]\(([^)\s]+?\.md)(?:#[^)]*)?\)", text):
            target = resolve_doc_ref(root, doc, raw, doc_set)
            if target:
                referenced.add(target)

    for doc, text in texts.items():
        if is_node_doc(doc):
            failures.extend(_node_contract_failures(root, doc, text, doc_set))
            if doc not in referenced:
                failures.append(f"{doc}: orphan node; no route rule or document reaches it")

    failures.extend(_cycle_failures(promoting))
    return failures


def _node_contract_failures(root: Path, doc: str, text: str, docs: set[str]) -> list[str]:
    failures: list[str] = []
    header, body = _split_frontmatter(text)
    for key in NODE_TRIGGER_KEYS:
        match = re.search(rf"^{key}:\s*(\S.*)$", header, re.M)
        if not match:
            failures.append(f"{doc}: node frontmatter needs a non-empty `{key}`")
    body_lines = len(body.splitlines())
    if body_lines > NODE_MAX_BODY_LINES:
        failures.append(
            f"{doc}: node body has {body_lines} lines; split it below {NODE_MAX_BODY_LINES}"
        )
    if not re.search(rf"^{re.escape(NODE_VERIFICATION_HEADING)}\s*$", body, re.M):
        failures.append(f"{doc}: node needs a `{NODE_VERIFICATION_HEADING}` section")
    for raw in INLINE_DOC_RE.findall(body):
        if "<" in raw or "*" in raw:
            continue
        if not resolve_doc_ref(root, doc, raw, docs):
            failures.append(f"{doc}: node references a missing document: {raw}")
    return failures


def _cycle_failures(edges: dict[str, list[str]]) -> list[str]:
    """Report each `requires`/`refines` cycle once, by its smallest member."""

    failures: list[str] = []
    reported: set[frozenset[str]] = set()
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in edges.get(node, []):
            if state.get(target) == 1:
                cycle = stack[stack.index(target):]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    start = cycle.index(min(cycle))
                    ordered = [*cycle[start:], *cycle[:start], min(cycle)]
                    failures.append("frontmatter dependency cycle: " + " -> ".join(ordered))
            elif target not in state:
                visit(target)
        stack.pop()
        state[node] = 2

    for node in sorted(edges):
        if node not in state:
            visit(node)
    return failures


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    return text[4:end], text[end + 4:].lstrip("\n")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
