"""Persistence and deduplication for content-free Tao Agent OS lessons."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_continuation_outbound import assert_no_continuation_outbound
from agent_execution_capsule_state import atomic_write_json
from agent_lesson_files import (
    existing_candidates,
    remove_duplicate_candidates,
    update_index as _update_index,
)
from agent_state_lock import state_lock


OCCURRENCE_KEY_HISTORY_LIMIT = 20


def promote_repaired_candidates(
    root: Path,
    *,
    occurrence_id: str,
    receipt_id: str,
) -> dict[str, Any]:
    """Move this run's lesson candidates to `promoted` after a verified repair.

    Only the inbox was ever written, so `accepted=0 promoted=0` was structural
    rather than neglect, and a signature could recur 89 times while the counter
    only grew. A candidate records the opaque occurrence key of every run that
    produced it, and a repair receipt is bound to one run's preflight, so the
    two join exactly: promote the candidates carrying this run's key and leave
    every unrelated historical candidate alone.

    `occurrence_keys` is preserved on the promoted record because
    `existing_candidates` reads promoted records for the occurrence baseline --
    a signature that returns after a repair must keep counting, not restart.
    """

    occurrence_key = _opaque_occurrence_key(occurrence_id)
    if not occurrence_key or not receipt_id.strip():
        return {"promoted": [], "reason": "missing_repair_binding"}
    inbox = root / "lessons" / "inbox"
    if not inbox.is_dir():
        return {"promoted": [], "reason": "no_candidates"}

    promoted: list[str] = []
    for path in sorted(inbox.glob("*.json")):
        lesson = _read_lesson(path)
        lesson_id = str(lesson.get("lesson_id") or "")
        if not lesson_id:
            continue
        keys = lesson.get("occurrence_keys")
        if not isinstance(keys, list) or occurrence_key not in keys:
            continue
        if _promote_one(root, path, lesson, receipt_id=receipt_id.strip()):
            promoted.append(lesson_id)
    return {"promoted": promoted}


def _promote_one(
    root: Path,
    inbox_path: Path,
    lesson: dict[str, Any],
    *,
    receipt_id: str,
) -> bool:
    relative_path = Path("lessons") / "promoted" / f"{lesson['lesson_id']}.json"
    destination = root / relative_path
    payload = {
        **lesson,
        "status": "promoted",
        "promotion_status": "repair_verified",
        "repair_receipt_id": receipt_id,
    }
    try:
        assert_no_continuation_outbound(payload, boundary="global_lesson")
        with state_lock(destination):
            atomic_write_json(destination, payload)
            _update_index(root, relative_path, payload)
        inbox_path.unlink(missing_ok=True)
    except (OSError, ValueError):
        return False
    return True


def _read_lesson(path: Path) -> dict[str, Any]:
    try:
        lesson = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return lesson if isinstance(lesson, dict) else {}


def upsert_retrospective_candidate(
    root: Path,
    lesson: dict[str, Any],
    *,
    occurrence_id: str = "",
) -> dict[str, Any]:
    relative_path = Path("lessons") / "inbox" / f"{lesson['lesson_id']}.json"
    path = root / relative_path
    try:
        assert_no_continuation_outbound(lesson, boundary="global_lesson")
        with state_lock(path):
            inbox_prior, promoted_prior, duplicate_paths = existing_candidates(
                root, lesson["lesson_id"]
            )
            prior = _occurrence_baseline(inbox_prior, promoted_prior)
            prior_keys = _merged_occurrence_keys(prior)
            occurrence_key = _opaque_occurrence_key(occurrence_id)
            if occurrence_key:
                repeated_occurrence = occurrence_key in prior_keys
            else:
                # Without a verifiable occurrence id (e.g. the run registry
                # was unavailable) we cannot prove this write is a new,
                # distinct occurrence rather than a re-run of one already
                # counted. Treat it as non-incrementing once a first record
                # exists, instead of inflating the count on every call --
                # under-counting only delays recurrence visibility, while
                # over-counting invents failures that never happened.
                repeated_occurrence = bool(prior)
            occurrence_count = sum(
                max(1, int(item.get("occurrence_count", 1))) for item in prior
            )
            if not repeated_occurrence:
                occurrence_count += 1
            first_seen_at = min(
                [
                    str(
                        item.get("first_seen_at")
                        or item.get("created_at")
                        or lesson["created_at"]
                    )
                    for item in prior
                ]
                or [lesson["created_at"]]
            )
            lesson.update(
                {
                    "first_seen_at": first_seen_at,
                    "last_seen_at": lesson["created_at"],
                    "occurrence_count": occurrence_count,
                    "occurrence_keys": _merged_occurrence_keys(prior, occurrence_key),
                    "promotion_status": lesson["promotion_status"],
                }
            )
            atomic_write_json(path, lesson)
            remove_duplicate_candidates(path, duplicate_paths)
            _update_index(root, relative_path, lesson)
    except (OSError, ValueError) as error:
        return {
            "created": False,
            "reason": "write_failed",
            "error": error.__class__.__name__,
        }
    return {
        "created": True,
        "status": lesson["promotion_status"],
        "lesson_id": lesson["lesson_id"],
        "relative_path": str(relative_path),
        "occurrence_count": lesson["occurrence_count"],
        "idempotent": repeated_occurrence,
    }


def _occurrence_baseline(
    inbox_records: list[dict[str, Any]], promoted_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pick the occurrence-count source for this write.

    Inbox records already carry forward any promoted baseline, so prefer them.
    Read the promoted record when no inbox record exists: that is both legacy
    history and the state left by `promote_repaired_candidates`, which removes
    the inbox record. A signature that returns after a verified repair therefore
    resumes counting from the promoted baseline instead of restarting at one.
    """
    return inbox_records if inbox_records else promoted_records


def _merged_occurrence_keys(prior: list[dict[str, Any]], new_key: str = "") -> list[str]:
    """Carry forward occurrence keys in append order, capped by recency.

    The previous version stored these in a ``set`` and capped with
    ``sorted(...)[-20:]``, which evicts by hash value rather than recency:
    once more than 20 distinct occurrences existed, an arbitrary (not
    necessarily the oldest) key could be evicted, and a legitimately
    repeated occurrence_id could then be miscounted as new. Deduping via
    dict.fromkeys preserves each key's first-seen position instead.
    """

    keys = list(
        dict.fromkeys(
            str(key)
            for item in prior
            for key in item.get("occurrence_keys", [])
            if isinstance(key, str) and key
        )
    )
    if new_key and new_key not in keys:
        keys.append(new_key)
    return keys[-OCCURRENCE_KEY_HISTORY_LIMIT:]


def _opaque_occurrence_key(occurrence_id: str) -> str:
    value = occurrence_id.strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""
