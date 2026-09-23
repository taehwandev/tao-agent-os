"""Two-phase, owner-aware takeover of one continuation run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import binding_record, binding_required_docs
from agent_continuation_drift import capture_drift_state, verify_drift
from agent_continuation_mutation_state import MutationCheckpointState
from agent_continuation_packet import ContinuationPacketError
from agent_continuation_store import continuation_path, read_continuation_packet, write_continuation_packet
from agent_execution_capsule_state import atomic_write_json, git_states_for_paths, read_json_object
from agent_run_owner import process_owner
from agent_route_state import route_fingerprint
from agent_runtime_session import runtime_session
from agent_run_registry import read_registry_state, registry_path, resume_holder_state
from agent_state_lock import project_state_lock, state_lock
FREE_HOLDER_STATES = ("dead_proven", "unproven_expired", "same_session_stopped")
TERMINAL_RUN_STATES = ("completed", "cancelled")
HOLDER_REFUSALS = {"live": "live_owner_refused", "unproven_wait": "owner_unproven_wait"}
# Drift that could not be measured at all. It is a signal rather than a bare
# `project_worktree` so that the reconciliation below can never mistake "the
# checkout moved" for "nothing could be compared".
UNMEASURED = "unmeasured"
# The signals a session resuming its own stopped run can account for from the
# turn it just ended. It made that byte movement and still holds the
# conversation that explains it, so refusing them made the ordinary turn
# boundary -- the moment Tao itself marks the run `interrupted` -- the end of
# the run: its own edits are `project_worktree`, its own commit is `head`, and
# a rules checkout advancing under it is `rules_worktree`. Moved guidance, a
# half-written mutation, and drift nothing could measure are none of those, and
# still require explicit reconciliation before the packet is handed back.
RECONCILABLE_SIGNALS = frozenset({"head", "project_worktree", "rules_worktree"})


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
        drift = _drift_verdict([UNMEASURED, "project_worktree"], [], None)
    result = _commit_claim(project, reservation, capture, drift)
    if result.get("result") == "drift_refused":
        _learn_reconcile_block(run_id)
    return result


def _learn_reconcile_block(run_id: str) -> None:
    """Count a drift-refused resume, keyed by the run so its repair retires it."""
    try:
        from agent_block_lessons import record_block

        record_block("run_reconcile", "resume_drift_refused", run_id=run_id)
    except Exception:  # noqa: BLE001 - learning never changes the claim result
        pass

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
        version = (binding.get("route") or {}).get("lifecycle_version", 1)
        if type(version) is not int or version not in (1, 2):
            return _refusal("unsupported_lifecycle", run_id)
        stopped = run.get("state") in {"blocked", "interrupted"}
        if stopped and (
            version != 2
            or run.get("route_fingerprint") != route_fingerprint(binding.get("route") or {})
        ):
            return _refusal("invalid_packet", run_id)
        holder = resume_holder_state(run, stale_after_seconds=stale_after_seconds)
        if stopped_session_matches(run, binding):
            holder = "same_session_stopped"
        if int(run.get("resume_generation") or 0) != int(expected_generation):
            return _refusal("claim_lost", run_id, holder_state=holder)
        if holder in HOLDER_REFUSALS:
            return _refusal(HOLDER_REFUSALS[holder], run_id, holder_state=holder)
        generation = int(run.get("resume_generation") or 0) + 1
        owner = process_owner()
        previous_state = run.get("state")
        previous_owner = run.get("owner")
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
        "expected_generation": int(expected_generation),
        "previous_state": previous_state,
        "previous_owner": previous_owner,
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
        resumable = clean or _stopped_session_reconciles(reservation, drift)
        if resumable and not clean:
            # Returning the objective does not make pre-drift checks reusable.
            packet = {**packet, "work": {**packet["work"], "verification": []}}
        generation = reservation["resume_generation"]
        if not resumable:
            # A refused claim is not a taken claim. The reservation advanced the
            # generation before drift could be judged, and the run's evidence
            # still records the old one, so leaving it advanced unbinds the run
            # from its own evidence: `resolve_runtime_evidence` stops matching
            # it, every later hook falls back to a default path that does not
            # exist, and the refusal silently ends the run instead of asking for
            # the reconciliation it names. Handing the reservation back leaves
            # the run exactly as refusable, and still reachable.
            generation = reservation["expected_generation"]
            run["resume_generation"] = generation
            if reservation["previous_owner"] is None:
                run.pop("owner", None)
            else:
                run["owner"] = reservation["previous_owner"]
        run["state"] = "running" if resumable else "reconcile_required"
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(path, payload)
    return {
        "result": "ready" if resumable else "drift_refused",
        "run_id": run_id,
        "holder_state": reservation["holder_state"],
        "resume_generation": generation,
        "run_state": run["state"],
        "evidence_path": str(reservation["binding_path"]),
        "changed_signals": list(drift.get("changed_signals") or []),
        "affected_paths": list(drift.get("affected_paths") or []),
        "phase": packet.get("phase") if resumable else "reconcile_required",
        "packet": packet if resumable else None,
    }


def _stopped_session_reconciles(
    reservation: dict[str, Any], drift: dict[str, Any]
) -> bool:
    """Whether the session resuming its own stopped run may carry this drift.

    Work identity and verification validity are separate questions. Bytes that
    moved during the turn this session just ended do not make the run someone
    else's work; they make some of its recorded evidence stale, which the gate
    ledger's own input records already decide. The claim is granted and every
    changed signal is reported, so the agent re-observes what the movement
    touched instead of carrying the objective into a fresh start.
    """

    signals = drift.get("changed_signals") or []
    return (
        reservation.get("holder_state") == "same_session_stopped"
        and bool(signals)
        and all(signal in RECONCILABLE_SIGNALS for signal in signals)
    )


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
        signals.extend((UNMEASURED, "project_worktree"))
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
    baseline = MutationCheckpointState.path(project, str(packet["run_id"]))
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


def stopped_session_matches(run: dict[str, Any], binding: dict[str, Any]) -> bool:
    """A stopped live process may reclaim only its own exact runtime session."""
    session = runtime_session()
    return (
        run.get("state") in {"blocked", "interrupted"}
        and bool(session.get("session_id"))
        and binding.get("runtime_session") == session
        and type((binding.get("route") or {}).get("lifecycle_version")) is int
        and (binding.get("route") or {}).get("lifecycle_version") == 2
    )
