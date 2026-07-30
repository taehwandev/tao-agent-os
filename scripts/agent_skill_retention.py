"""Bounded retention and summaries for passive skill-learning state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_skill_state import observation_candidate_ids
from agent_state_lock import state_lock


DEFAULT_REVIEW_THRESHOLD = 2
MAX_OBSERVATIONS = 500
MAX_COMPLETED = 200


def skill_learning_summary(root: Path) -> dict[str, int]:
    return {
        "observations": _json_count(root / "skill-learning" / "observations"),
        "review_ready": _json_count(root / "skill-learning" / "review-queue"),
        "staged": _json_count(root / "skill-learning" / "staged"),
        "completed": _json_count(root / "skill-learning" / "completed"),
    }


def prune_skill_learning_state(
    root: Path,
    *,
    max_observations: int = MAX_OBSERVATIONS,
    max_completed: int = MAX_COMPLETED,
) -> dict[str, int]:
    """Strictly bound passive history and prevent terminal resurrection."""

    with state_lock(root / "skill-learning" / "locks" / "curator.json"):
        return _prune_skill_learning_state_locked(
            root,
            max_observations=max_observations,
            max_completed=max_completed,
        )


def _prune_skill_learning_state_locked(
    root: Path,
    *,
    max_observations: int,
    max_completed: int,
) -> dict[str, int]:

    observation_limit = max(DEFAULT_REVIEW_THRESHOLD, int(max_observations))
    completed_limit = max(1, int(max_completed))
    completed_paths = _records_newest_first(root / "skill-learning" / "completed")
    expired_completed = completed_paths[completed_limit:]
    expired_candidate_ids = {path.stem for path in expired_completed}
    removed_completed = _remove_paths(expired_completed)

    observation_paths = _records_newest_first(root / "skill-learning" / "observations")
    expired_observations = {
        path
        for path in observation_paths
        if observation_candidate_ids(_read_json(path)) & expired_candidate_ids
    }
    available = [path for path in observation_paths if path not in expired_observations]
    keep = set(available[:observation_limit])
    removed_observations = _remove_paths(
        [path for path in observation_paths if path not in keep]
    )
    _drop_unreviewable_queue_records(root, keep)
    return {
        "removed_observations": removed_observations,
        "removed_completed": removed_completed,
        "kept_observations": len(keep),
        "kept_completed": min(len(completed_paths), completed_limit),
    }


def _drop_unreviewable_queue_records(root: Path, kept_observations: set[Path]) -> None:
    counts: dict[str, int] = {}
    for path in kept_observations:
        for candidate_id in observation_candidate_ids(_read_json(path)):
            counts[candidate_id] = counts.get(candidate_id, 0) + 1
    for queue_path in (root / "skill-learning" / "review-queue").glob("*.json"):
        if counts.get(queue_path.stem, 0) < DEFAULT_REVIEW_THRESHOLD:
            try:
                queue_path.unlink()
            except FileNotFoundError:
                pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_count(path: Path) -> int:
    return sum(1 for item in path.glob("*.json") if item.is_file()) if path.exists() else 0


def _records_newest_first(path: Path) -> list[Path]:
    records: list[tuple[int, str, Path]] = []
    if not path.exists():
        return []
    for item in path.glob("*.json"):
        try:
            stat = item.stat()
        except OSError:
            continue
        if item.is_file():
            records.append((stat.st_mtime_ns, item.name, item))
    return [item for _mtime, _name, item in sorted(records, reverse=True)]


def _remove_paths(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        else:
            removed += 1
    return removed
