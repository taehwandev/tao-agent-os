"""Learn from blocks that stop work before finish, without enforcing anything.

Owner: the global lesson store's pre-finish learning boundary.
Allowed imports: the standard library, the lesson store writer and promotion,
and the user-store write guard. Callers import this lazily, on a block path.
Forbidden imports: the gates, the route, the run lifecycle -- recording must
never be able to change the verdict that triggered it.
Callers/tests: the Claude pre-tool gate, the start hook, resume reconciliation,
the lesson summary and the finish check; ``tests/test_agent_block_lessons.py``.
Verification: that module, then ``test_lesson_recurrence_notice``.

The store used to learn only from finish failures, so the blocks an agent hit
while working -- a denied edit, a refused start, a drift-refused resume -- were
never counted and could recur forever unseen. A block is recorded here as a
content-free candidate (enum slugs, counts, opaque keys, timestamps), rate
limited per session, and the recurring ones are surfaced at start and in the
retrospective guidance so they are fixed in the normal flow of work.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RATE_LIMIT_SECONDS = 10 * 60
RECURRING_WINDOW = timedelta(days=7)
STALE_AFTER = timedelta(days=14)
SURFACE_THRESHOLD = 3
SURFACE_LIMIT = 3
LESSON_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# reason code -> suggested next action. Both sides are fixed slugs, so nothing a
# caller passes can put request text, a command or a path into a record.
NEXT_ACTIONS: dict[str, dict[str, str]] = {
    "pretool_gate": {
        "workflow_entry_missing": "run_start_in_this_session_first",
        "ticketed_product_branch": "use_a_ticketed_branch",
        "publication_before_finish": "finish_before_publishing",
        "publication_after_finish_mismatch": "publish_only_the_finished_scope",
        "unreadable_command_effect": "use_one_literal_command",
        "file_sprawl_budget": "collapse_or_justify_new_files",
        "continuation_pre_mutation": "reconcile_continuation_before_edit",
        "worktree_isolation": "work_in_a_linked_worktree",
        "workflow_start_worktree": "start_in_a_linked_worktree",
        "read_only_run_mutation": "start_a_writable_route_first",
        # Not a block: the gate failed open on its own bug. Recorded so the
        # crash is repaired rather than silently repeated.
        "gate_internal_error": "report_gate_internal_error",
    },
    "agent_hook_start": {
        "start_arguments_invalid": "fix_all_start_arguments_in_one_call",
        "start_intent_slug_invalid": "use_a_short_intent_slug",
        "start_effect_approval_mismatch": "match_approved_effect_to_route",
        "start_session_unbound": "start_from_the_runtime_session",
        "start_continuity_invalid": "check_the_continue_from_run",
        "publication_already_finished": "continue_the_pending_publication",
        "task_affinity_conflict": "finish_or_transfer_the_active_task",
        "run_claim_conflict": "resume_or_cancel_the_claimed_run",
        "start_preflight_failed": "fix_the_preflight_fail_lines",
        "leaked_session_runs": "finish_or_cancel_runs_before_restarting",
    },
    "run_reconcile": {
        "resume_drift_refused": "reconcile_drift_then_resume",
    },
}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def block_lesson_id(source: str, reason_code: str) -> str:
    seed = {"failure_type": "prefinish_block", "source": source, "root_cause": reason_code}
    return _opaque(json.dumps(seed, sort_keys=True))


def block_candidate(source: str, reason_code: str, now: datetime | None = None) -> dict[str, Any]:
    created_at = _now(now).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "lesson_id": block_lesson_id(source, reason_code),
        "created_at": created_at,
        "source": source,
        "status": "candidate",
        "failure_type": "prefinish_block",
        "root_cause": reason_code,
        "block_signature": f"{source}/{reason_code}",
        "next_action": NEXT_ACTIONS[source][reason_code],
        "missed_gates": [],
        "policy_failure_count": 0,
        "promotion_status": "repair_required",
        "promotion_target": "shared_doc_or_hook_or_test",
        "privacy": "safe_slugs_only",
    }


def record_block(
    source: str,
    reason_code: str,
    *,
    session_id: str = "",
    run_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Count one block, at most once per session and window. Never raises.

    A run id, when the block belongs to one run, is the occurrence itself, so
    the existing repair-receipt promotion for that run also retires it.
    """

    try:
        if reason_code not in NEXT_ACTIONS.get(source, {}):
            return {"created": False, "reason": "unknown_block"}
        from support.global_state import global_state_dir, user_store_write_error

        if user_store_write_error():
            return {"created": False, "reason": "store_not_writable_here"}
        current = _now(now)
        if run_id:
            # The same key `promote_repaired_candidates` derives for that run.
            occurrence = run_id
        else:
            bucket = int(current.timestamp() // RATE_LIMIT_SECONDS)
            occurrence = f"{source}:{reason_code}:{session_id or 'no_session'}:{bucket}"
        root = global_state_dir()
        lesson_id = block_lesson_id(source, reason_code)
        if _opaque(occurrence) in _recorded_keys(root / "lessons" / "inbox" / f"{lesson_id}.json"):
            return {"created": False, "reason": "rate_limited"}
        from agent_lesson_store import upsert_retrospective_candidate

        return upsert_retrospective_candidate(
            root, block_candidate(source, reason_code, current), occurrence_id=occurrence
        )
    except Exception:  # noqa: BLE001 - learning must never change a verdict
        return {"created": False, "reason": "record_failed"}


def _recorded_keys(path: Path) -> list[str]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = record.get("occurrence_keys") if isinstance(record, dict) else None
    return keys if isinstance(keys, list) else []


def _seen_at(record: dict[str, Any]) -> datetime | None:
    raw = str(record.get("last_seen_at") or record.get("created_at") or "")
    try:
        seen = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)


