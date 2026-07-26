"""Fail-closed validation for structural failure-repair receipts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import sha256_file
from agent_repair_ledger import checkpoint_failure_signature
from agent_route_state import preflight_evidence_sha256, route_fingerprint
from agent_verification_command import (
    UNITTEST_SELECTOR_RE,
    VERIFICATION_KINDS,
    resolve_verification_target,
    run_verification_command,
    verification_command,
    verification_target_is_changed,
    verification_workdir,
)


SCHEMA_VERSION = 1
RECEIPT_ID_RE = re.compile(r"^[a-f0-9]{24}$")


def validate_repair_receipt(
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
    preflight: dict[str, Any],
    target: str,
    checkpoint: str,
    receipt_path: Path,
) -> list[str]:
    try:
        resolved_receipt = receipt_path.resolve()
        resolved_receipt.relative_to((project / ".tao").resolve())
        payload = json.loads(resolved_receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ["--repair-evidence must name a project-local structural repair receipt"]
    if not isinstance(payload, dict):
        return ["--repair-evidence repair receipt must be a JSON object"]

    failures: list[str] = []
    route = preflight.get("route") or {}
    resolved_target = resolve_verification_target(project, rules, target)
    if resolved_target is None or not resolved_target[0].is_file():
        return ["--repair-target must name an existing file under project or rules root"]
    target_path, target_scope, target_relative, target_root = resolved_target
    if not verification_target_is_changed(
        target_root,
        target_path,
        preflight=preflight,
        target_relative=target_relative,
    ):
        failures.append("repair target is no longer changed in the bound worktree")
    expected = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": checkpoint.strip(),
        "failure_signature": checkpoint_failure_signature(
            route=route, evidence_path=evidence_path, checkpoint=checkpoint.strip()
        ),
        "preflight_evidence_sha256": preflight_evidence_sha256(evidence_path),
        "route_fingerprint": route_fingerprint(route),
        "target_scope": target_scope,
        "target_relative": target_relative,
        "target_sha256": sha256_file(target_path),
        "returncode": 0,
        "status": "SUCCESS",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            failures.append(f"repair receipt field {field!r} does not match current repair state")
    verification_kind = str(payload.get("verification_kind") or "")
    test_selector = str(payload.get("test_selector") or "")
    if verification_kind not in VERIFICATION_KINDS:
        failures.append("repair receipt verification_kind is not allowlisted")
    if verification_kind == "py_compile" and target_path.suffix != ".py":
        failures.append("py_compile repair receipt requires a Python repair target")
    if verification_kind == "unittest" and not UNITTEST_SELECTOR_RE.fullmatch(test_selector):
        failures.append("unittest repair receipt has an invalid selector")
    if verification_kind != "unittest" and test_selector:
        failures.append("repair receipt test_selector is only allowed for unittest")
    if not _receipt_identity_is_valid(payload):
        failures.append("repair receipt identity is invalid or has been modified")
    if failures:
        return failures
    command = verification_command(
        project=project,
        rules=rules,
        target=target_path,
        verification_kind=verification_kind,
        test_selector=test_selector,
    )
    if not command:
        return ["repair receipt cannot reconstruct its allowlisted verification command"]
    result = run_verification_command(
        command,
        verification_workdir(
            verification_kind=verification_kind,
            target_root=target_root,
            rules=rules,
        ),
    )
    return [] if result.get("returncode") == 0 else [
        "repair receipt verification no longer succeeds when re-executed"
    ]


def _receipt_identity_is_valid(payload: dict[str, Any]) -> bool:
    fields = (
        "schema_version", "checkpoint", "failure_signature",
        "preflight_evidence_sha256", "route_fingerprint", "target_scope",
        "target_relative", "target_sha256", "verification_kind",
        "test_selector", "returncode", "status",
    )
    core = {field: payload.get(field) for field in fields}
    expected = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    receipt_id = str(payload.get("receipt_id") or "")
    return bool(RECEIPT_ID_RE.fullmatch(receipt_id)) and receipt_id == expected
