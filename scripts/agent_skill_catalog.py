"""Canonical skill identifiers available to retrospective learning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from support.project_tree import PRUNED_RUN_STATE, iter_project_files


SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,80}$")
NO_SKILL_IDS = frozenset({"none", "none_loaded", "no_skill_used"})
PROJECT_SKILL_ROOTS = (
    Path(".agents/shared/llm-skills"),
    Path(".agents/local/skills"),
)
FEEDBACK_SIGNALS = frozenset(
    {
        "missing_rule",
        "unclear_ownership",
        "weak_verification",
        "stale_guidance",
        "missing_platform_guidance",
        "ambiguous_decision",
        "execution_error",
    }
)
LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION = 1
LEGACY_FEEDBACK_SIGNAL_MAP = {
    "claimed_visual_parity_without_source_diff": "weak_verification",
    "custom_evidence_binding": "missing_rule",
    "feature_inherits_toggle_reachability": "missing_rule",
    "focus_guard_disables_shortcuts": "missing_rule",
    "grill_me_evidence_prewrite_validation": "weak_verification",
    "live_runtime_identity_check": "weak_verification",
    "measure_metric_before_reporting_it": "weak_verification",
    "optional_evaluation_can_be_skipped": "missing_rule",
    "project_scope_container_dir": "unclear_ownership",
    "question_battery_rejected_on_fast_pivot": "ambiguous_decision",
    "stale_cache_path_ids": "stale_guidance",
    "transparent_label_still_occupies_layout": "missing_rule",
    "worker_self_reported_counts_unverified": "weak_verification",
}


def normalize_skill_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    return normalized if SKILL_ID_RE.fullmatch(normalized) else ""


def parse_skill_ids(value: str) -> list[str]:
    raw_items = [item.strip() for item in re.split(r"\s*,\s*", value) if item.strip()]
    return [normalize_skill_id(item) for item in raw_items]


def normalize_feedback_signal(
    value: str,
    *,
    legacy_mapping_version: int | None = None,
) -> str:
    normalized = value.strip()
    if normalized in FEEDBACK_SIGNALS:
        return normalized
    if legacy_mapping_version == LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION:
        return LEGACY_FEEDBACK_SIGNAL_MAP.get(normalized, "")
    return ""


def canonical_skill_ids(project: Path, rules: Path) -> set[str]:
    """Return IDs backed by canonical rule or project-local skill bundles."""

    ids = _skill_ids_under(rules.resolve())
    project_root = project.resolve()
    for relative in PROJECT_SKILL_ROOTS:
        ids.update(_skill_ids_under(project_root / relative))
    return ids


def _skill_ids_under(root: Path) -> set[str]:
    """Collect skill ids without walking one directory per recorded run.

    `.tao/runs` is state, but `.tao/skills` beside it is tracked content its
    own ignore file deliberately keeps, so only the run directories are
    pruned. In an integrated checkout they hold a second copy of the
    repository, which is why the walk found 320 skill documents to keep 159 --
    and why every id but one was being read twice.
    """

    if not root.is_dir():
        return set()
    ids: set[str] = set()
    for skill_doc in iter_project_files(root, "SKILL.md", pruned=PRUNED_RUN_STATE):
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
