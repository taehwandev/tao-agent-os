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
    candidate_gap_types,
    candidate_id,
    candidate_lock_path,
    completed_path,
    json_count,
    now,
    observation_candidate_ids,
    observation_dir,
    read_json,
    review_queue_path,
    safe_slug,
    staged_path,
    terminal_candidate_exists,
    transition_record,
    valid_candidate_record,
)
from agent_state_lock import state_lock


MAX_CURATED_GROUPS = 100
MAX_REVIEW_QUEUE = 100
# A candidate groups occurrences that share skill_id + signal, so its members can
# name different gaps. Carrying all of them keeps a later reviewer from guessing
# which one the representative observation happened to be; the cap keeps the
# record bounded.
MAX_QUEUED_GAP_TYPES = 4


def _observed_gap_type_set(observations: list[dict[str, Any]]) -> set[str]:
    """Return every distinct safe gap named across the candidate observations."""

    return {
        value
        for value in (str(item.get("gap_type") or "").strip() for item in observations)
        if value and safe_slug(value)
    }


def _bounded_gap_types(
    gap_types: set[str], *, priority: list[str] | None = None
) -> list[str]:
    """Bound a queue payload while retaining uncovered gaps before covered ones."""

    prioritized = list(
        dict.fromkeys(value for value in (priority or []) if value in gap_types)
    )
    ordered = prioritized + sorted(gap_types - set(prioritized))
    return ordered[:MAX_QUEUED_GAP_TYPES]


def _observed_gap_types(observations: list[dict[str, Any]]) -> list[str]:
    """Return the bounded safe gap slugs carried by a new review item."""

    return _bounded_gap_types(_observed_gap_type_set(observations))


def _latest_gap_types(observations: list[dict[str, Any]]) -> list[str]:
    """Return safe gaps from the newest occurrence so active follow-up can advance.

    New observations carry a candidate-local order because wall-clock timestamps
    may tie. Historical observations fall back to their existing timestamps.
    """

    orders = [
        value
        for item in observations
        for value in [item.get("candidate_order")]
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1
    ]
    if orders:
        latest_order = max(orders)
        latest = [
            item for item in observations if item.get("candidate_order") == latest_order
        ]
    else:
        latest_at = max(
            (str(item.get("created_at") or "") for item in observations), default=""
        )
        latest = [
            item
            for item in observations
            if str(item.get("created_at") or "") == latest_at
        ]
    return sorted(
        {
            value
            for item in latest
            for value in [str(item.get("gap_type") or "").strip()]
            if value and safe_slug(value)
        }
    )


def _valid_completed_candidate(payload: dict[str, Any], candidate: str) -> bool:
    status = str(payload.get("status") or "")
    return (
        status in {"no_change", "applied", "rejected"}
        and valid_candidate_record(payload, candidate, expected_status=status)
        and payload.get("next_action") == "none"
    )



def _covers_gaps(payload: dict[str, Any], gap_types: set[str]) -> bool:
    """Whether a completed record settles the gaps an observation names.

    Two terminal statuses settle them. `no_change` is a reviewer deciding the
    gap needs nothing; `applied` is the fix landing. `rejected` is neither: the
    review said `stage_patch` -- the gap should be fixed -- and maintenance did
    not apply it. Treating that as settled left an accepted gap unreachable
    forever and told the next closeout a review had already closed it.
    """

    if str(payload.get("status") or "") == "rejected":
        return False
    return gap_types.issubset(candidate_gap_types(payload))


def _terminal_reopen_path(
    root: Path,
    compatible_candidates: set[str],
    gap_types: set[str],
) -> tuple[Path | None, str]:
    """Return one safe completed record to reopen, or why state blocks queueing.

    The block is named rather than reported as a bare boolean. Curation reports
    only how many items it queued, so a declined group looked exactly like no
    observation at all -- and the way forward, naming the gap, appeared nowhere.
    """

    if any(
        (root / review_queue_path(candidate)).exists()
        or (root / staged_path(candidate)).exists()
        for candidate in compatible_candidates
    ):
        return None, "already_awaiting_review"
    completed = [
        (candidate, root / completed_path(candidate), read_json(root / completed_path(candidate)))
        for candidate in compatible_candidates
        if (root / completed_path(candidate)).exists()
    ]
    if any(
        not _valid_completed_candidate(payload, candidate)
        for candidate, _path, payload in completed
    ):
        return None, "unreadable_completed_record"
    if any(
        _covers_gaps(payload, gap_types) for _id, _path, payload in completed
    ):
        # An empty gap set is a subset of everything, so a recurrence that names
        # no gap lands here too. Declining is right -- it carries nothing the
        # closed review did not decide -- but the caller has to be told.
        return None, "closed_review_no_new_gap"
    # Multiple legacy aliases are ambiguous; one state may be reopened safely.
    if len(completed) == 1:
        return completed[0][1], ""
    return None, "ambiguous_completed_aliases" if completed else ""


