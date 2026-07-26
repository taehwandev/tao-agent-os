"""Validated persistence primitives for content-free skill-learning state."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json


SCHEMA_VERSION = 1
SAFE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
CANDIDATE_ID_RE = re.compile(r"^[a-f0-9]{16}$")
DEFAULT_REVIEW_THRESHOLD = 2


def candidate_id(skill_id: str, signal: str) -> str:
    return opaque_key(json.dumps({"skill_id": skill_id, "signal": signal}, sort_keys=True))


def opaque_key(value: str) -> str:
    normalized = value.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""


def safe_slug(value: str) -> bool:
    return bool(SAFE_SLUG_RE.fullmatch(value.strip()))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def observation_dir() -> Path:
    return Path("skill-learning") / "observations"


def review_queue_path(candidate: str) -> Path:
    return Path("skill-learning") / "review-queue" / f"{candidate}.json"


def staged_path(candidate: str) -> Path:
    return Path("skill-learning") / "staged" / f"{candidate}.json"


def completed_path(candidate: str) -> Path:
    return Path("skill-learning") / "completed" / f"{candidate}.json"


def candidate_lock_path(candidate: str) -> Path:
    return Path("skill-learning") / "locks" / f"{candidate}.json"


def terminal_candidate_exists(root: Path, candidate: str) -> bool:
    return (root / staged_path(candidate)).exists() or (root / completed_path(candidate)).exists()


def valid_candidate_record(
    payload: dict[str, Any], candidate: str, *, expected_status: str
) -> bool:
    skill_id = str(payload.get("skill_id") or "")
    signal = str(payload.get("signal") or "")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("candidate_id") != candidate
        or payload.get("status") != expected_status
        or payload.get("privacy") != "safe_slugs_and_opaque_ids_only"
        or not safe_slug(skill_id)
        or not safe_slug(signal)
        or candidate_id(skill_id, signal) != candidate
    ):
        return False
    if expected_status == "review_ready":
        count = payload.get("distinct_occurrences")
        return isinstance(count, int) and count >= DEFAULT_REVIEW_THRESHOLD
    if expected_status == "staged_patch":
        return payload.get("review_decision") == "stage_patch" and all(
            safe_slug(str(payload.get(field) or ""))
            for field in ("gap_type", "change_type", "promotion_target")
        )
    return True


def skill_name_segment(target_relative: str) -> str:
    """Return the normalized <skill-name> segment of a "<...>/skills/<skill-name>/..." path.

    Used to bind a promotion_target to the exact skill directory a
    maintenance receipt touched, not merely to some segment of the path --
    a plain set-membership check let a generic promotion_target like
    "skills" or "workflows" match every skill file's path, since those
    words are literal directory segments shared by every skill under this
    layout.
    """

    parts = Path(target_relative).parts
    for index, part in enumerate(parts):
        if part.lower() in {"skills", "llm-skills"} and index + 1 < len(parts):
            return parts[index + 1].lower().replace("-", "_")
    return ""


def candidate_occurrence_count(root: Path, candidate: str) -> int:
    occurrences: set[str] = set()
    for path in (root / observation_dir()).glob("*.json"):
        payload = read_json(path)
        occurrence_key = str(payload.get("occurrence_key") or "")
        normalized = {**payload, "status": "review_ready", "distinct_occurrences": 2}
        if (
            payload.get("candidate_id") == candidate
            and payload.get("status") == "observed"
            and CANDIDATE_ID_RE.fullmatch(occurrence_key)
            and valid_candidate_record(normalized, candidate, expected_status="review_ready")
        ):
            occurrences.add(occurrence_key)
    return len(occurrences)


def valid_maintenance_receipt(
    receipt: dict[str, Any], candidate: str, verification_kind: str
) -> bool:
    target_sha256 = str(receipt.get("target_sha256") or "")
    return (
        safe_slug(verification_kind)
        and receipt.get("candidate_id") == candidate
        and receipt.get("status") == "SUCCESS"
        and receipt.get("returncode") == 0
        and receipt.get("target_scope") in {"rules", "project"}
        and receipt.get("verification_kind") == verification_kind
        and safe_slug(str(receipt.get("promotion_target") or ""))
        and bool(str(receipt.get("target_relative") or ""))
        and len(target_sha256) == 64
        and all(character in "0123456789abcdef" for character in target_sha256)
    )


def transition_record(source: Path, destination: Path, payload: dict[str, Any]) -> None:
    """Persist a new state, then atomically move it without split-brain files."""

    if destination.exists():
        raise ValueError("transition destination already exists")
    prior = read_json(source)
    atomic_write_json(source, payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.replace(destination)
    except OSError:
        atomic_write_json(source, prior)
        raise


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def json_count(path: Path) -> int:
    return sum(1 for item in path.glob("*.json") if item.is_file()) if path.exists() else 0
