"""Parse document references for the local Tao Agent OS graph."""

from __future__ import annotations

import re
from pathlib import Path

from workflow_common import unique


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+?\.md)(?:#[^)]+)?\)")
INLINE_DOC_RE = re.compile(r"`([^`]+?\.md)`")
FRONTMATTER_KEYS = {
    "requires": "frontmatter:requires",
    "required_docs": "frontmatter:requires",
    "requires_docs": "frontmatter:requires",
    "related_docs": "frontmatter:related",
    "see_also": "frontmatter:related",
    "references": "frontmatter:reference",
}
REQUIRED_FRONTMATTER_KEYS = {"requires", "required_docs", "requires_docs"}


def markdown_doc_refs(root: Path, source: str, text: str, docs: set[str]) -> list[str]:
    refs: list[str] = []
    for pattern in (MARKDOWN_LINK_RE, INLINE_DOC_RE):
        for raw in pattern.findall(text):
            target = resolve_doc_ref(root, source, raw, docs)
            if target:
                refs.append(target)
    return unique(refs)


def frontmatter_doc_refs(root: Path, source: str, text: str, docs: set[str]) -> list[tuple[str, str]]:
    frontmatter = _frontmatter_block(text)
    if not frontmatter:
        return []
    refs: list[tuple[str, str]] = []
    current_relation = ""
    for line in frontmatter.splitlines():
        key_match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if key_match:
            current_relation = FRONTMATTER_KEYS.get(key_match.group(1), "")
            if current_relation:
                refs.extend(
                    (current_relation, target)
                    for target in _doc_refs_from_value(root, source, key_match.group(2), docs)
                )
            continue
        if current_relation and line.strip().startswith("-"):
            refs.extend(
                (current_relation, target)
                for target in _doc_refs_from_value(root, source, line, docs)
            )
    return refs


def frontmatter_required_doc_refs(root: Path, source: str, text: str) -> list[str]:
    """Resolve only explicit required-document frontmatter from one source.

    Route selection needs this small dependency set, not the Markdown-link and
    surface-neighbor graph for the whole documentation corpus.
    """

    frontmatter = _frontmatter_block(text)
    if not frontmatter:
        return []
    refs: list[str] = []
    current_required = False
    for line in frontmatter.splitlines():
        key_match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if key_match:
            current_required = key_match.group(1) in REQUIRED_FRONTMATTER_KEYS
            if current_required:
                refs.extend(
                    _existing_doc_refs_from_value(
                        root, source, key_match.group(2)
                    )
                )
            continue
        if current_required and line.strip().startswith("-"):
            refs.extend(_existing_doc_refs_from_value(root, source, line))
    return unique(refs)


def normalize_doc_seed(root: Path, doc: str) -> str:
    value = str(doc).strip().strip("'\"`")
    if not value:
        return ""
    resolved_root = root.resolve()
    if value.startswith(str(resolved_root) + "/"):
        return Path(value).resolve().relative_to(resolved_root).as_posix()
    return value


def resolve_doc_ref(root: Path, source: str, raw: str, docs: set[str]) -> str:
    target = raw.split("#", 1)[0].split("?", 1)[0].strip().strip("'\"`")
    if not target or "://" in target:
        return ""
    if target.startswith("/"):
        try:
            target_path = Path(target).resolve().relative_to(root)
        except ValueError:
            return ""
    elif not target.startswith(("./", "../")) and (root / target).exists():
        target_path = Path(target)
    else:
        target_path = (Path(source).parent / target).as_posix()
    normalized = _collapse_path(target_path)
    return normalized if normalized in docs else ""


def _frontmatter_block(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[4:end]


def _doc_refs_from_value(root: Path, source: str, value: str, docs: set[str]) -> list[str]:
    refs: list[str] = []
    for raw in re.findall(r"['\"]?([^'\"\[\],\s]+?\.md)['\"]?", value):
        target = resolve_doc_ref(root, source, raw, docs)
        if target:
            refs.append(target)
    return unique(refs)


def _existing_doc_refs_from_value(root: Path, source: str, value: str) -> list[str]:
    refs: list[str] = []
    for raw in re.findall(r"['\"]?([^'\"\[\],\s]+?\.md)['\"]?", value):
        target = _resolve_existing_doc_ref(root, source, raw)
        if target:
            refs.append(target)
    return unique(refs)


def _resolve_existing_doc_ref(root: Path, source: str, raw: str) -> str:
    target = raw.split("#", 1)[0].split("?", 1)[0].strip().strip("'\"`")
    if not target or "://" in target:
        return ""
    resolved_root = root.resolve()
    if target.startswith("/"):
        candidate = Path(target).resolve()
    elif target.startswith(("./", "../")):
        candidate = (resolved_root / Path(source).parent / target).resolve()
    else:
        rooted = (resolved_root / target).resolve()
        candidate = rooted if rooted.is_file() else (
            resolved_root / Path(source).parent / target
        ).resolve()
    if not candidate.is_relative_to(resolved_root) or candidate.suffix != ".md":
        return ""
    if not candidate.is_file():
        return ""
    return candidate.relative_to(resolved_root).as_posix()


def _collapse_path(path: str | Path) -> str:
    normalized = Path(path).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)
