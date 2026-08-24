"""Local cross-agent lesson storage for missed workflow gates."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_lesson_store import promote_repaired_candidates, upsert_retrospective_candidate
from agent_skill_retention import skill_learning_summary
from support.global_state import STATE_HOME_ENV, global_state_dir
from workflow_common import (
    REPAIR_CYCLE_LIMIT,
    REPAIR_POLICY,
    REPAIR_STOP_CONDITION,
    RESUME_SCOPE,
)
from support.stage_timing import stage

SCHEMA_VERSION = 1
SAFE_SLUG_RE = re.compile(r"[^a-z0-9_]+")
LESSON_STATUSES = ("accepted", "promoted")

# A bare `candidates=37` reads as bookkeeping, so a signature that had already
# recurred 89 times stayed invisible while agents reported a clean finish. At or
# above this many occurrences the summary names the signature instead of only
# counting it.
RECURRENCE_NOTICE_THRESHOLD = 3


def state_home() -> Path:
    # Single definition, shared with the gates' global-vs-project discriminator
    # so the two can never disagree about which directory is the global install.
    return global_state_dir()


def lesson_summary(limit: int = 10) -> dict[str, Any]:
    with stage("lesson_summary"):
        return _lesson_summary(limit)


def _lesson_summary(limit: int) -> dict[str, Any]:
    root = state_home()
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state_home": "env" if os.environ.get(STATE_HOME_ENV) else "default",
        "available": root.exists(),
        "accepted": [],
        "promoted": [],
        **_inbox_summary(root / "lessons" / "inbox"),
        "skill_learning": skill_learning_summary(root),
    }
    for status in LESSON_STATUSES:
        summary[status] = _read_lessons(root / "lessons" / status, limit)
    return summary


def write_retrospective_candidate(finish_result: dict[str, Any]) -> dict[str, Any]:
    if not finish_result.get("retrospective_required"):
        return {"created": False, "reason": "retrospective_not_required"}

    return upsert_retrospective_candidate(
        state_home(),
        retrospective_candidate(finish_result),
        occurrence_id=str(finish_result.get("occurrence_id") or ""),
    )


def promote_lessons_for_repair(occurrence_id: str, receipt_id: str) -> dict[str, Any]:
    """Promote this run's lesson candidates once a repair receipt verifies."""

    return promote_repaired_candidates(
        state_home(), occurrence_id=occurrence_id, receipt_id=receipt_id
    )


def retrospective_candidate(finish_result: dict[str, Any]) -> dict[str, Any]:
    missed_gates = [_slug(gate) for gate in finish_result.get("missed_gates", []) if gate]
    policy_failures = _policy_failure_count(finish_result)
    failure_type = _failure_type(missed_gates, policy_failures)
    root_cause = _root_cause(missed_gates, policy_failures)
    created_at = datetime.now(timezone.utc).isoformat()
    seed = {
        "failure_type": failure_type,
        "missed_gates": missed_gates,
        "policy_failure_count": policy_failures,
        "root_cause": root_cause,
        "next_action": "repair_verify_then_resume_failed_checkpoint",
    }
    lesson_id = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": SCHEMA_VERSION,
        "lesson_id": lesson_id,
        "created_at": created_at,
        "created_at_compact": created_at.replace(":", "").replace("-", "").split(".")[0].replace("T", "-"),
        "source": "agent_finish_check",
        "status": "candidate",
        "failure_type": failure_type,
        "missed_gates": missed_gates,
        "policy_failure_count": policy_failures,
        "root_cause": root_cause,
        "next_action": "repair_verify_then_resume_failed_checkpoint",
        "required_retrospective_output": "immediate_correction_plan",
        "repair_rule": "improve_tao_doc_hook_validator_or_test_before_resume",
        "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
        "repair_policy": REPAIR_POLICY,
        "resume_rule": f"resume_{RESUME_SCOPE}_after_verified_improvement",
        "stop_rule": REPAIR_STOP_CONDITION,
        "durable_fix_rule": "apply_safe_scoped_fix_immediately_else_stop_for_owner",
        "promotion_target": "shared_doc_or_hook_or_test",
        "promotion_status": "repair_required",
        "privacy": "safe_slugs_only",
    }


def _policy_failure_count(finish_result: dict[str, Any]) -> int:
    return sum(
        1
        for signal in finish_result.get("gate_signals", [])
        if signal.get("gate") == "gate evidence policy" and signal.get("signal") == "FAIL"
    )


def _failure_type(missed_gates: list[str], policy_failures: int) -> str:
    if missed_gates and policy_failures:
        return "missed_gate_and_policy_failure"
    if missed_gates:
        return "missed_required_gate"
    if policy_failures:
        return "gate_evidence_policy_failure"
    return "finish_gate_failure"


def _root_cause(missed_gates: list[str], policy_failures: int) -> str:
    if missed_gates:
        return "missing_required_gate_evidence"
    if policy_failures:
        return "weak_gate_evidence"
    return "finish_failed_before_completion"


def _slug(value: str) -> str:
    normalized = SAFE_SLUG_RE.sub("_", value.strip().lower().replace("-", "_")).strip("_")
    return normalized or "unknown"


def _read_lessons(path: Path, limit: int) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    if not path.exists():
        return lessons
    for lesson_path in sorted(path.glob("*.json"), reverse=True)[:limit]:
        try:
            lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lessons.append(
            {
                "lesson_id": lesson.get("lesson_id", ""),
                "failure_type": lesson.get("failure_type", ""),
                "root_cause": lesson.get("root_cause", ""),
                "next_action": lesson.get("next_action", ""),
                "promotion_status": lesson.get("promotion_status", ""),
            }
        )
    return lessons


def _inbox_summary(path: Path) -> dict[str, Any]:
    """Read the candidate inbox once, for both numbers a summary reports.

    Counting the candidates and finding the most-repeated one each used to walk
    and parse the whole inbox. On this machine that is 905 files and 3.5 MB,
    read twice on every preflight -- profiled at 51 ms with a warm filesystem
    cache and 206 ms without, and it grows with the store rather than with the
    work. One pass answers both.
    """

    lesson_ids: set[str] = set()
    best: dict[str, Any] = {}
    best_count = 0
    if path.exists():
        for lesson_path in sorted(path.glob("*.json")):
            try:
                lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(lesson, dict):
                continue
            lesson_id = str(lesson.get("lesson_id") or "")
            if lesson_id:
                lesson_ids.add(lesson_id)
            count = lesson.get("occurrence_count")
            if not isinstance(count, int) or isinstance(count, bool):
                continue
            if count > best_count:
                best, best_count = lesson, count
    return {
        "candidate_count": len(lesson_ids),
        "top_recurrence": _recurrence_notice(best, best_count),
    }


def _recurrence_notice(best: dict[str, Any], best_count: int) -> dict[str, Any]:
    """Name the most-repeated candidate so a count cannot stand in for a repair.

    Only safe slugs, an opaque lesson id and a number are returned; the lesson
    records themselves hold no request content.
    """

    if best_count < RECURRENCE_NOTICE_THRESHOLD:
        return {}
    return {
        "lesson_id": str(best.get("lesson_id") or ""),
        "failure_type": str(best.get("failure_type") or ""),
        "occurrence_count": best_count,
        "promotion_status": str(best.get("promotion_status") or ""),
    }
