"""Validate exact task continuation bindings; messages never supply authority.

Owner: mailbox task authorization and Stop eligibility checks.
Allowed imports: stdlib, existing capsule/session/packet validators.
Forbidden imports: provider clients, execution, credentials, prompt classifiers.
Callers/tests: agent_mailbox_task; test_agent_mailbox_task.
Verification: stale, foreign, read-only and pending-decision cases fail closed.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_execution_capsule import capsule_path_for_evidence, read_execution_capsule, validate_execution_capsule
from agent_execution_capsule_state import read_json_object
from agent_mailbox_store import _expired, _validate_packet, _require_local_path
from agent_route_state import request_fingerprint
from agent_run_registry import ACTIVE_RUN_STATES, registered_run
from agent_runtime_session import is_run_local_continuation_evidence, resolve_runtime_evidence, same_runtime_session
from support.global_state import global_state_dir
from workflow_effect_policy import route_minimum_effect

__all__ = []  # Internal predicates for the task queue, not an extension API.

def task_binding(project: Path, identity: dict, evidence: Path) -> dict:
    _require_local_path(project, evidence)
    evidence = evidence.resolve()
    relative = evidence.relative_to(project / ".tao/runs")
    if len(relative.parts) != 2 or resolve_runtime_evidence(project, identity) != evidence:
        raise ValueError("task continuation needs this session's active run")
    preflight = read_json_object(evidence)
    route = preflight.get("route") or {}
    envelope = (route.get("request_classification") or {}).get("intent_envelope") or {}
    if (preflight.get("execution_mode", {}).get("read_only") or route_minimum_effect(route.get("command", "")) == "read"
            or not envelope.get("schema_valid") or not envelope.get("envelope_present")
            or envelope.get("failures") or envelope.get("effective_effect") not in
            {"local_write", "git_write", "external_write", "destructive"}):
        raise ValueError("task continuation needs an admitted writable scope")
    capsule_path = capsule_path_for_evidence(evidence)
    _require_local_path(project, capsule_path)
    capsule = read_execution_capsule(capsule_path)
    if validate_execution_capsule(capsule, project, Path(preflight["rules"]), evidence, route):
        raise ValueError("task continuation capsule is invalid")
    return {"evidence": relative.as_posix(), "request": request_fingerprint(preflight.get("request_intake") or {}),
            "capsule": hashlib.sha256(capsule_path.read_bytes()).hexdigest()}


def validate_task(project: Path, identity: dict, packet: dict, binding: dict) -> None:
    run_id = str(packet.get("source_run_id") or "")
    _validate_packet(packet, project, run_id, identity["runtime"], str(packet.get("message_id") or ""))
    if packet["kind"] != "task" or _expired(packet, datetime.now(timezone.utc)):
        raise ValueError("only a live execution-bound task can continue")
    source = project / ".tao/runs" / run_id / "preflight.json"
    _require_local_path(project, source)
    _require_local_path(project, capsule_path_for_evidence(source))
    expected = hashlib.sha256(f"{run_id}/preflight.json".encode()).hexdigest()
    preflight = read_json_object(source)
    if (packet["evidence_fingerprint"] != expected
            or request_fingerprint(preflight.get("request_intake") or {}) != binding["request"]):
        raise ValueError("message is outside the current authorized request")
    if validate_execution_capsule(read_execution_capsule(capsule_path_for_evidence(source)), project,
                                  Path(preflight["rules"]), source, preflight["route"]):
        raise ValueError("message source capsule is invalid")


def validate_completion_binding(project: Path, identity: dict, binding: dict) -> None:
    """Validate a receipt against its enrolled run, without resuming that run."""
    relative = Path(str(binding.get("evidence") or ""))
    evidence = project / ".tao/runs" / relative
    if (relative.is_absolute() or evidence.name != "preflight.json"
            or not is_run_local_continuation_evidence(project, evidence)):
        raise ValueError("task completion needs a valid run-local evidence binding")
    _require_local_path(project, evidence)
    run = registered_run(project, evidence)
    if run is None or run.get("run_id") != evidence.parent.name:
        raise ValueError("task completion bound run is missing")
    if run.get("state") not in {*ACTIVE_RUN_STATES, "interrupted", "completed"}:
        raise ValueError(f"task completion unavailable for bound run state: {run.get('state')}")
    preflight = read_json_object(evidence)
    if Path(str(preflight.get("project") or "")).resolve() != project.resolve():
        raise ValueError("task completion project binding has changed")
    if not same_runtime_session(preflight.get("runtime_session"), identity,
                                resume_generation=int(run.get("resume_generation") or 0)):
        raise ValueError("task completion session binding is missing or stale")
    if (request_fingerprint(preflight.get("request_intake") or {}) != binding.get("request")
            or run.get("request_fingerprint") != binding.get("request")):
        raise ValueError("task completion request binding has changed")


def stop_ready(payload: dict, identity: dict, project: Path) -> bool:
    if payload.get("stop_hook_active") or any(payload.get(key) for key in
            ("user_interrupted", "interrupted", "approval_pending", "waiting_for_approval")):
        return False
    if payload.get("stop_reason") not in (None, "", "end_turn", "completed"):
        return False
    evidence = resolve_runtime_evidence(project, identity)
    if evidence is None:
        return False
    from agent_continuation_store import continuation_path, read_continuation_packet
    packet = read_continuation_packet(project, continuation_path(project, evidence.parent.name)).get("packet") or {}
    if (packet.get("phase") == "blocked" or (packet.get("work") or {}).get("blockers")
            or (packet.get("checkpoint") or {}).get("mutation_pending") is not None):
        return False
    directory = global_state_dir() / "codex-operator-review"
    paths = list(directory.glob("*.json")) if directory.exists() else []
    if len(paths) > 128:
        return False
    return not any(record.get("session_id") == identity["session_id"] and record.get("status") == "pending"
                   and record.get("expires_at", 0) > time.time()
                   for record in (read_json_object(path) for path in paths))
