"""Content-free follow-up checks for the current skill-learning occurrence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_retrospective_observation import recorded_observation_failures
from agent_skill_catalog import normalize_feedback_signal
from agent_skill_state import (
    CANDIDATE_ID_RE,
    CURRENT_TASK_REVIEW_THRESHOLD,
    SCHEMA_VERSION,
    candidate_gap_types,
    candidate_id,
    candidate_occurrence_count,
    completed_path,
    observation_dir,
    opaque_key,
    read_json,
    review_queue_path,
    safe_slug,
    staged_path,
    valid_candidate_record,
)


__all__ = ["skill_followup_failures"]


def skill_followup_failures(
    *,
    state_root: Path,
    preflight: dict[str, Any],
    gate_evidence_ledger: dict[str, Any] | None = None,
) -> list[str]:
    """Report unfinished learning triggered by the current opaque occurrence.

    Historical candidates are deliberately ignored. Returned diagnostics contain
    only fixed labels and opaque candidate identities.
    """

    occurrence_key = opaque_key(str(preflight.get("agent_run_id") or ""))
    if not occurrence_key:
        return ["skill follow-up occurrence unavailable"]

    failures: set[str] = set()
    failures.update(
        recorded_observation_failures(
            preflight=preflight,
            fields=_retrospective_fields(gate_evidence_ledger),
            state_root=state_root,
        )
    )
    candidates: dict[str, set[str]] = {}
    for path in (state_root / observation_dir()).glob("*.json"):
        payload = read_json(path)
        if payload.get("occurrence_key") != occurrence_key:
            continue
        candidate = str(payload.get("candidate_id") or "")
        if not _valid_current_observation(payload, occurrence_key):
            suffix = f": candidate={candidate}" if CANDIDATE_ID_RE.fullmatch(candidate) else ""
            failures.add(f"skill follow-up current observation invalid{suffix}")
            continue
        gap_type = str(payload.get("gap_type") or "").strip()
        candidates.setdefault(candidate, set())
        if gap_type:
            candidates[candidate].add(gap_type)

    for candidate in sorted(candidates):
        if candidate_occurrence_count(state_root, candidate) < CURRENT_TASK_REVIEW_THRESHOLD:
            continue
        failures.update(
            _candidate_failures(state_root, candidate, candidates[candidate])
        )
    return sorted(failures)


def _retrospective_fields(gate_evidence_ledger: dict[str, Any] | None) -> dict[str, Any]:
    """Read the retrospective fields the agent actually recorded.

    This used to read `preflight["route"]["gate_ledger"]`, which is the route
    snapshot frozen at `start`: its entries carry `gate`, `status`, `signal` and
    `evidence`, and never a `fields` key at all. Across 99 recorded runs not one
    carried fields, so the lookup returned `{}` every time and the observation
    check below could never see a `reusable_gap` to verify. The recorded fields
    live in the gate evidence ledger, which is the file `gate` and `gate-batch`
    write and the finish check has already read and validated by this point.

    The last matching entry wins: re-recording a gate is how a correction is
    made, and the correction is what the finish is judging.
    """

    entries = (gate_evidence_ledger or {}).get("entries")
    if not isinstance(entries, list):
        return {}
    fields: dict[str, Any] = {}
    for item in entries:
        if not isinstance(item, dict) or item.get("gate") != "retrospective check":
            continue
        recorded = item.get("fields")
        if isinstance(recorded, dict):
            fields = recorded
    return fields


def _valid_current_observation(payload: dict[str, Any], occurrence_key: str) -> bool:
    skill_id = str(payload.get("skill_id") or "")
    signal = str(payload.get("signal") or "")
    candidate = candidate_id(skill_id, signal) if safe_slug(skill_id) else ""
    observation = opaque_key(f"{candidate}:{occurrence_key}") if candidate else ""
    return (
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("status") == "observed"
        and payload.get("privacy") == "safe_slugs_and_opaque_ids_only"
        and payload.get("occurrence_key") == occurrence_key
        and normalize_feedback_signal(signal) == signal
        and payload.get("candidate_id") == candidate
        and payload.get("observation_id") == observation
        and (
            not str(payload.get("gap_type") or "").strip()
            or safe_slug(str(payload.get("gap_type") or "").strip())
        )
    )


def _candidate_failures(
    state_root: Path,
    candidate: str,
    required_gap_types: set[str],
) -> set[str]:
    records = {
        "bounded review": state_root / review_queue_path(candidate),
        "verified maintenance": state_root / staged_path(candidate),
        "completed": state_root / completed_path(candidate),
    }
    existing = {state: path for state, path in records.items() if path.exists()}
    if len(existing) > 1:
        return {f"skill follow-up state invalid: candidate={candidate}"}
    if not existing:
        return {f"skill follow-up curation pending: candidate={candidate}"}

    state, path = next(iter(existing.items()))
    payload = read_json(path)
    if state == "bounded review":
        if valid_candidate_record(payload, candidate, expected_status="review_ready"):
            if not required_gap_types.issubset(candidate_gap_types(payload)):
                return {f"skill follow-up curation pending: candidate={candidate}"}
            return {f"skill follow-up bounded review pending: candidate={candidate}"}
    elif state == "verified maintenance":
        if valid_candidate_record(payload, candidate, expected_status="staged_patch"):
            return {f"skill follow-up verified maintenance pending: candidate={candidate}"}
    elif _valid_completed_record(payload, candidate):
        if required_gap_types.issubset(candidate_gap_types(payload)):
            return set()
        return {f"skill follow-up curation pending: candidate={candidate}"}
    return {f"skill follow-up state invalid: candidate={candidate}"}


def _valid_completed_record(payload: dict[str, Any], candidate: str) -> bool:
    status = str(payload.get("status") or "")
    if status not in {"no_change", "applied", "rejected"}:
        return False
    if not valid_candidate_record(payload, candidate, expected_status=status):
        return False
    if payload.get("next_action") != "none":
        return False
    if status == "no_change":
        return payload.get("review_decision") == "no_change"
    return (
        payload.get("review_decision") == "stage_patch"
        and payload.get("maintenance_outcome") == status
        and safe_slug(str(payload.get("gap_type") or ""))
        and safe_slug(str(payload.get("change_type") or ""))
        and safe_slug(str(payload.get("promotion_target") or ""))
        and safe_slug(str(payload.get("verification_kind") or ""))
    )