def is_stale(record: dict[str, Any], now: datetime | None = None) -> bool:
    """Marked stale, or dated and unseen for the stale window."""

    if record.get("status") == "stale":
        return True
    seen = _seen_at(record)
    return seen is not None and _now(now) - seen > STALE_AFTER


def occurrences_in_window(record: dict[str, Any], now: datetime | None = None) -> int:
    """Occurrences on the last `RECURRING_WINDOW` days, never the lifetime count.

    A record written before day buckets existed proves at most one occurrence:
    its last sighting, when that falls inside the window.
    """

    current = _now(now)
    buckets = record.get("recent_occurrences")
    if isinstance(buckets, dict):
        first_day = (current - RECURRING_WINDOW + timedelta(days=1)).date().isoformat()
        last_day = current.date().isoformat()
        return sum(
            count for day, count in buckets.items()
            if isinstance(day, str) and len(day) == 10 and first_day <= day <= last_day
            and isinstance(count, int) and not isinstance(count, bool) and count > 0
        )
    seen = _seen_at(record)
    return int(seen is not None and current - seen <= RECURRING_WINDOW)


def recurring_signatures(
    records: list[dict[str, Any]], now: datetime | None = None, limit: int = SURFACE_LIMIT
) -> list[dict[str, Any]]:
    """Top open candidates at the threshold, counting only in-window occurrences."""

    current = _now(now)
    items = []
    for record in records:
        count = occurrences_in_window(record, current)
        seen = _seen_at(record)
        if (
            count < SURFACE_THRESHOLD or seen is None
            or record.get("status") != "candidate"
            or not LESSON_ID_RE.fullmatch(str(record.get("lesson_id") or ""))
        ):
            continue
        items.append((count, seen, {
            "lesson_id": str(record["lesson_id"]),
            "signature": _slug_signature(record),
            "occurrence_count": count,
            "next_action": _slug(str(record.get("next_action") or "repair_then_resume")),
        }))
    items.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item for _, _, item in items[:limit]]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_") or "unknown"


def _slug_signature(record: dict[str, Any]) -> str:
    source = _slug(str(record.get("source") or "agent_finish_check"))
    # A block names its reason in root_cause; a finish lesson in failure_type.
    field = "root_cause" if record.get("block_signature") else "failure_type"
    return f"{source}/{_slug(str(record.get(field) or ''))}"


def recurring_lines(items: list[dict[str, Any]]) -> list[str]:
    return [
        f"Recurring block: {item['signature']} x{item['occurrence_count']} (7d) "
        f"-> {item['next_action']} [lesson {item['lesson_id']}]"
        for item in items
    ]


def retrospective_guidance_line(global_lessons: dict[str, Any]) -> str:
    items = (global_lessons or {}).get("recurring") or []
    if not items:
        return ""
    named = "; ".join(
        f"{item['signature']} x{item['occurrence_count']} [{item['lesson_id']}]" for item in items
    )
    return (
        "    recurring blocks: if one is in scope, fix it as reusable_gap and add "
        f"fixed_lesson=<lesson id> to retire it on a clean finish: {named}"
    )


def resolve_fixed_lesson(gate_evidence_ledger: dict[str, Any] | None, preflight: dict[str, Any]) -> str:
    """Retire the lesson a clean finish's retrospective says it fixed. Never raises."""

    try:
        fields: dict[str, Any] = {}
        for entry in (gate_evidence_ledger or {}).get("entries") or []:
            if isinstance(entry, dict) and entry.get("gate") == "retrospective check":
                fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
        lesson_id = str(fields.get("fixed_lesson") or "").strip().lower()
        run_id = str(preflight.get("agent_run_id") or "")
        if not LESSON_ID_RE.fullmatch(lesson_id) or not run_id:
            return ""
        from support.global_state import global_state_dir, user_store_write_error

        if user_store_write_error():
            return ""
        from agent_lesson_store import promote_fixed_candidate

        promoted = promote_fixed_candidate(
            global_state_dir(), lesson_id, receipt_id=f"finish:{_opaque(run_id)}",
            promotion_status="retrospective_fix_verified",
        )
        return lesson_id if promoted else ""
    except Exception:  # noqa: BLE001 - closeout learning never fails a finish
        return ""
