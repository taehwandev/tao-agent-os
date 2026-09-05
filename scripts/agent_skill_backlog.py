"""Count the skill-learning work that is waiting, so a stalled queue is visible.

The retrospective gate is a skill-document mechanism, not a diary: an
observation is supposed to travel observation -> review queue -> staged patch ->
completed, and the last step is what strengthens a skill document. Nothing
reported where a candidate had stopped. `skill_followup_failures` blocks finish
only for a candidate observed in the *current* run and deliberately ignores
historical ones, so a queue can hold items for weeks while every run closes
green. On this install it held sixteen, the oldest for twenty-five days, and no
line anywhere named them.

This module answers one question -- how much is waiting and for how long -- and
answers it from counts, safe slugs and opaque candidate ids only, so it can be
printed by a hook that is forbidden to read task content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_skill_state import (
    CANDIDATE_ID_RE,
    observation_dir,
    read_json,
)


__all__ = ["skill_backlog_summary", "format_skill_backlog"]

# Reading every record to age it is what makes the queue legible, so the scan is
# bounded instead of unbounded: a backlog this size is already the problem being
# reported, and the exact count past the cap does not change what to do about it.
MAX_SCANNED = 200


def skill_backlog_summary(state_root: Path) -> dict[str, Any]:
    """Report what waits in each skill-learning state, oldest first.

    `observed` is the retained observation-file count, kept for compatibility.
    Curation and completion preserve this history, so it is not an uncurated
    count and must not contribute to `waiting`. Counting needs no content reads.
    The two actionable states are read, because "sixteen waiting" and "sixteen
    waiting, oldest twenty-five days" prompt different actions.
    """

    observed = _count_files(state_root / observation_dir())
    queued, queued_oldest = _scan_stage(state_root, "review-queue")
    staged, staged_oldest = _scan_stage(state_root, "staged")
    oldest = _older(queued_oldest, staged_oldest)
    return {
        "observed": observed,
        "queued": queued,
        "staged": staged,
        "waiting": queued + staged,
        "oldest_age_days": _age_days(oldest[0]) if oldest else None,
        "oldest_candidate": oldest[1] if oldest else "",
    }


def format_skill_backlog(summary: dict[str, Any]) -> str:
    """One line, and only when there is something to act on.

    An empty backlog is the normal state; printing "0 waiting" on every start
    would train the reader to skip the line that matters.
    """

    if not summary.get("waiting"):
        return ""
    line = (
        f"Skill learning backlog: {summary['queued']} awaiting review, "
        f"{summary['staged']} staged, {summary['observed']} observations retained"
    )
    age = summary.get("oldest_age_days")
    if age is not None:
        line += f"; oldest {age}d"
        candidate = summary.get("oldest_candidate")
        if candidate:
            line += f" (candidate {candidate})"
    return line + "; run skill-review to drain it"


def _scan_stage(state_root: Path, stage: str) -> tuple[int, tuple[datetime, str] | None]:
    """Age both stages by `queued_at`, which a staged record carries forward.

    A review that stages a patch writes `{**queued, ...}`, so `queued_at`
    survives the transition and `staged` has no timestamp of its own. Ageing
    from entry is also the number worth seeing: what matters is how long a gap
    has gone unaddressed, not how long ago someone last touched its record.
    """

    directory = state_root / "skill-learning" / stage
    count = 0
    oldest: tuple[datetime, str] | None = None
    for path in _iter_records(directory):
        count += 1
        payload = read_json(path)
        if not isinstance(payload, dict):
            continue
        when = _parse_timestamp(payload.get("queued_at"))
        if when is None:
            continue
        candidate = str(payload.get("candidate_id") or "")
        entry = (when, candidate if CANDIDATE_ID_RE.fullmatch(candidate) else "")
        if oldest is None or entry[0] < oldest[0]:
            oldest = entry
    return count, oldest


def _iter_records(directory: Path) -> list[Path]:
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return []
    return paths[:MAX_SCANNED]


def _count_files(directory: Path) -> int:
    try:
        return sum(1 for _ in directory.glob("*.json"))
    except OSError:
        return 0


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    # A record written without an offset would otherwise raise on subtraction
    # against an aware `now`, turning a report into a crash at start.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _older(
    left: tuple[datetime, str] | None, right: tuple[datetime, str] | None
) -> tuple[datetime, str] | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left[0] <= right[0] else right


def _age_days(when: datetime) -> int:
    return max(0, (datetime.now(timezone.utc) - when).days)
