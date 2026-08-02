"""Content-free skill state orchestration; no gate, shell/model, or writer imports."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_skill_catalog import normalize_feedback_signal
from agent_skill_curator import curate_observations
from agent_skill_state import (
    CANDIDATE_ID_RE,
    DEFAULT_REVIEW_THRESHOLD,
    SCHEMA_VERSION,
    candidate_id as _candidate_id,
    candidate_lock_path as _candidate_lock_path,
    occurrence_lock_path as _occurrence_lock_path,
    candidate_occurrence_count as _candidate_occurrence_count,
    completed_path as _completed_path,
    json_count as _json_count,
    now as _now,
    observation_dir as _observation_dir,
    opaque_key as _opaque_key,
    read_json as _read_json,
    review_queue_path as _review_queue_path,
    safe_slug as _safe_slug,
    staged_path as _staged_path,
    transition_record as _transition_record,
    valid_candidate_record as _valid_candidate_record,
)
from agent_state_lock import state_lock


MAX_STAGED = 100


def record_observation(
    root: Path,
    *,
    occurrence_id: str,
    skill_id: str,
    signal: str,
) -> dict[str, Any]:
    if not _safe_slug(skill_id):
        return {"created": False, "reason": "unsafe_observation_fields"}
    if normalize_feedback_signal(signal) != signal:
        return {"created": False, "reason": "unknown_feedback_signal"}
    occurrence_key = _opaque_key(occurrence_id)
    if not occurrence_key:
        return {"created": False, "reason": "missing_occurrence_id"}

    candidate_id = _candidate_id(skill_id, signal)
    observation_id = _opaque_key(f"{candidate_id}:{occurrence_key}")
    relative_path = _observation_dir() / f"{observation_id}.json"
    path = root / relative_path
    now = _now()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "candidate_id": candidate_id,
        "skill_id": skill_id,
        "signal": signal,
        "occurrence_key": occurrence_key,
        "status": "observed",
        "created_at": now,
        "privacy": "safe_slugs_and_opaque_ids_only",
    }
    try:
        # The occurrence, not the candidate, is the scope of the invariant: a
        # reusable gap may produce at most one observation per run. Locking per
        # candidate let two different skill/signal pairs from the same run each
        # pass their own existence check and store a second observation.
        with state_lock(root / _occurrence_lock_path(occurrence_key)):
            if path.exists():
                return {
                    "created": False,
                    "idempotent": True,
                    "observation_id": observation_id,
                    "candidate_id": candidate_id,
                    "status": "observed",
                    "relative_path": str(relative_path),
                }
            existing = _observation_for_occurrence(root, occurrence_key)
            if existing is not None:
                return {
                    "created": False,
                    "reason": "occurrence_already_observed",
                    "observation_id": str(existing.get("observation_id") or ""),
                    "candidate_id": str(existing.get("candidate_id") or ""),
                    "status": "observed",
                }
            atomic_write_json(path, payload)
    except (OSError, ValueError) as error:
        return {"created": False, "reason": "write_failed", "error": error.__class__.__name__}
    return {
        "created": True,
        "idempotent": False,
        "observation_id": observation_id,
        "candidate_id": candidate_id,
        "status": "observed",
        "relative_path": str(relative_path),
    }


def _observation_for_occurrence(root: Path, occurrence_key: str) -> dict[str, Any] | None:
    """Return the observation already stored for this run, if any.

    Scanning rather than indexing keeps records written before this invariant
    existed subject to it, and the observation store stays small because one
    run may now contribute at most one file.
    """

    directory = root / _observation_dir()
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.glob("*.json")):
        record = _read_json(candidate)
        if isinstance(record, dict) and record.get("occurrence_key") == occurrence_key:
            return record
    return None


def review_candidate(
    root: Path,
    candidate_id: str,
    *,
    decision: str,
    gap_type: str = "",
    change_type: str = "",
    promotion_target: str = "",
) -> dict[str, Any]:
    if not CANDIDATE_ID_RE.fullmatch(candidate_id):
        return {"updated": False, "reason": "invalid_candidate_id"}
    if decision not in {"no_change", "stage_patch"}:
        return {"updated": False, "reason": "invalid_review_decision"}
    queue_path = root / _review_queue_path(candidate_id)
    with state_lock(root / _candidate_lock_path(candidate_id)):
        queued = _read_json(queue_path)
        if not _valid_candidate_record(queued, candidate_id, expected_status="review_ready"):
            return {"updated": False, "reason": "candidate_not_found"}
        if _candidate_occurrence_count(root, candidate_id) < DEFAULT_REVIEW_THRESHOLD:
            return {"updated": False, "reason": "candidate_observations_missing"}
        if decision == "stage_patch" and not all(
            _safe_slug(value) for value in (gap_type, change_type, promotion_target)
        ):
            return {"updated": False, "reason": "unsafe_review_fields"}
        cap_lock = (
            state_lock(root / "skill-learning" / "locks" / "staged-cap.json")
            if decision == "stage_patch"
            else nullcontext()
        )
        with cap_lock:
            if (
                decision == "stage_patch"
                and _json_count(root / "skill-learning" / "staged") >= MAX_STAGED
            ):
                return {"updated": False, "reason": "staged_queue_full"}
            status = "no_change" if decision == "no_change" else "staged_patch"
            payload = {
                **queued,
                "status": status,
                "reviewed_at": _now(),
                "review_decision": decision,
            }
            if decision == "stage_patch":
                payload.update(
                    gap_type=gap_type,
                    change_type=change_type,
                    promotion_target=promotion_target,
                    next_action="separate_verified_skill_maintenance",
                )
                destination = root / _staged_path(candidate_id)
            else:
                payload["next_action"] = "none"
                destination = root / _completed_path(candidate_id)
            try:
                _transition_record(queue_path, destination, payload)
            except (OSError, ValueError) as error:
                return {"updated": False, "reason": "write_failed", "error": error.__class__.__name__}
    return {"updated": True, "candidate_id": candidate_id, "status": status}
