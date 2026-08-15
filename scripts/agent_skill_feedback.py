"""Best-effort adapters for successful-task skill learning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_global_lessons import state_home
from agent_gate_evidence import latest_successful_gate_fields
from agent_skill_catalog import (
    canonical_skill_ids,
    normalize_feedback_signal,
    normalize_skill_id,
    parse_skill_ids,
)
from agent_skill_draft import record_draft
from agent_skill_learning import (
    curate_observations,
    record_observation,
    review_candidate,
)
from agent_skill_maintenance import complete_verified_skill_maintenance
from agent_skill_retention import prune_skill_learning_state
from agent_skill_state import CURRENT_TASK_REVIEW_THRESHOLD, DEFAULT_REVIEW_THRESHOLD


def record_skill_feedback(
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
    outcome: str,
    skill_id: str,
    signal: str,
    gap_type: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Record an observation and immediately prepare same-closeout maintenance.

    The hook still does not write prose or mutate canonical skill guidance. It
    queues the current occurrence immediately so the observing run can author,
    verify, and record the bounded maintenance before finish.
    """

    normalized_outcome = outcome.strip().lower()
    if normalized_outcome == "no_change":
        return {"created": False, "reason": "no_change"}, [
            "skill observation check completed with no reusable signal"
        ]
    if normalized_outcome != "observed":
        return {"created": False, "reason": "invalid_observation_outcome"}, [
            "skill observation skipped: invalid outcome; task completion is unchanged"
        ]

    normalized_skill = normalize_skill_id(skill_id)
    if not normalized_skill or normalized_skill not in canonical_skill_ids(project, rules):
        return {"created": False, "reason": "unknown_canonical_skill"}, [
            "skill observation skipped: unknown canonical skill; task completion is unchanged"
        ]
    normalized_signal = normalize_feedback_signal(signal)
    if not normalized_signal:
        return {"created": False, "reason": "unknown_feedback_signal"}, [
            "skill observation skipped: signal is not schema-owned; task completion is unchanged"
        ]
    retrospective = _retrospective_fields(evidence_path)
    checked_skills = set(parse_skill_ids(retrospective.get("skills_checked", "")))
    if (
        retrospective.get("outcome", "").strip().lower() != "reusable_gap"
        or retrospective.get("observation", "").strip().lower() != "recorded"
        or normalized_skill not in checked_skills
    ):
        return {"created": False, "reason": "skill_not_checked_in_retrospective"}, [
            "skill observation skipped: skill was not bound to the current retrospective; "
            "task completion is unchanged"
        ]

    result = record_observation(
        state_home(),
        occurrence_id=_occurrence_id(evidence_path),
        skill_id=normalized_skill,
        signal=normalized_signal,
        gap_type=gap_type,
    )
    if result.get("idempotent"):
        details = [
            "successful-task skill observation replay was deduplicated",
            "task completion is unchanged",
        ]
    elif not result.get("created"):
        reason = str(result.get("reason") or "not_recorded")
        return result, [f"skill observation skipped: {reason}; task completion is unchanged"]
    else:
        details = [
            "successful-task skill observation recorded",
            f"observation status: {result.get('status', 'observed')}",
        ]

    curation, curation_details = record_skill_curation(
        min_occurrences=CURRENT_TASK_REVIEW_THRESHOLD
    )
    result["curation"] = curation
    details.extend(curation_details)
    candidate = str(result.get("candidate_id") or "")
    if candidate and candidate in set(curation.get("queued") or []):
        details.append(
            f"current skill candidate requires bounded review before finish: {candidate}"
        )
    return result, details


