"""Persistence and deduplication for content-free Tao Agent OS lessons."""

from __future__ import annotations

import hashlib
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

    Inbox records already carry forward any legacy promoted baseline, so
    prefer them. Read the promoted record only as backward-compatible history
    when no inbox record exists; there is no write path that promotes a new
    candidate from this module.
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
