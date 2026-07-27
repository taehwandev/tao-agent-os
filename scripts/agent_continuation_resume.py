"""Discovery of unfinished continuation packets for one checkout.

``resume_list`` reports and never mutates: the registry is read without its lock
because every write is an atomic replace, so listing unfinished work is always
safe to run. ``resume_last`` resumes, which is what its name promises, and it
targets exactly one packet -- the newest. A blocked newest packet is refused by
name; it never falls through to an older task, because a caller asking for the
last thing they were doing has the least context in which to notice they were
handed something else. Every mutation still happens inside ``claim_resume``,
which remains the only owner of the takeover transaction.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import binding_required_docs, first_unfinished_checkpoint
from agent_continuation_claim import (
    FREE_HOLDER_STATES,
    TERMINAL_RUN_STATES,
    claim_resume,
    holder_state,
)
from agent_continuation_drift import verify_drift
from agent_continuation_store import (
    continuation_path,
    list_continuation_run_ids,
    read_continuation_packet,
)
from agent_execution_capsule_state import read_json_object
from agent_run_registry import read_registry_state, registry_path


DRIFT_LABELS = (
    ("head", "head_drift"),
    ("project_worktree", "worktree_drift"),
    ("rules_worktree", "worktree_drift"),
    ("required_docs", "required_doc_drift"),
)
UNRESUMABLE_STATUSES = ("invalid_packet", "local_boundary_failed")


def resume_list(
    project: Path,
    *,
    rules: Path | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Enumerate this checkout's unfinished packets, newest first.

    Only the selected project root is inspected. Another Git worktree has
    different mutable state and is not a candidate even when it shares object
    storage.
    """

    runs = {
        str(run.get("run_id")): run
        for run in read_registry_state(registry_path(project)).get("runs") or []
        if run.get("run_id")
    }
    entries = [
        _entry(project, rules, run_id, runs, stale_after_seconds)
        for run_id in sorted(set(list_continuation_run_ids(project)) | set(runs))
        if runs.get(run_id, {}).get("state") not in TERMINAL_RUN_STATES
    ]
    entries.sort(key=lambda entry: entry["updated_at"], reverse=True)
    return {"result": "ok", "entries": entries}


