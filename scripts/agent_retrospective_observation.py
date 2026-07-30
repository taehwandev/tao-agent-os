"""Bind a recorded retrospective result to one real content-free observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_skill_catalog import normalize_feedback_signal, parse_skill_ids
from agent_skill_state import (
    SCHEMA_VERSION,
    candidate_id,
    observation_dir,
    opaque_key,
    read_json,
)


def recorded_observation_failures(
    *,
    preflight: dict[str, Any],
    fields: dict[str, str],
    state_root: Path,
) -> list[str]:
    """Reject a self-reported ``recorded`` state without its current observation."""

    if fields.get("outcome", "").strip().lower() != "reusable_gap":
        return []
    if fields.get("observation", "").strip().lower() != "recorded":
        return []

    occurrence_key = opaque_key(str(preflight.get("agent_run_id") or ""))
    checked_skills = set(parse_skill_ids(fields.get("skills_checked", "")))
    if not occurrence_key or not checked_skills:
        return [_missing_observation()]

    for path in (state_root / observation_dir()).glob("*.json"):
        payload = read_json(path)
        if _matches_current_observation(payload, occurrence_key, checked_skills):
            return []
    return [_missing_observation()]


def _matches_current_observation(
    payload: dict[str, Any],
    occurrence_key: str,
    checked_skills: set[str],
) -> bool:
    skill_id = str(payload.get("skill_id") or "")
    raw_signal = str(payload.get("signal") or "")
    signal = normalize_feedback_signal(raw_signal)
    candidate = candidate_id(skill_id, signal) if signal else ""
    observation = opaque_key(f"{candidate}:{occurrence_key}") if candidate else ""
    return (
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("status") == "observed"
        and payload.get("privacy") == "safe_slugs_and_opaque_ids_only"
        and payload.get("occurrence_key") == occurrence_key
        and skill_id in checked_skills
        and signal == raw_signal
        and payload.get("candidate_id") == candidate
        and payload.get("observation_id") == observation
    )


def _missing_observation() -> str:
    return (
        "retrospective check observation recorded requires a matching stored observation "
        "for the current occurrence and one checked skill"
    )
