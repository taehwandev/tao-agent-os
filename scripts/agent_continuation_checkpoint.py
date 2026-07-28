"""The during-work continuation checkpoint writer.

A shutdown-time write cannot describe a shutdown that never runs, and a
gate-only write hides hours of edits behind the same defect. The packet is
therefore rewritten in full at every durable semantic or mutation boundary:
initial, before and after each bounded mutation, at each material decision, at
each lifecycle transition, and -- best effort only -- at Stop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_drift import capture_drift_state, required_docs_digest
from agent_continuation_fields import failure
from agent_continuation_mutation_state import MutationCheckpointState
from agent_continuation_packet import (
    CONTINUATION_SCHEMA_VERSION,
    STORAGE_CLASS,
    ContinuationPacketError,
)
from agent_continuation_store import (
    continuation_path,
    read_continuation_packet,
    write_continuation_packet,
)
from agent_execution_capsule_state import (
    CAPSULE_FILENAME,
    atomic_write_json,
    execution_capsule_binding_fingerprint,
    preflight_snapshot_binding_fingerprint,
    read_json_object,
    sha256_file,
)
from agent_gate_evidence import (
    gate_evidence_path_for_preflight,
    read_gate_evidence_ledger,
)
from agent_route_state import route_fingerprint
from agent_run_owner import process_owner
from agent_run_registry import read_registry_state, registry_path
from agent_state_lock import project_state_lock, state_lock


CHECKPOINT_KINDS = ("initial", "pre_mutation", "post_mutation", "decision", "lifecycle", "stop")
PHASE_BY_KIND = {"initial": "scoped", "pre_mutation": "acting", "post_mutation": "acting"}
ACTIVE_CHECKPOINT_STATES = {"running", "resuming"}
EMPTY_WORK: dict[str, Any] = {
    "objective": "",
    "non_goals": [],
    "decisions": [],
    "changed_scope": [],
    "inspected_scope": [],
    "verification": [],
    "remaining_work": [],
    "blockers": [],
}


def write_continuation_checkpoint(
    *,
    project: Path,
    rules: Path,
    run_id: str,
    kind: str,
    binding_path: Path,
    work: dict[str, Any] | None = None,
    phase: str | None = None,
    mutation: dict[str, Any] | None = None,
    last_completed: str | None = None,
    finalize_completed: bool = False,
) -> dict[str, Any]:
    """Rewrite the whole packet for one checkpoint and return it.

    The packet is a snapshot, not a log: append-only history already belongs to
    the gate ledger. A failed rewrite raises and leaves the previous valid
    generation intact, so a mutating tool that waits for this call cannot run
    against a packet that was never written.
    """

    if kind not in CHECKPOINT_KINDS:
        raise ValueError(f"unsupported continuation checkpoint kind: {kind}")
    record = _owned_run(project, run_id)
    if finalize_completed and not (
        kind == "lifecycle"
        and phase == "done"
        and record.get("state") == "completed"
    ):
        raise ContinuationPacketError(
            [failure("invalid_completed_checkpoint", "/phase")]
        )
    base = _base_packet(project, run_id, kind)
    binding_payload = _binding_payload(project, run_id, binding_path)
    work_update = dict(work or {})
    if kind == "post_mutation":
        work_update = MutationCheckpointState.merge_changed_scope(
            project, run_id, base, work_update
        )
    drift = capture_drift_state(
        project,
        rules,
        str((base.get("drift") or {}).get("required_docs_sha256") or "")
        or required_docs_digest(binding_required_docs(binding_payload)),
    )
    packet = {
        "schema_version": CONTINUATION_SCHEMA_VERSION,
        "storage_class": STORAGE_CLASS,
        "run_id": run_id,
        "generation": 0 if kind == "initial" else int(base.get("generation", 0)) + 1,
        "phase": phase or PHASE_BY_KIND.get(kind) or str(base.get("phase") or "scoped"),
        "binding": binding_record(binding_path, binding_payload),
        "drift": drift,
        "work": {**(base.get("work") or EMPTY_WORK), **work_update},
        "checkpoint": {
            "last_completed": last_completed
            if last_completed is not None
            else (base.get("checkpoint") or {}).get("last_completed"),
            "first_unfinished": first_unfinished_checkpoint(
                binding_path, run_state=str(record.get("state") or "")
            ),
            "mutation_pending": _pending(kind, base, mutation, drift),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if kind == "post_mutation":
        MutationCheckpointState.reject_undeclared_paths(project, run_id, base, packet)
    baseline = MutationCheckpointState.capture(project) if kind == "pre_mutation" else None
    _write_owned_checkpoint(
        project,
        run_id,
        record,
        packet,
        baseline=baseline,
        expected_packet_generation=None
        if kind == "initial"
        else int(base.get("generation") or 0),
        finalize_completed=finalize_completed,
    )
    return packet


def first_unfinished_checkpoint(binding_path: Path, *, run_state: str = "") -> str | None:
    """Recompute the resumable checkpoint from the route and the gate ledger.

    The packet's cached value is display state only. Authority is the ordered
    gate manifest of the bound trust record plus the parent-owned ledger, so
    packet prose can never move a checkpoint, and an already recorded failure
    stays the checkpoint even when later dependent evidence exists.
    """

    payload = read_json_object(binding_path)
    route = payload.get("route") or {}
    gates = [str(gate) for gate in route.get("gates") or []]
    statuses = _latest_gate_statuses(binding_path, route)
    for gate in gates:
        if statuses.get(gate) != "SUCCESS":
            return gate
    return None if run_state == "completed" else "finish"


def binding_required_docs(binding_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the content-free required-document trust record of a binding."""

    snapshot = binding_payload.get("execution_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("required_docs"), list):
        return list(snapshot["required_docs"])
    if isinstance(binding_payload.get("required_docs"), list):
        return list(binding_payload["required_docs"])
    return []


def _base_packet(project: Path, run_id: str, kind: str) -> dict[str, Any]:
    """Return the packet this checkpoint rewrites, or nothing for the first one.

    Only the initial checkpoint may start from no packet. Every later kind
    requires a valid predecessor, so a corrupted or foreign packet cannot be
    silently replaced by a fresh one that claims the same run.
    """

    if kind == "initial":
        return {}
    result = read_continuation_packet(project, continuation_path(project, run_id))
    if result["status"] != "ok":
        raise ContinuationPacketError(
            result["failures"] or [failure("missing_packet", "")]
        )
    return result["packet"]


def _owned_run(project: Path, run_id: str) -> dict[str, Any]:
    """Refuse a rewrite from anything but the registry's current owner.

    An old owner that outlived its session, or a session whose run was taken
    over after its grace ceiling, must not overwrite the newer owner's packet.
    Ownership lives on the run record; the packet deliberately carries no owner
    field of its own.
    """

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = read_registry_state(path)
        record = next(
            (run for run in payload["runs"] if run.get("run_id") == run_id),
            None,
        )
    if record is None:
        raise ContinuationPacketError([failure("unknown_run", "/run_id")])
    if (record.get("owner") or {}) != (process_owner() or {}):
        raise ContinuationPacketError([failure("owner_changed", "/run_id")])
    return dict(record)


def _write_owned_checkpoint(
    project: Path,
    run_id: str,
    expected: dict[str, Any],
    packet: dict[str, Any],
    *,
    baseline: dict[str, str] | None,
    expected_packet_generation: int | None,
    finalize_completed: bool,
) -> None:
    """Compare owner/generation and replace the packet under one registry lock."""

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = read_registry_state(path)
        current = next((run for run in payload["runs"] if run.get("run_id") == run_id), None)
        if current is None:
            raise ContinuationPacketError([failure("unknown_run", "/run_id")])
        allowed_states = (
            {"completed"} if finalize_completed else ACTIVE_CHECKPOINT_STATES
        )
        if current.get("state") not in allowed_states:
            raise ContinuationPacketError([failure("run_not_active", "/run_id")])
        if (current.get("owner") or {}) != (expected.get("owner") or {}):
            raise ContinuationPacketError([failure("owner_changed", "/run_id")])
        if int(current.get("resume_generation") or 0) != int(
            expected.get("resume_generation") or 0
        ):
            raise ContinuationPacketError([failure("resume_generation_changed", "/run_id")])
        existing = read_continuation_packet(project, continuation_path(project, run_id))
        if expected_packet_generation is None:
            if existing["status"] == "ok":
                raise ContinuationPacketError(
                    [failure("checkpoint_generation_changed", "/generation")]
                )
        elif (
            existing["status"] != "ok"
            or int(existing["packet"].get("generation") or 0)
            != expected_packet_generation
        ):
            raise ContinuationPacketError(
                [failure("checkpoint_generation_changed", "/generation")]
            )
        baseline_path = MutationCheckpointState.path(project, run_id)
        if baseline is not None and not MutationCheckpointState.is_local(
            project, baseline_path
        ):
            raise ContinuationPacketError(
                [failure("mutation_baseline_not_git_ignored", "/checkpoint/mutation_pending")]
            )
        write_continuation_packet(project, packet)
        if baseline is not None:
            atomic_write_json(
                baseline_path,
                {"packet_generation": packet["generation"], "states": baseline},
            )
        if (packet.get("checkpoint") or {}).get("mutation_pending") is None:
            baseline_path.unlink(missing_ok=True)


def _binding_payload(project: Path, run_id: str, binding_path: Path) -> dict[str, Any]:
    if binding_path.resolve().parent != continuation_path(project, run_id).parent:
        raise ContinuationPacketError([failure("binding_outside_run", "/binding/filename")])
    payload = read_json_object(binding_path)
    if not payload or payload.get("invalid_json"):
        raise ContinuationPacketError([failure("unreadable_binding", "/binding")])
    return payload


def binding_record(binding_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Reference the content-free trust state one way, and only one way.

    The packet may point at the capsule or preflight snapshot so a moved
    binding can invalidate a resume. It never copies the route, request
    fingerprint, required-doc manifest, or gate order those records own.
    """

    if binding_path.name.endswith(CAPSULE_FILENAME):
        kind = "execution_capsule"
        fingerprint = execution_capsule_binding_fingerprint(payload)
    else:
        kind = "preflight_snapshot"
        fingerprint = preflight_snapshot_binding_fingerprint(payload.get("execution_snapshot") or {})
    if not fingerprint:
        raise ContinuationPacketError([failure("unbound_trust_record", "/binding/binding_sha256")])
    return {
        "kind": kind,
        "filename": binding_path.name,
        "file_sha256": sha256_file(binding_path),
        "binding_sha256": fingerprint,
    }


def _nothing_written_since(previous: dict[str, Any], drift: dict[str, Any]) -> bool:
    """True when the pending mutation's tool never reached the filesystem.

    A pending record is cleared by the post-mutation checkpoint, so anything
    that stops the tool between the two -- a declined permission prompt above
    all, but equally an aborted turn -- leaves it in place. Refusing every later
    mutation for that would make one declined prompt lock the session out of
    editing, with no in-band way back.

    The pending record carries the project and rules state it was written
    against, so "the tool never ran" is checkable rather than assumed: identical
    state means no bytes moved and this pending describes a mutation that did
    not happen. Superseding it is then the same conclusion resume already draws
    from the same evidence. Changed state is the opposite case and still raises,
    because those bytes need reconciliation, not a fresh pending on top.
    """
    return (
        previous.get("project") == drift["project"]
        and previous.get("rules") == drift["rules"]
    )


def _pending(
    kind: str,
    base: dict[str, Any],
    mutation: dict[str, Any] | None,
    drift: dict[str, Any],
) -> dict[str, Any] | None:
    previous = (base.get("checkpoint") or {}).get("mutation_pending")
    if kind == "post_mutation":
        if previous is None:
            raise ContinuationPacketError([failure("no_pending_mutation", "/checkpoint")])
        return None
    if kind != "pre_mutation":
        return previous
    if previous is not None and not _nothing_written_since(previous, drift):
        raise ContinuationPacketError(
            [failure("mutation_already_pending", "/checkpoint/mutation_pending")]
        )
    if not isinstance(mutation, dict):
        raise ContinuationPacketError([failure("missing_mutation", "/checkpoint/mutation_pending")])
    return {
        "kind": str(mutation.get("kind") or ""),
        "paths": list(mutation.get("paths") or []),
        "project": drift["project"],
        "rules": drift["rules"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def _latest_gate_statuses(binding_path: Path, route: dict[str, Any]) -> dict[str, str]:
    ledger = read_gate_evidence_ledger(gate_evidence_path_for_preflight(binding_path))
    if ledger.get("route_fingerprint") != route_fingerprint(route):
        # Evidence recorded against another route manifest proves nothing about
        # this one, so every gate reads as unfinished rather than inherited.
        return {}
    statuses: dict[str, str] = {}
    for entry in ledger.get("entries") or []:
        if isinstance(entry, dict) and entry.get("gate"):
            statuses[str(entry["gate"])] = str(entry.get("status") or "")
    return statuses
