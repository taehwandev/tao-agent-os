"""Two-phase, owner-aware takeover of one continuation run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import MUTATION_BASELINE_FILENAME, binding_record, binding_required_docs
from agent_continuation_drift import capture_drift_state, verify_drift
from agent_continuation_packet import ContinuationPacketError
from agent_continuation_store import continuation_path, read_continuation_packet, write_continuation_packet
from agent_execution_capsule_state import atomic_write_json, git_states_for_paths, read_json_object
from agent_run_owner import process_owner
from agent_run_registry import read_registry_state, registry_path, resume_holder_state
from agent_state_lock import project_state_lock, state_lock
FREE_HOLDER_STATES = ("dead_proven", "unproven_expired")
TERMINAL_RUN_STATES = ("completed", "cancelled")
HOLDER_REFUSALS = {"live": "live_owner_refused", "unproven_wait": "owner_unproven_wait"}


def claim_resume(
    project: Path,
    run_id: str,
    *,
    expected_generation: int,
    rules: Path | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Reserve, capture authoritative drift, then CAS the exact reservation."""

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    reservation = _reserve(project, run_id, expected_generation, stale_after_seconds)
    if reservation.get("result") != "reserved":
        return reservation
    rules_root = _rules_root(reservation["binding"], rules, project)
    reservation["rules_root"] = rules_root
    try:
        capture, drift = _capture_validation(
            project,
            rules_root,
            reservation["packet"],
            binding_required_docs(reservation["binding"]),
        )
    except (OSError, RuntimeError, ValueError):
        capture = None
        drift = _drift_verdict(["project_worktree"], [], None)
    return _commit_claim(project, reservation, capture, drift)

def _reserve(
    project: Path,
    run_id: str,
    expected_generation: int,
    stale_after_seconds: int,
) -> dict[str, Any]:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = read_registry_state(path)
        run = next((item for item in payload["runs"] if item.get("run_id") == run_id), None)
        if run is None or run.get("state") in TERMINAL_RUN_STATES:
            return _refusal("not_found", run_id)
        packet, binding, binding_path, packet_refusal = _bound_packet(project, run_id)
        if packet_refusal:
            return packet_refusal
        holder = resume_holder_state(run, stale_after_seconds=stale_after_seconds)
        if int(run.get("resume_generation") or 0) != int(expected_generation):
            return _refusal("claim_lost", run_id, holder_state=holder)
        if holder in HOLDER_REFUSALS:
            return _refusal(HOLDER_REFUSALS[holder], run_id, holder_state=holder)
        generation = int(run.get("resume_generation") or 0) + 1
        owner = process_owner()
        run.update(
            resume_generation=generation,
            owner=owner,
            state="resuming",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        atomic_write_json(path, payload)
    return {
        "result": "reserved",
        "run_id": run_id,
        "holder_state": holder,
        "resume_generation": generation,
        "owner": owner,
        "packet": packet,
        "binding": binding,
        "binding_path": binding_path,
    }

def _capture_validation(
    project: Path,
    rules: Path,
    packet: dict[str, Any],
    required_docs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    recorded = packet.get("drift") or {}
    capture = capture_drift_state(
        project, rules, str(recorded.get("required_docs_sha256") or "")
    )
    verified = verify_drift(
        project, rules, packet, required_doc_records=required_docs
    )
    forced = _capture_signals(packet, capture)
    signals = list(dict.fromkeys([*(verified.get("changed_signals") or []), *forced]))
    return capture, _drift_verdict(
        signals,
        list(verified.get("affected_paths") or []),
        verified.get("pending_state"),
        phase=verified.get("phase"),
    )


def _commit_claim(
    project: Path,
    reservation: dict[str, Any],
    capture: dict[str, Any] | None,
    drift: dict[str, Any],
) -> dict[str, Any]:
    path = registry_path(project)
    run_id = reservation["run_id"]
    rules = reservation["rules_root"]
    with project_state_lock(project), state_lock(path):
        payload = read_registry_state(path)
        run = next((item for item in payload["runs"] if item.get("run_id") == run_id), None)
        if not _reservation_matches(run, reservation):
            return _refusal("claim_lost", run_id)
        try:
            current = _current_capture(project, rules, capture)
        except (OSError, RuntimeError, ValueError):
            current = None
        if capture is None or current != capture:
            drift = _merge_capture_race(drift, capture, current)
        clean = drift.get("status") == "clean"
        packet = reservation["packet"]
        if clean and drift.get("pending_state") == "pending_clean":
            try:
                packet = _clear_pending_mutation(project, packet)
            except (OSError, ValueError):
                clean = False
                drift = _drift_verdict(
                    list(
                        dict.fromkeys(
                            [*(drift.get("changed_signals") or []), "pending_mutation"]
                        )
                    ),
                    list(drift.get("affected_paths") or []),
                    "pending_clean",
                )
        run["state"] = "running" if clean else "reconcile_required"
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(path, payload)
    return {
        "result": "ready" if clean else "drift_refused",
        "run_id": run_id,
        "holder_state": reservation["holder_state"],
        "resume_generation": reservation["resume_generation"],
        "run_state": run["state"],
        "evidence_path": str(reservation["binding_path"]),
        "changed_signals": list(drift.get("changed_signals") or []),
        "affected_paths": list(drift.get("affected_paths") or []),
        "phase": packet.get("phase") if clean else "reconcile_required",
        "packet": packet if clean else None,
    }


def _bound_packet(
    project: Path, run_id: str
) -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, Any] | None]:
    result = read_continuation_packet(project, continuation_path(project, run_id))
    if result["status"] != "ok":
        status = result["status"]
        return {}, {}, Path(), _refusal(
            status if status == "local_boundary_failed" else "invalid_packet",
            run_id,
            failures=result["failures"],
        )
    packet = result["packet"]
    if packet.get("run_id") != run_id:
        return {}, {}, Path(), _refusal(
            "invalid_packet",
            run_id,
            failures=[{"rule": "run_binding_mismatch", "pointer": "/run_id"}],
        )
    binding = packet["binding"]
    binding_path = continuation_path(project, run_id).parent / str(binding["filename"])
    try:
        binding_payload = read_json_object(binding_path)
        current = binding_record(binding_path, binding_payload)
    except (ContinuationPacketError, OSError):
        binding_payload = {}
        current = None
    if current != binding:
        return {}, {}, Path(), _refusal(
            "invalid_packet",
            run_id,
            failures=[{"rule": "binding_moved", "pointer": "/binding"}],
        )
    return packet, binding_payload, binding_path, None


