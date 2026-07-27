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
    base = _base_packet(project, run_id, kind)
    binding_payload = _binding_payload(project, run_id, binding_path)
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
        "work": {**(base.get("work") or EMPTY_WORK), **(work or {})},
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
        _reject_undeclared_paths(base, packet)
    write_continuation_packet(project, packet)
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
    return record


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
    if not isinstance(mutation, dict):
        raise ContinuationPacketError([failure("missing_mutation", "/checkpoint/mutation_pending")])
    return {
        "kind": str(mutation.get("kind") or ""),
        "paths": list(mutation.get("paths") or []),
        "project": drift["project"],
        "rules": drift["rules"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def _reject_undeclared_paths(base: dict[str, Any], packet: dict[str, Any]) -> None:
    """Fail the post-mutation checkpoint on any path the batch never declared."""

    declared = set((base.get("checkpoint") or {}).get("mutation_pending", {}).get("paths") or [])
    known = _scope_paths((base.get("work") or {}).get("changed_scope") or [])
    for index, path in enumerate(_scope_paths((packet.get("work") or {}).get("changed_scope") or [])):
        if path not in known and path not in declared:
            raise ContinuationPacketError(
                [failure("undeclared_changed_path", f"/work/changed_scope/{index}")]
            )


def _scope_paths(records: Any) -> list[str]:
    paths: list[str] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        paths.extend(str(record[key]) for key in ("path", "from", "to") if record.get(key))
    return paths


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
