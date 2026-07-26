"""Objective verification boundary for staged canonical skill maintenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_state import sha256_file
from agent_state_lock import state_lock
from agent_verification_command import (
    run_verification_command,
    resolve_verification_target,
    verification_command,
    verification_target_is_changed,
)
from agent_skill_state import (
    CANDIDATE_ID_RE,
    candidate_lock_path as _candidate_lock_path,
    completed_path as _completed_path,
    now as _now,
    read_json as _read_json,
    skill_name_segment as _skill_name_segment,
    staged_path as _staged_path,
    transition_record as _transition_record,
    valid_candidate_record as _valid_candidate_record,
    valid_maintenance_receipt as _valid_maintenance_receipt,
)


__all__ = ["complete_verified_skill_maintenance"]


def complete_verified_skill_maintenance(
    root: Path,
    *,
    project: Path,
    rules: Path,
    candidate_id: str,
    outcome: str,
    verification_kind: str = "",
    target: str = "",
    test_selector: str = "",
) -> dict[str, Any]:
    """Reject directly, or apply only after a changed target passes a fixed check."""

    if not CANDIDATE_ID_RE.fullmatch(candidate_id):
        return {"updated": False, "reason": "invalid_candidate_id"}
    if outcome == "rejected":
        return _reject_staged_maintenance(root, candidate_id)
    if outcome != "applied":
        return {"updated": False, "reason": "invalid_maintenance_outcome"}

    staged, staged_error = _load_staged_candidate(root, candidate_id)
    if staged_error:
        return {"updated": False, "reason": staged_error}
    promotion_target = str(staged.get("promotion_target") or "")
    resolved = resolve_verification_target(project, rules, target)
    if resolved is None:
        return {"updated": False, "reason": "maintenance_target_not_found"}
    target_path, target_scope, target_relative, target_root = resolved
    if not _target_scope_is_allowed(
        project=project,
        target_path=target_path,
        target_scope=target_scope,
        target_relative=target_relative,
        promotion_target=promotion_target,
    ):
        return {"updated": False, "reason": "maintenance_target_mismatch"}
    if not verification_target_is_changed(target_root, target_path):
        return {"updated": False, "reason": "maintenance_target_not_changed"}
    command = verification_command(
        project=project,
        rules=rules,
        target=target_path,
        verification_kind=verification_kind,
        test_selector=test_selector,
    )
    if not command:
        return {"updated": False, "reason": "invalid_verification_contract"}
    target_sha256 = _target_sha256(target_path)
    if not target_sha256:
        return {"updated": False, "reason": "maintenance_target_not_found"}
    result = run_verification_command(
        command,
        target_root,
    )
    returncode = int(result.get("returncode", 1))
    if returncode != 0:
        return {"updated": False, "reason": "maintenance_verification_failed"}
    if _target_sha256(target_path) != target_sha256:
        return {"updated": False, "reason": "maintenance_target_changed_during_verification"}
    receipt = {
        "candidate_id": candidate_id,
        "promotion_target": promotion_target,
        "target_scope": target_scope,
        "target_relative": target_relative,
        "target_sha256": target_sha256,
        "verification_kind": verification_kind,
        "returncode": returncode,
        "status": "SUCCESS",
    }
    if not _valid_maintenance_receipt(receipt, candidate_id, verification_kind):
        return {"updated": False, "reason": "internal_maintenance_receipt_invalid"}
    staged_path = root / _staged_path(candidate_id)
    with state_lock(root / _candidate_lock_path(candidate_id)):
        staged, staged_error = _load_staged_candidate(root, candidate_id)
        if staged_error:
            return {"updated": False, "reason": staged_error}
        if (
            staged.get("promotion_target") != promotion_target
            or not _target_matches_promotion(target_relative, promotion_target)
        ):
            return {"updated": False, "reason": "maintenance_target_mismatch"}
        if _target_sha256(target_path) != target_sha256:
            return {"updated": False, "reason": "maintenance_target_changed_after_verification"}
        payload = {
            **staged,
            "status": "applied",
            "maintenance_outcome": "applied",
            "completed_at": _now(),
            "verification_kind": verification_kind,
            "next_action": "none",
        }
        try:
            _transition_record(staged_path, root / _completed_path(candidate_id), payload)
        except (OSError, ValueError) as error:
            return {"updated": False, "reason": "write_failed", "error": error.__class__.__name__}
    return {
        "updated": True,
        "candidate_id": candidate_id,
        "status": "applied",
        "verification_kind": verification_kind,
    }


def _load_staged_candidate(root: Path, candidate_id: str) -> tuple[dict[str, Any], str]:
    staged = _read_json(root / _staged_path(candidate_id))
    if _valid_candidate_record(staged, candidate_id, expected_status="staged_patch"):
        return staged, ""
    if (root / _completed_path(candidate_id)).exists():
        return {}, "candidate_not_staged"
    return {}, "candidate_not_found"


def _reject_staged_maintenance(root: Path, candidate_id: str) -> dict[str, Any]:
    staged_path = root / _staged_path(candidate_id)
    with state_lock(root / _candidate_lock_path(candidate_id)):
        staged, staged_error = _load_staged_candidate(root, candidate_id)
        if staged_error:
            return {"updated": False, "reason": staged_error}
        payload = {
            **staged,
            "status": "rejected",
            "maintenance_outcome": "rejected",
            "completed_at": _now(),
            "verification_kind": "not_applicable",
            "next_action": "none",
        }
        try:
            _transition_record(staged_path, root / _completed_path(candidate_id), payload)
        except (OSError, ValueError) as error:
            return {"updated": False, "reason": "write_failed", "error": error.__class__.__name__}
    return {
        "updated": True,
        "candidate_id": candidate_id,
        "status": "rejected",
        "verification_kind": "not_applicable",
    }


def _target_matches_promotion(target_relative: str, promotion_target: str) -> bool:
    return bool(promotion_target) and _skill_name_segment(target_relative) == promotion_target


def _target_scope_is_allowed(
    *,
    project: Path,
    target_path: Path,
    target_scope: str,
    target_relative: str,
    promotion_target: str,
) -> bool:
    if not _target_matches_promotion(target_relative, promotion_target):
        return False
    if target_scope == "rules":
        return True
    if target_scope != "project":
        return False

    parts = Path(target_relative).parts
    allowed_prefixes = (
        (".agents", "shared", "llm-skills"),
        (".agents", "local", "skills"),
    )
    prefix = next(
        (candidate for candidate in allowed_prefixes if parts[: len(candidate)] == candidate),
        None,
    )
    if prefix is None or len(parts) <= len(prefix):
        return False
    bundle = project.resolve().joinpath(*prefix, parts[len(prefix)])
    try:
        target_path.resolve().relative_to(bundle.resolve())
    except ValueError:
        return False
    return (bundle / "SKILL.md").is_file()


def _target_sha256(target_path: Path) -> str:
    try:
        return sha256_file(target_path) if target_path.is_file() else ""
    except OSError:
        return ""
