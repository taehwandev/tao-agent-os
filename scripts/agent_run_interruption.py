"""Record a versioned turn boundary without claiming task completion."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent_continuation_checkpoint import binding_record
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_route_state import route_fingerprint
from agent_run_registry import (
    ACTIVE_RUN_STATES, evidence_binding_key, read_registry_state, registry_path,
)
from agent_runtime_session import resolve_runtime_evidence
from agent_state_lock import project_state_lock, state_lock


def record_turn_boundary(
    project: Path, runtime: str, session_id: str, evidence: Path | None = None,
) -> bool:
    """Handle v2/unknown Stop without continuation; return False for legacy.

    Read-only selection precedes locking so no-run and legacy stops create no
    state. The transaction rechecks the exact run instance and generation.
    No packet or finish receipt is authored, and failed writes permit turn end.
    """
    identity = {"runtime": runtime, "session_id": session_id}
    if not session_id or not runtime:
        return False
    project = project.resolve()
    path = registry_path(project)
    handled = False
    try:
        if evidence is not None:
            provided = read_json_object(evidence)
            marker = (provided.get("route") or {}).get("lifecycle_version", 1)
            handled = (
                provided.get("runtime_session") == identity
                and Path(str(provided.get("project") or "")).resolve() == project
                and not (type(marker) is int and marker == 1)
            )
        if not path.is_file():
            return handled
        evidence = evidence or resolve_runtime_evidence(project, identity)
        matches = _matches(project, read_registry_state(path), identity, evidence)
        handled = handled or bool(matches)
        if len(matches) != 1:
            return handled
        original, candidate, binding, version = matches[0]
        if type(version) is not int or version != 2:
            return True
        if original.get("state") not in ACTIVE_RUN_STATES:
            return True
        with project_state_lock(project), state_lock(path):
            registry = read_registry_state(path)
            current = _matches(project, registry, identity, candidate)
            if len(current) != 1:
                return True
            run, candidate, current_binding, current_version = current[0]
            if (
                type(current_version) is not int or current_version != 2
                or run.get("state") not in ACTIVE_RUN_STATES
                or any(run.get(key) != original.get(key) for key in (
                    "run_id", "started_at", "resume_generation", "route_fingerprint",
                ))
                or current_binding != binding
                or run.get("route_fingerprint") != route_fingerprint(binding["route"])
            ):
                return True
            run["state"] = _checkpoint_outcome(project, run, candidate, binding)
            run["updated_at"] = datetime.now(timezone.utc).isoformat()
            atomic_write_json(path, registry)
        return True
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return handled


def _matches(project: Path, registry: dict, identity: dict, evidence: Path | None) -> list:
    matches = []
    latest = {run.get("evidence_key"): run for run in registry["runs"]}
    for run in latest.values():
        if run.get("state") not in {*ACTIVE_RUN_STATES, "blocked", "interrupted"}:
            continue
        candidates = [evidence] if evidence else _retained_paths(project, run)
        for candidate in candidates:
            if candidate is None or evidence_binding_key(project, candidate) != run.get("evidence_key"):
                continue
            binding = read_json_object(candidate)
            if binding.get("runtime_session") != identity:
                continue
            if Path(str(binding.get("project") or "")).resolve() != project:
                continue
            version = (binding.get("route") or {}).get("lifecycle_version", 1)
            if type(version) is int and version == 1:
                continue
            matches.append((run, candidate, binding, version))
    return matches


def _retained_paths(project: Path, run: dict) -> list[Path]:
    run_id = str(run.get("run_id") or "")
    name = str(run.get("evidence_name") or "")
    if len(run_id) != 32 or any(ch not in "0123456789abcdef" for ch in run_id):
        return []
    if not name or Path(name).name != name:
        return []
    return [project / ".tao" / "runs" / run_id / name, project / ".tao" / name]


def _checkpoint_outcome(project: Path, run: dict, evidence: Path, binding: dict) -> str:
    path = continuation_path(project, run["run_id"])
    if not path.is_file():
        return "interrupted"
    result = read_continuation_packet(project, path)
    packet = result.get("packet") or {}
    if (
        result.get("status") == "ok"
        and packet.get("run_id") == run["run_id"]
        and packet.get("binding") == binding_record(evidence, binding)
        and packet.get("phase") == "blocked"
    ):
        return "blocked"
    return "interrupted"