def record_skill_draft(
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
    skill_id: str,
    signal: str,
    proposal: str,
) -> tuple[dict[str, Any], list[str]]:
    """Store the observing run's patch proposal for a candidate.

    Kept separate from `record_skill_feedback` so the observation hook still
    only records facts. The draft is the run's reasoning, and it carries no
    authority to change canonical guidance.
    """

    try:
        result = record_draft(
            state_home(),
            project=project,
            rules=rules,
            skill_id=skill_id,
            signal=signal,
            proposal=proposal,
            occurrence_id=_occurrence_id(evidence_path),
        )
    except (OSError, ValueError) as error:
        result = {
            "created": False,
            "reason": "draft_failed",
            "error": error.__class__.__name__,
        }
    if result.get("idempotent"):
        return result, ["skill patch draft was unchanged; task completion is unchanged"]
    if not result.get("created"):
        reason = str(result.get("reason") or "not_recorded")
        return result, [f"skill patch draft skipped: {reason}; task completion is unchanged"]
    return result, [
        "skill patch draft recorded for same-closeout review"
        if not result.get("revised")
        else "skill patch draft revised for same-closeout review",
        "canonical skill guidance is edited only by the verified maintenance step",
    ]


def record_skill_curation(
    *, min_occurrences: int = DEFAULT_REVIEW_THRESHOLD
) -> tuple[dict[str, Any], list[str]]:
    try:
        result = curate_observations(
            state_home(), min_occurrences=min_occurrences
        )
        result["retention"] = prune_skill_learning_state(state_home())
    except (OSError, ValueError) as error:
        return {"updated": False, "reason": "curation_failed", "error": error.__class__.__name__}, [
            "skill curation skipped; completed tasks and runtime maintenance are unchanged"
        ]
    details = [
        f"skill observations scanned: {result['scanned']}",
        f"new review items queued: {result['ready_count']}",
        (
            "legacy observations mapped by exact compatibility table: "
            f"{result['legacy_mapped_count']}"
        ),
        (
            "unmapped legacy observations retained for diagnosis: "
            f"{result['legacy_unmapped_count']}"
        ),
    ]
    return result, details


def record_skill_review(
    *,
    candidate_id: str,
    decision: str,
    gap_type: str,
    change_type: str,
    promotion_target: str,
) -> tuple[dict[str, Any], list[str]]:
    try:
        result = review_candidate(
            state_home(),
            candidate_id=candidate_id,
            decision=decision,
            gap_type=gap_type,
            change_type=change_type,
            promotion_target=promotion_target,
            min_occurrences=CURRENT_TASK_REVIEW_THRESHOLD,
        )
    except (OSError, ValueError) as error:
        result = {"updated": False, "reason": "review_failed", "error": error.__class__.__name__}
    if not result.get("updated"):
        reason = str(result.get("reason") or "not_updated")
        return result, [f"bounded skill review skipped: {reason}; completed tasks are unchanged"]
    return result, [
        f"bounded skill review recorded: {result['status']}",
        "canonical skill guidance is edited only by the verified maintenance step",
    ]


def record_skill_maintenance(
    *,
    project: Path,
    rules: Path,
    candidate_id: str,
    outcome: str,
    verification_kind: str,
    target: str,
    test_selector: str,
    evidence_path: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        result = complete_verified_skill_maintenance(
            state_home(),
            project=project,
            rules=rules,
            candidate_id=candidate_id,
            outcome=outcome,
            verification_kind=verification_kind,
            target=target,
            test_selector=test_selector,
            preflight=_preflight_payload(evidence_path),
        )
    except (OSError, ValueError) as error:
        result = {"updated": False, "reason": "maintenance_failed", "error": error.__class__.__name__}
    if not result.get("updated"):
        reason = str(result.get("reason") or "not_updated")
        return result, [f"skill maintenance status skipped: {reason}"]
    return result, [f"skill maintenance completed: {result['status']}"]


def _preflight_payload(evidence_path: Path | None) -> dict[str, Any] | None:
    """Read preflight evidence for non-Git runtime maintenance proof."""

    if evidence_path is None:
        return None
    try:
        payload = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _occurrence_id(evidence_path: Path) -> str:
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("agent_run_id") or "")


def _retrospective_fields(evidence_path: Path) -> dict[str, str]:
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    route = payload.get("route") or {}
    if not isinstance(route, dict):
        return {}
    return latest_successful_gate_fields(
        route=route,
        evidence_path=evidence_path,
        gate="retrospective check",
    )