def resume_last(
    project: Path,
    *,
    rules: Path | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Resume the newest unfinished packet for this checkout, or refuse by name.

    Exactly one packet is ever a candidate. If it is held, unproven, drifted, or
    invalid, that is the answer; an older task is never substituted for the one
    the caller asked for. Owner policy and drift are decided inside
    ``claim_resume`` so one transaction owns every stable result code.
    """

    entries = resume_list(project, rules=rules, stale_after_seconds=stale_after_seconds)["entries"]
    if not entries:
        return _result("not_found", {}, reason="no_unfinished_packet")
    newest = entries[0]
    if newest["status"] in UNRESUMABLE_STATUSES:
        return _result(newest["status"], newest, reason=newest["status"])
    if newest["status"] != "ok":
        # A packet-less registry entry is recovered by a fresh start, and it
        # still occupies the newest slot rather than yielding it to an older run.
        return _result("not_found", newest, reason=newest["status"])
    if newest["first_unfinished"] is None:
        return _result("not_found", newest, reason="already_finished")
    packet, binding_path, drift = _verified(project, rules, newest["run_id"])
    if packet is None:
        return _result("invalid_packet", newest, reason="invalid_packet")
    claim = claim_resume(
        project,
        newest["run_id"],
        expected_generation=newest["resume_generation"],
        drift=drift,
        stale_after_seconds=stale_after_seconds,
    )
    return _claimed(claim, newest, binding_path)


def _claimed(
    claim: dict[str, Any],
    entry: dict[str, Any],
    binding_path: Path,
) -> dict[str, Any]:
    ready = claim["result"] == "ready"
    return _result(
        claim["result"],
        entry,
        reason="" if ready else claim["result"],
        evidence_path=str(binding_path),
        resume_generation=claim["resume_generation"],
        holder_state=claim["holder_state"] or entry["holder_state"],
        changed_signals=claim["changed_signals"],
        affected_paths=claim["affected_paths"],
        # A refusal returns no semantic work object and no checkpoint to
        # resume from; only a completed claim does.
        work=claim["packet"]["work"] if ready else None,
        checkpoint=entry["first_unfinished"] if ready else None,
    )


def _result(result: str, entry: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result": result,
        "reason": "",
        "run_id": entry.get("run_id", ""),
        "evidence_path": "",
        "route_command": entry.get("route_command", ""),
        "resume_generation": None,
        "checkpoint": None,
        "work": None,
        "holder_state": entry.get("holder_state", ""),
        "changed_signals": entry.get("changed_signals", []),
        "affected_paths": entry.get("affected_paths", []),
    }
    payload.update(overrides)
    return payload


def _verified(
    project: Path,
    rules: Path | None,
    run_id: str,
) -> tuple[dict[str, Any] | None, Path, dict[str, Any]]:
    """Re-verify drift immediately before the claim that will be bound to it.

    The listing already reported a verdict, but that one was measured for
    display. Measuring again here keeps the window between the strong capture
    and the resume compare-and-swap as narrow as this design allows.
    """

    binding_path = continuation_path(project, run_id)
    result = read_continuation_packet(project, binding_path)
    if result["status"] != "ok":
        return None, binding_path, {"status": "drift_refused"}
    packet = result["packet"]
    binding_path = binding_path.parent / packet["binding"]["filename"]
    binding = read_json_object(binding_path)
    return packet, binding_path, verify_drift(
        project,
        _rules_root(binding, rules, project),
        packet,
        required_doc_records=binding_required_docs(binding),
    )


def _entry(
    project: Path,
    rules: Path | None,
    run_id: str,
    runs: dict[str, dict[str, Any]],
    stale_after_seconds: int,
) -> dict[str, Any]:
    run = runs.get(run_id) or {}
    state = holder_state(run, stale_after_seconds=stale_after_seconds) if run else "dead_proven"
    entry: dict[str, Any] = {
        "run_id": run_id,
        "status": "legacy_no_packet" if run else "unknown_run",
        "route_command": str(run.get("command") or ""),
        "objective": "",
        "updated_at": str(run.get("updated_at") or ""),
        "first_unfinished": None,
        "drift": "",
        "changed_signals": [],
        "affected_paths": [],
        "pending": None,
        "holder_state": state,
        "holder": _holder(state),
        "resume_generation": int(run.get("resume_generation") or 0),
        "run_state": str(run.get("state") or ""),
    }
    result = read_continuation_packet(project, continuation_path(project, run_id))
    if result["status"] == "not_found":
        return entry
    if result["status"] != "ok":
        # An invalid packet is listed by opaque run id; its prose is never read.
        entry["status"] = result["status"]
        entry["failures"] = result["failures"]
        return entry
    return _packet_entry(project, rules, entry, result["packet"])


def _packet_entry(
    project: Path,
    rules: Path | None,
    entry: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    binding_path = continuation_path(project, entry["run_id"]).parent / packet["binding"]["filename"]
    binding = read_json_object(binding_path)
    drift = verify_drift(
        project,
        _rules_root(binding, rules, project),
        packet,
        required_doc_records=binding_required_docs(binding),
    )
    entry.update(
        {
            "status": "ok",
            "objective": packet["work"]["objective"],
            "updated_at": _latest(packet["updated_at"], entry["updated_at"]),
            "route_command": str((binding.get("route") or {}).get("command") or entry["route_command"]),
            "first_unfinished": first_unfinished_checkpoint(
                binding_path, run_state=entry["run_state"]
            ),
            "drift": _drift_label(drift["changed_signals"]),
            "changed_signals": drift["changed_signals"],
            "affected_paths": drift["affected_paths"],
            "pending": drift["pending_state"],
            "phase": packet["phase"],
        }
    )
    return entry


def _latest(*values: str) -> str:
    """Return the most recent evidence that a run was active.

    A packet that cannot be read has no snapshot time of its own, so ordering
    would fall back to its registry heartbeat alone. Taking the later of the two
    for readable packets keeps a stale heartbeat from demoting a fresh packet
    below an older run -- which would hand the caller an older task by exactly
    the silent substitution ``resume_last`` exists to refuse.
    """

    moments = []
    for value in values:
        try:
            moments.append((datetime.fromisoformat(str(value).replace("Z", "+00:00")), value))
        except ValueError:
            continue
    return max(moments)[1] if moments else ""


def _rules_root(binding: dict[str, Any], rules: Path | None, project: Path) -> Path:
    """Resolve the rules root this run was started against, not a guessed one."""

    if binding.get("rules"):
        return Path(str(binding["rules"]))
    return rules or project


def _drift_label(signals: list[str]) -> str:
    for signal, label in DRIFT_LABELS:
        if signal in signals:
            return label
    return "drift_refused" if signals else "clean"


def _holder(state: str) -> str:
    if state in FREE_HOLDER_STATES:
        return "free"
    return "unproven" if state == "unproven_wait" else "held"
