"""Durable failure checkpoints and bounded repair attempts.

Owner: the failure-repair persistence boundary.
Allowed imports: standard-library utilities plus execution-capsule state,
route identity, and state-lock helpers.
Forbidden imports: finish/review hook orchestration, skill-feedback processing,
workflow routing, or project-specific policy.
Callers/tests: finish and review failure reporters plus hook repair validation;
focused regression coverage lives in ``tests/test_agent_repair_ledger_cycle.py``.
Verification: run the checkpoint-signature, bounded-attempt, concurrency, and
finish-reporting regression tests before broader workflow validation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_route_state import (
    preflight_evidence_sha256,
    request_fingerprint,
    route_fingerprint,
)
from agent_state_lock import state_lock


SCHEMA_VERSION = 1
REBOUND = "rebound"
NOT_APPLICABLE = "not_applicable"
CONFLICT = "conflict"


def failure_signature(failures: list[str]) -> str:
    return hashlib.sha256(";".join(sorted(failures)).encode("utf-8")).hexdigest()[:16]


def repair_checkpoint_path_for_preflight(evidence_path: Path) -> Path:
    if evidence_path.name == "preflight.json":
        return evidence_path.parent / "repair-checkpoints.json"
    return evidence_path.parent / f"{evidence_path.stem}-repair-checkpoints.json"


def capture_failure_checkpoint_binding(evidence_path: Path) -> dict[str, str]:
    """Capture a content-free binding before start replaces preflight bytes.

    The repair ledger itself deliberately stores no request content.  This
    in-memory receipt adds only the old request fingerprint so a later
    required-document refresh cannot accidentally transfer a failed checkpoint
    to another task that happens to use the same route.
    """

    path = repair_checkpoint_path_for_preflight(evidence_path)
    with state_lock(path):
        payload = read_json_object(path)
        preflight = read_json_object(evidence_path)
        if (
            not payload
            or payload.get("invalid_json")
            or payload.get("schema_version") != SCHEMA_VERSION
            or not isinstance(payload.get("failed_checkpoints"), list)
            or not payload.get("failed_checkpoints")
            or not preflight
            or preflight.get("invalid_json")
            or not _same_evidence_path(payload.get("preflight_evidence"), evidence_path)
        ):
            return {}
        try:
            evidence_sha256 = preflight_evidence_sha256(evidence_path)
        except OSError:
            return {}
        current_route_fingerprint = route_fingerprint(preflight.get("route") or {})
        if (
            payload.get("preflight_evidence_sha256") != evidence_sha256
            or payload.get("route_fingerprint") != current_route_fingerprint
        ):
            return {}
        return {
            "preflight_evidence_sha256": evidence_sha256,
            "route_fingerprint": current_route_fingerprint,
            "request_fingerprint": request_fingerprint(
                preflight.get("request_intake") or {}
            ),
        }


def rebind_failure_checkpoints_after_required_doc_refresh(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    prior_binding: dict[str, str],
    required_doc_drift: bool,
) -> str:
    """Rebind one valid repair ledger after same-task required-doc drift.

    Returning ``conflict`` is intentionally distinct from a non-applicable
    binding: once the exact same task proved required-doc drift, losing or
    replacing its captured failure ledger must stop start rather than silently
    granting a fresh repair budget.
    """

    if not required_doc_drift or not prior_binding:
        return NOT_APPLICABLE
    _enforce_worker_evidence_boundary(evidence_path)
    current_route_fingerprint = route_fingerprint(preflight.get("route") or {})
    current_request_fingerprint = request_fingerprint(
        preflight.get("request_intake") or {}
    )
    if (
        prior_binding.get("route_fingerprint") != current_route_fingerprint
        or prior_binding.get("request_fingerprint") != current_request_fingerprint
    ):
        return NOT_APPLICABLE

    path = repair_checkpoint_path_for_preflight(evidence_path)
    with state_lock(path):
        payload = read_json_object(path)
        if (
            not payload
            or payload.get("invalid_json")
            or payload.get("schema_version") != SCHEMA_VERSION
            or not isinstance(payload.get("failed_checkpoints"), list)
            or not payload.get("failed_checkpoints")
            or not _same_evidence_path(payload.get("preflight_evidence"), evidence_path)
            or payload.get("preflight_evidence_sha256")
            != prior_binding.get("preflight_evidence_sha256")
            or payload.get("route_fingerprint") != current_route_fingerprint
        ):
            return CONFLICT
        try:
            payload["preflight_evidence_sha256"] = preflight_evidence_sha256(
                evidence_path
            )
        except OSError:
            return CONFLICT
        payload["rebound_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(path, payload)
    return REBOUND


def record_failure_checkpoints(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    checkpoints: list[str],
    signature: str = "",
    checkpoint_signatures: dict[str, str] | None = None,
) -> None:
    """Persist actual hook or finish failures without resetting a used retry."""

    _enforce_worker_evidence_boundary(evidence_path)
    if not checkpoints:
        return
    path = repair_checkpoint_path_for_preflight(evidence_path)
    with state_lock(path):
        prior = _recorded_failure_payload(preflight.get("route") or {}, evidence_path)
        # Always carry every checkpoint's repair_attempts forward, regardless
        # of whether the overall batch signature changed. The overall
        # signature is a hash of ALL failures in this run, so it changes
        # whenever ANY checkpoint's message differs -- gating the carry-
        # forward on it wiped every OTHER checkpoint's already-consumed
        # attempt too. register_repair_attempt already resets a specific
        # checkpoint's count on its own when THAT checkpoint's signature
        # changed; this function must not duplicate that at the batch level.
        attempts = prior.get("repair_attempts")
        resolved_signatures = {
            checkpoint: str((checkpoint_signatures or {}).get(checkpoint) or signature)
            for checkpoint in sorted(set(checkpoints))
        }
        payload = {
            "schema_version": SCHEMA_VERSION,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "preflight_evidence": str(evidence_path.resolve()),
            "preflight_evidence_sha256": preflight_evidence_sha256(evidence_path),
            "route_fingerprint": route_fingerprint(preflight.get("route") or {}),
            "failed_checkpoints": sorted(set(checkpoints)),
            "failure_signature": signature,
            "failure_signatures": resolved_signatures,
            "repair_attempts": attempts if isinstance(attempts, dict) else {},
        }
        atomic_write_json(path, payload)


def record_finish_failure_checkpoints(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    checkpoints: list[str],
    failure_signature: str = "",
    checkpoint_signatures: dict[str, str] | None = None,
) -> None:
    """Compatibility wrapper for callers using the former finish-only name."""

    record_failure_checkpoints(
        evidence_path=evidence_path,
        preflight=preflight,
        checkpoints=checkpoints,
        signature=failure_signature,
        checkpoint_signatures=checkpoint_signatures,
    )


def checkpoint_has_recorded_failure(
    *, route: dict[str, Any], evidence_path: Path, checkpoint: str
) -> bool:
    payload = _recorded_failure_payload(route, evidence_path)
    return checkpoint in (payload.get("failed_checkpoints") or [])


def checkpoint_failure_signature(
    *, route: dict[str, Any], evidence_path: Path, checkpoint: str
) -> str:
    payload = _recorded_failure_payload(route, evidence_path)
    signatures = payload.get("failure_signatures")
    if isinstance(signatures, dict) and checkpoint in signatures:
        return str(signatures.get(checkpoint) or "")
    # Compatibility for ledgers written before checkpoint-specific signatures.
    return str(payload.get("failure_signature") or "")


def register_repair_attempt(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    checkpoint: str,
    limit: int,
    failure_signature: str = "",
) -> tuple[bool, int]:
    """Atomically consume one retry for one recorded checkpoint and failure."""

    _enforce_worker_evidence_boundary(evidence_path)
    path = repair_checkpoint_path_for_preflight(evidence_path)
    with state_lock(path):
        payload = _recorded_failure_payload(preflight.get("route") or {}, evidence_path)
        if not payload:
            return False, 0
        attempts = payload.get("repair_attempts")
        if not isinstance(attempts, dict):
            attempts = {}
        prior = attempts.get(checkpoint)
        count = int(prior.get("count", 0)) if isinstance(prior, dict) else 0
        if isinstance(prior, dict) and failure_signature:
            # Only a real (non-empty) incoming signature can prove this is a
            # different failure, so only reset on a non-empty incoming
            # signature -- a call site that can't compute one at all must
            # not get a free reset of an already-consumed budget. But an
            # empty PRIOR signature (an earlier attempt recorded without a
            # computable signature) must not be trusted as "definitely the
            # same failure" either: the previous `prior_signature and
            # prior_signature != failure_signature` check required
            # prior_signature to be truthy before it would ever reset,
            # so an empty prior signature stayed "" forever and permanently
            # locked the checkpoint out of repair even once a later, real,
            # provably different signature showed up.
            prior_signature = str(prior.get("failure_signature") or "")
            if not prior_signature or prior_signature != failure_signature:
                count = 0
        if count >= limit:
            return False, count
        count += 1
        attempts[checkpoint] = {
            "count": count,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "failure_signature": failure_signature,
        }
        payload["repair_attempts"] = attempts
        atomic_write_json(path, payload)
    return True, count


def release_repair_attempt(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    checkpoint: str,
    failure_signature: str,
) -> bool:
    """Release the matching repair claim when a hook rejects its invocation."""

    if not failure_signature:
        return False
    _enforce_worker_evidence_boundary(evidence_path)
    path = repair_checkpoint_path_for_preflight(evidence_path)
    with state_lock(path):
        payload = _recorded_failure_payload(preflight.get("route") or {}, evidence_path)
        attempts = payload.get("repair_attempts") if payload else None
        if not isinstance(attempts, dict):
            return False
        prior = attempts.get(checkpoint)
        if not isinstance(prior, dict):
            return False
        if str(prior.get("failure_signature") or "") != failure_signature:
            return False
        if int(prior.get("count", 0)) != 1:
            return False
        attempts.pop(checkpoint)
        payload["repair_attempts"] = attempts
        atomic_write_json(path, payload)
    return True


def _recorded_failure_payload(route: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
    payload = read_json_object(repair_checkpoint_path_for_preflight(evidence_path))
    if not payload or payload.get("invalid_json"):
        return {}
    if not _same_evidence_path(payload.get("preflight_evidence"), evidence_path):
        return {}
    if payload.get("preflight_evidence_sha256") != preflight_evidence_sha256(evidence_path):
        return {}
    if payload.get("route_fingerprint") != route_fingerprint(route):
        return {}
    return payload


def _same_evidence_path(recorded: Any, evidence_path: Path) -> bool:
    try:
        return Path(str(recorded)).expanduser().resolve() == evidence_path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _enforce_worker_evidence_boundary(evidence_path: Path) -> None:
    import os

    if os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        raise PermissionError("reusable worker capsule cannot write parent repair evidence")
    expected = os.environ.get("TAO_WORKER_EVIDENCE")
    if expected and evidence_path.resolve() != Path(expected).expanduser().resolve():
        raise PermissionError("worker may write only its launcher-issued repair evidence")
