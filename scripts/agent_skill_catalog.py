"""Canonical skill identifiers available to retrospective learning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,80}$")
NO_SKILL_IDS = frozenset({"none", "none_loaded", "no_skill_used"})
PROJECT_SKILL_ROOTS = (
    Path(".agents/shared/llm-skills"),
    Path(".agents/local/skills"),
)


def normalize_skill_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    return normalized if SKILL_ID_RE.fullmatch(normalized) else ""


def parse_skill_ids(value: str) -> list[str]:
    raw_items = [item.strip() for item in re.split(r"\s*,\s*", value) if item.strip()]
    return [normalize_skill_id(item) for item in raw_items]


def canonical_skill_ids(project: Path, rules: Path) -> set[str]:
    """Return IDs backed by canonical rule or project-local skill bundles."""

    ids = _skill_ids_under(rules.resolve())
    project_root = project.resolve()
    for relative in PROJECT_SKILL_ROOTS:
        ids.update(_skill_ids_under(project_root / relative))
    return ids


def _skill_ids_under(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    ids: set[str] = set()
    for skill_doc in root.rglob("SKILL.md"):
        skill_id = normalize_skill_id(skill_doc.parent.name)
        if skill_id and _has_skill_container(skill_doc, root):
            ids.add(skill_id)
    return ids


def _has_skill_container(skill_doc: Path, root: Path) -> bool:
    try:
        parts: Iterable[str] = skill_doc.relative_to(root).parts[:-2]
    except ValueError:
        return False
    return root.name in {"skills", "llm-skills"} or any(
        part in {"skills", "llm-skills"} for part in parts
    )