def _queue_candidate(
    root: Path,
    candidate: str,
    payload: dict[str, Any],
    observed_gap_types: set[str],
    latest_gap_types: list[str],
    reopen_path: Path | None,
) -> bool:
    """Write a new queue state or atomically reopen one completed state."""

    queue_path = root / review_queue_path(candidate)
    try:
        with state_lock(root / candidate_lock_path(candidate)):
            if queue_path.exists() or (root / staged_path(candidate)).exists():
                return False
            if reopen_path is not None:
                if not reopen_path.exists():
                    return False
                current = read_json(reopen_path)
                if not _valid_completed_candidate(current, reopen_path.stem):
                    return False
                # The same question _terminal_reopen_path already answered, and
                # it is asked again here because this is where the write
                # happens. One definition answers both, or the two drift.
                if _covers_gaps(current, observed_gap_types):
                    return False
                covered_gap_types = candidate_gap_types(current)
                uncovered_gap_types = observed_gap_types - covered_gap_types
                if not uncovered_gap_types:
                    # A rejected record settles nothing, so every observed gap
                    # is still open even when the record already lists it.
                    uncovered_gap_types = set(observed_gap_types)
                latest_uncovered = [
                    gap_type
                    for gap_type in latest_gap_types
                    if gap_type in uncovered_gap_types
                ]
                payload = {
                    **payload,
                    "gap_types": _bounded_gap_types(
                        observed_gap_types,
                        priority=latest_uncovered
                        + sorted(uncovered_gap_types - set(latest_uncovered)),
                    ),
                }
                transition_record(reopen_path, queue_path, payload)
            elif terminal_candidate_exists(root, candidate):
                return False
            else:
                atomic_write_json(queue_path, payload)
    except (OSError, ValueError):
        return False
    return True


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
    not_queued: list[dict[str, str]] = []
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
        gap_type_set = _observed_gap_type_set(observations)
        latest_gap_types = _latest_gap_types(observations)
        gap_types = _bounded_gap_types(gap_type_set, priority=latest_gap_types)
        compatible_candidates = set().union(
            *(
                set(item.get("_compatible_candidate_ids") or ())
                for item in observations
            )
        )
        reopen_path, blocked = _terminal_reopen_path(
            root, compatible_candidates, gap_type_set
        )
        if blocked:
            not_queued.append({"candidate_id": candidate, "reason": blocked})
            continue
        if queue_count >= MAX_REVIEW_QUEUE:
            break
        representative = observations[0]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate,
            "skill_id": representative["skill_id"],
            "signal": representative["signal"],
            "gap_types": gap_types,
            "distinct_occurrences": len(occurrence_keys),
            "threshold": threshold,
            "first_observed_at": min(str(item.get("created_at") or "") for item in observations),
            "last_observed_at": max(str(item.get("created_at") or "") for item in observations),
            "queued_at": now(),
            "status": "review_ready",
            "next_action": "bounded_skill_review",
            "privacy": "safe_slugs_and_opaque_ids_only",
        }
        if not _queue_candidate(
            root,
            candidate,
            payload,
            gap_type_set,
            latest_gap_types,
            reopen_path,
        ):
            continue
        queued.append(candidate)
        queue_count += 1
    return {
        "scanned": sum(len(items) for items in groups.values()),
        "queued": queued,
        "not_queued": not_queued,
        "ready_count": len(queued),
        "eligible_count": eligible_count,
        "threshold": threshold,
        "legacy_mapping_version": LEGACY_FEEDBACK_SIGNAL_MAPPING_VERSION,
        "legacy_mapped_count": legacy_mapped_count,
        "legacy_unmapped_count": legacy_unmapped_count,
    }