def _rules_root(binding: dict[str, Any], rules: Path | None, project: Path) -> Path:
    return Path(str(binding["rules"])).resolve() if binding.get("rules") else (rules or project).resolve()


def _capture_signals(packet: dict[str, Any], capture: dict[str, Any]) -> list[str]:
    recorded = packet.get("drift") or {}
    signals: list[str] = []
    if (recorded.get("project") or {}).get("head") != capture["project"].get("head"):
        signals.append("head")
    if (recorded.get("project") or {}).get("worktree_fingerprint") != capture["project"].get(
        "worktree_fingerprint"
    ):
        signals.append("project_worktree")
    if (recorded.get("rules") or {}) != capture["rules"]:
        signals.append("rules_worktree")
    pending = (packet.get("checkpoint") or {}).get("mutation_pending")
    if isinstance(pending, dict) and (
        (pending.get("project") or {}) != capture["project"]
        or (pending.get("rules") or {}) != capture["rules"]
    ):
        signals.append("pending_mutation")
    return signals


def _drift_verdict(
    signals: list[str],
    affected: list[str],
    pending: str | None,
    *,
    phase: Any = None,
) -> dict[str, Any]:
    return {
        "status": "drift_refused" if signals else "clean",
        "phase": "reconcile_required" if signals else phase,
        "changed_signals": signals,
        "affected_paths": affected,
        "pending_state": pending,
    }


def _current_capture(
    project: Path, rules: Path, capture: dict[str, Any] | None
) -> dict[str, Any] | None:
    if capture is None:
        return None
    project_state, rules_state = git_states_for_paths(
        project,
        rules,
        project_record=capture["project"],
        rules_record=capture["rules"],
    )
    return {
        "project": project_state,
        "rules": rules_state,
        "required_docs_sha256": capture["required_docs_sha256"],
    }


def _reservation_matches(run: Any, reservation: dict[str, Any]) -> bool:
    return (
        isinstance(run, dict)
        and run.get("state") == "resuming"
        and run.get("owner") == reservation["owner"]
        and int(run.get("resume_generation") or 0) == reservation["resume_generation"]
    )


def _merge_capture_race(
    drift: dict[str, Any],
    capture: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    signals = list(drift.get("changed_signals") or [])
    if capture is None or current is None:
        signals.append("project_worktree")
    else:
        signals.extend(_capture_signals({"drift": capture, "checkpoint": {}}, current))
    return _drift_verdict(
        list(dict.fromkeys(signals)),
        list(drift.get("affected_paths") or []),
        drift.get("pending_state"),
    )


def _clear_pending_mutation(project: Path, packet: dict[str, Any]) -> dict[str, Any]:
    updated = dict(packet)
    updated["checkpoint"] = {**packet["checkpoint"], "mutation_pending": None}
    updated["generation"] = int(packet.get("generation") or 0) + 1
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_continuation_packet(project, updated)
    baseline = continuation_path(project, str(packet["run_id"])).parent / MUTATION_BASELINE_FILENAME
    baseline.unlink(missing_ok=True)
    return updated


def _refusal(
    result: str,
    run_id: str,
    *,
    holder_state: str = "",
    failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "result": result,
        "run_id": run_id,
        "holder_state": holder_state,
        "resume_generation": None,
        "run_state": "",
        "changed_signals": [],
        "affected_paths": [],
        "phase": None,
        "packet": None,
        "failures": failures or [],
    }
