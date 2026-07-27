"""Structural repair receipts.

Owner/import boundary: allowlisted check execution may use route, repair-ledger,
and atomic-state helpers, never prose parsers or canonical writers.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json, sha256_file
from agent_repair_ledger import (
    checkpoint_failure_signature,
    checkpoint_has_recorded_failure,
)
from agent_route_state import preflight_evidence_sha256, route_fingerprint
from agent_repair_receipt_validation import validate_repair_receipt
from agent_verification_command import (
    Runner,
    VERIFICATION_KINDS,
    resolve_verification_target,
    run_verification_command,
    verification_command,
    verification_target_is_changed,
    verification_workdir,
)


SCHEMA_VERSION = 1


def create_repair_receipt(
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
    preflight: dict[str, Any],
    target: str,
    checkpoint: str,
    verification_kind: str,
    test_selector: str = "",
    output_path: Path | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    route = preflight.get("route") or {}
    checkpoint_text = checkpoint.strip()
    if verification_kind not in VERIFICATION_KINDS:
        return {"created": False, "reason": "unsupported_verification_kind"}
    if not checkpoint_text or not checkpoint_has_recorded_failure(
        route=route,
        evidence_path=evidence_path,
        checkpoint=checkpoint_text,
    ):
        return {"created": False, "reason": "checkpoint_not_failed"}
    resolved = resolve_verification_target(project, rules, target)
    if resolved is None or not resolved[0].is_file():
        return {"created": False, "reason": "target_not_found"}
    target_path, target_scope, target_relative, target_root = resolved
    if not verification_target_is_changed(
        target_root,
        target_path,
        preflight=preflight,
        target_relative=target_relative,
    ):
        return {"created": False, "reason": "target_not_changed"}
    command = verification_command(
        project=project,
        rules=rules,
        target=target_path,
        verification_kind=verification_kind,
        test_selector=test_selector,
    )
    if not command:
        return {"created": False, "reason": "invalid_verification_contract"}

    execute = runner or run_verification_command
    result = execute(
        command,
        verification_workdir(
            verification_kind=verification_kind,
            target_root=target_root,
            rules=rules,
        ),
    )
    returncode = int(result.get("returncode", 1))
    status = "SUCCESS" if returncode == 0 else "FAIL"
    core = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": checkpoint_text,
        "failure_signature": checkpoint_failure_signature(
            route=route,
            evidence_path=evidence_path,
            checkpoint=checkpoint_text,
        ),
        "preflight_evidence_sha256": preflight_evidence_sha256(evidence_path),
        "route_fingerprint": route_fingerprint(route),
        "target_scope": target_scope,
        "target_relative": target_relative,
        "target_sha256": sha256_file(target_path),
        "verification_kind": verification_kind,
        "test_selector": test_selector if verification_kind == "unittest" else "",
        "returncode": returncode,
        "status": status,
    }
    receipt_id = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    payload = {
        **core,
        "receipt_id": receipt_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    destination = output_path or (
        project / ".tao" / "repair-verification" / f"{receipt_id}.json"
    )
    try:
        destination = destination.resolve()
        destination.relative_to((project / ".tao").resolve())
        atomic_write_json(destination, payload)
    except (OSError, ValueError):
        return {"created": False, "reason": "receipt_write_failed"}
    return {
        "created": True,
        "receipt_path": str(destination),
        "receipt_id": receipt_id,
        "status": status,
        "returncode": returncode,
    }
