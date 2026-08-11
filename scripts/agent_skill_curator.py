"""Deterministic, token-free curation of structured skill observations."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_skill_catalog import (
    LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION,
    normalize_feedback_signal,
)
from agent_skill_state import (
    DEFAULT_REVIEW_THRESHOLD,
    SCHEMA_VERSION,
    candidate_id,
    candidate_lock_path,
    json_count,
    now,
    observation_candidate_ids,
    observation_dir,
    read_json,
    review_queue_path,
    safe_slug,
    terminal_candidate_exists,
)
from agent_state_lock import state_lock


MAX_CURATED_GROUPS = 100
MAX_REVIEW_QUEUE = 100
# A candidate groups occurrences that share skill_id + signal, so its members can
# name different gaps. Carrying all of them keeps a later reviewer from guessing
# which one the representative observation happened to be; the cap keeps the
# record bounded.
MAX_QUEUED_GAP_TYPES = 4


def _observed_gap_types(observations: list[dict[str, Any]]) -> list[str]:
    """Return the distinct safe gap slugs named across this candidate's observations."""

    seen = {
        value
        for value in (str(item.get("gap_type") or "").strip() for item in observations)
        if value and safe_slug(value)
    }
    return sorted(seen)[:MAX_QUEUED_GAP_TYPES]


def curate_observations(
    root: Path,
    *,
    min_occurrences: int = DEFAULT_REVIEW_THRESHOLD,
) -> dict[str, Any]:
    with state_lock(root / "skill-learning" / "locks" / "curator.json"):
        return _curate_observations_locked(root, min_occurrences=min_occurrences)


def _curate_observations_locked(root: Path, *, min_occurrences: int) -> dict[str, Any]:
    threshold = max(1, int(min_occurrences))
    groups: dict[str, list[dict[str, Any]]] = {}
    legacy_mapped_count = 0
    legacy_unmapped_count = 0
    for path in sorted((root / observation_dir()).glob("*.json")):
        payload = read_json(path)
        skill_id = str(payload.get("skill_id") or "")
        raw_signal = str(payload.get("signal") or "")
        compatible_candidates = observation_candidate_ids(payload)
        if not compatible_candidates:
            continue
        signal = normalize_feedback_signal(
            raw_signal,
            legacy_mapping_version=LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION,
        )
        if not signal:
            legacy_unmapped_count += 1
            continue
        canonical_candidate = candidate_id(skill_id, signal)
        if signal != raw_signal:
            legacy_mapped_count += 1
        normalized_payload = {
            **payload,
            "candidate_id": canonical_candidate,
            "signal": signal,
            "_compatible_candidate_ids": compatible_candidates,
        }
        groups.setdefault(canonical_candidate, []).append(normalized_payload)

    queued: list[str] = []
    eligible_count = 0
    queue_count = json_count(root / "skill-learning" / "review-queue")
    ordered = sorted(
        groups,
        key=lambda candidate: max(str(item.get("created_at") or "") for item in groups[candidate]),
        reverse=True,
    )
    for candidate in ordered:
        observations = groups[candidate]
        occurrence_keys = sorted({str(item["occurrence_key"]) for item in observations})
        if len(occurrence_keys) < threshold:
            continue
        eligible_count += 1
        if eligible_count > MAX_CURATED_GROUPS:
            break
        queue_path = root / review_queue_path(candidate)
        compatible_candidates = set().union(
            *(
                set(item.get("_compatible_candidate_ids") or ())
                for item in observations
            )
        )
        if any(
            terminal_candidate_exists(root, compatible_candidate)
            for compatible_candidate in compatible_candidates
        ) or any(
            (root / review_queue_path(compatible_candidate)).exists()
            for compatible_candidate in compatible_candidates
        ):
            continue
        if queue_count >= MAX_REVIEW_QUEUE:
            break
        representative = observations[0]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate,
            "skill_id": representative["skill_id"],
            "signal": representative["signal"],
            "gap_types": _observed_gap_types(observations),
            "distinct_occurrences": len(occurrence_keys),
            "threshold": threshold,
            "first_observed_at": min(str(item.get("created_at") or "") for item in observations),
            "last_observed_at": max(str(item.get("created_at") or "") for item in observations),
            "queued_at": now(),
            "status": "review_ready",
            "next_action": "bounded_skill_review",
            "privacy": "safe_slugs_and_opaque_ids_only",
        }
        try:
            with state_lock(root / candidate_lock_path(candidate)):
                if not queue_path.exists() and not terminal_candidate_exists(root, candidate):
                    atomic_write_json(queue_path, payload)
                    queued.append(candidate)
                    queue_count += 1
        except (OSError, ValueError):
            continue
    return {
        "scanned": sum(len(items) for items in groups.values()),
        "queued": queued,
        "ready_count": len(queued),
        "eligible_count": eligible_count,
        "threshold": threshold,
        "legacy_mapping_version": LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION,
        "legacy_mapped_count": legacy_mapped_count,
        "legacy_unmapped_count": legacy_unmapped_count,
    }
