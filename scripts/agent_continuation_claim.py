"""The one registry transaction that hands a run to a resuming session.

Continuation takeover is not a second question: may this session adopt a run
another session started is exactly what the run registry and ``agent_run_owner``
already answer for exclusive start claims. This module reuses that answer and
adds the part the low-level ``resume_run`` state flip omits -- installing the
resuming process as the new owner. Without that, a revived run keeps a dead
owner, stays provably dead, and the next sweep fails it again immediately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import binding_record
from agent_continuation_packet import ContinuationPacketError
from agent_continuation_store import (
    continuation_path,
    read_continuation_packet,
    write_continuation_packet,
)
from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_run_owner import (
    LIVE_OWNER_GRACE_MULTIPLIER,
    owner_death_is_proven,
    owner_is_gone,
    process_owner,
)
from agent_run_registry import read_registry_state, registry_path
from agent_state_lock import project_state_lock, state_lock


HOLDER_STATES = ("live", "dead_proven", "unproven_wait", "unproven_expired")
FREE_HOLDER_STATES = ("dead_proven", "unproven_expired")
TERMINAL_RUN_STATES = ("completed", "cancelled")
HOLDER_REFUSALS = {"live": "live_owner_refused", "unproven_wait": "owner_unproven_wait"}


def holder_state(
    run: dict[str, Any],
    *,
    stale_after_seconds: int = 3600,
    now: datetime | None = None,
) -> str:
    """Classify who still holds a run, using the stale sweep's exact rules.

    Proof of death releases a claim immediately at any age, because exclusive
    claims would otherwise strand an agent retrying its own request. Absent
    owner evidence is not proof, so it keeps the bounded timestamp fallback, and
    a live owner buys more silence but never unlimited silence.
    """

    owner = run.get("owner")
    if owner_death_is_proven(owner):
        return "dead_proven"
    moment = now or datetime.now(timezone.utc)
    try:
        updated = datetime.fromisoformat(str(run.get("updated_at")))
    except (TypeError, ValueError):
        # An unreadable timestamp cannot prove abandonment; keep the run held
        # rather than freeing it on malformed state.
        return "live" if not owner_is_gone(owner) else "unproven_wait"
    if updated >= moment - timedelta(seconds=stale_after_seconds):
        return "unproven_wait" if owner_is_gone(owner) else "live"
    ceiling = moment - timedelta(seconds=stale_after_seconds * LIVE_OWNER_GRACE_MULTIPLIER)
    if updated >= ceiling and not owner_is_gone(owner):
        return "live"
    return "unproven_expired"


def claim_resume(
    project: Path,
    run_id: str,
    *,
    expected_generation: int,
    drift: dict[str, Any],
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Take over one run, or lose the attempt, in a single registry transaction.

    Everything that decides the outcome happens under the same lock the
    exclusive start claim uses: resolving the run and its packet binding,
    applying the owner policy, rejecting a stale resume generation, installing
    this process as the owner, and recording the resulting run state. A caller
    that loses must not retry silently; the winner already owns the run.
    """

    path = registry_path(project)
    clean = drift.get("status") == "clean"
    with project_state_lock(project), state_lock(path):
        payload = read_registry_state(path)
        run = next((item for item in payload["runs"] if item.get("run_id") == run_id), None)
        if run is None or run.get("state") in TERMINAL_RUN_STATES:
            return _refusal("not_found", run_id)
        packet, packet_refusal = _bound_packet(project, run_id)
        if packet_refusal:
            return packet_refusal
        state = holder_state(run, stale_after_seconds=stale_after_seconds)
        # The generation is checked before the owner policy on purpose. Once
        # another claimant has won, the owner it installed is legitimately
        # live, and reporting that as a live-owner refusal would hide the race
        # behind a code that invites waiting instead of stopping.
        if int(run.get("resume_generation") or 0) != int(expected_generation):
            return _refusal("claim_lost", run_id, holder_state=state)
        if state in HOLDER_REFUSALS:
            return _refusal(HOLDER_REFUSALS[state], run_id, holder_state=state)
        generation = int(run.get("resume_generation") or 0) + 1
        run["resume_generation"] = generation
        run["owner"] = process_owner()
        run["state"] = "running" if clean else "reconcile_required"
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(path, payload)
        if clean and drift.get("pending_state") == "pending_clean":
            packet = _clear_pending_mutation(project, packet)
    return {
        "result": "ready" if clean else "drift_refused",
        "run_id": run_id,
        "holder_state": state,
        "resume_generation": generation,
        "run_state": run["state"],
        "changed_signals": list(drift.get("changed_signals") or []),
        "affected_paths": list(drift.get("affected_paths") or []),
        "phase": "reconcile_required" if not clean else packet.get("phase"),
        # A refusal returns no semantic work object; only a clean claim does.
        "packet": packet if clean else None,
    }


def _bound_packet(project: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve the packet and prove it still binds this run's trust record."""

    result = read_continuation_packet(project, continuation_path(project, run_id))
    if result["status"] != "ok":
        status = result["status"]
        return {}, _refusal(
            status if status == "local_boundary_failed" else "invalid_packet",
            run_id,
            failures=result["failures"],
        )
    packet = result["packet"]
    binding = packet["binding"]
    binding_path = continuation_path(project, run_id).parent / str(binding["filename"])
    try:
        current = binding_record(binding_path, read_json_object(binding_path))
    except (ContinuationPacketError, OSError):
        current = None
    if current != binding:
        return {}, _refusal("invalid_packet", run_id, failures=[
            {"rule": "binding_moved", "pointer": "/binding"},
        ])
    return packet, None


def _clear_pending_mutation(project: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Drop a pending record whose bytes never moved, so work simply restarts.

    The process died before the tool wrote anything, so the pre-mutation state
    still matches and that same checkpoint can be attempted again. Nothing else
    in the packet is rewritten, and a pending record whose bytes did move never
    reaches here -- that path is reconciliation, not resume.
    """

    updated = dict(packet)
    updated["checkpoint"] = {**packet["checkpoint"], "mutation_pending": None}
    updated["generation"] = int(packet.get("generation") or 0) + 1
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_continuation_packet(project, updated)
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
