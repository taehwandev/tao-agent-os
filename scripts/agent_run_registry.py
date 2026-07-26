"""Content-free local registry for Tao Agent OS run lifecycle state."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_route_state import request_fingerprint, route_fingerprint
from agent_ipc import emit_event
from agent_state_lock import project_state_lock, state_lock


SCHEMA_VERSION = 1
REGISTRY_FILENAME = "run-registry.json"
RUN_STATES = frozenset({"running", "paused", "failed", "completed", "cancelled"})
MAX_RUNS = 100


def registry_path(project: Path) -> Path:
    return project.resolve() / ".tao" / REGISTRY_FILENAME


def register_run(
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
    *,
    reuse_active: bool = False,
) -> dict[str, Any]:
    """Register a new run without persisting request text or local paths."""

    now = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": uuid.uuid4().hex,
        "project_id": _opaque_project_id(project),
        "evidence_name": evidence_path.name,
        "evidence_key": _evidence_key(project, evidence_path),
        "command": str(route.get("command") or "task"),
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "state": "running",
        "started_at": now,
        "updated_at": now,
    }
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        if reuse_active:
            existing = next(
                (
                    item
                    for item in reversed(payload["runs"])
                    if item.get("state") in {"running", "paused"}
                    and _matches_evidence(item, project, evidence_path)
                    and item.get("command") == run["command"]
                    and item.get("request_fingerprint") == run["request_fingerprint"]
                ),
                None,
            )
            if existing is not None:
                existing["route_fingerprint"] = run["route_fingerprint"]
                existing["state"] = "running"
                existing["updated_at"] = now
                _write_registry(path, payload)
                return existing
        payload["runs"].append(run)
        payload["runs"] = payload["runs"][-MAX_RUNS:]
        _write_registry(path, payload)
    _safe_event(project, "run.started", run_id=run["run_id"], state="running")
    return run


def transition_run(
    project: Path,
    evidence_path: Path,
    state: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Transition a run by opaque ID, falling back to newest evidence binding."""

    if state not in RUN_STATES:
        raise ValueError(f"unsupported run state: {state}")
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        candidates = [
            run for run in payload["runs"] if _matches_evidence(run, project, evidence_path)
        ]
        if run_id:
            candidates = [run for run in candidates if run.get("run_id") == run_id]
        if not candidates:
            return None
        target = candidates[-1]
        target["state"] = state
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=target["run_id"], state=state)
    return target


def active_runs(project: Path) -> list[dict[str, Any]]:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        return [run for run in payload["runs"] if run.get("state") in {"running", "paused"}]


def latest_run_id(project: Path, evidence_path: Path) -> str | None:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        matches = [
            run for run in payload["runs"] if _matches_evidence(run, project, evidence_path)
        ]
        return str(matches[-1]["run_id"]) if matches and matches[-1].get("run_id") else None


def active_run_conflict(
    project: Path,
    evidence_path: Path,
    *,
    command: str,
    request_intake: dict[str, Any] | None,
) -> bool:
    """Reject overwriting active evidence that belongs to another request."""

    expected_request = request_fingerprint(request_intake)
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        return any(
            run.get("state") in {"running", "paused"}
            and _matches_evidence(run, project, evidence_path)
            and (
                run.get("command") != command
                or run.get("request_fingerprint") != expected_request
            )
            for run in payload["runs"]
        )


def recover_stale_runs(project: Path, *, stale_after_seconds: int = 3600) -> list[dict[str, Any]]:
    """Fail stale active runs so a later scheduler invocation can recover them."""

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        recovered: list[dict[str, Any]] = []
        for run in payload["runs"]:
            if run.get("state") not in {"running", "paused"}:
                continue
            try:
                updated = datetime.fromisoformat(str(run["updated_at"]))
            except (KeyError, TypeError, ValueError):
                continue
            if updated < cutoff:
                run["state"] = "failed"
                run["updated_at"] = datetime.now(timezone.utc).isoformat()
                recovered.append(run)
        if recovered:
            _write_registry(path, payload)
    for run in recovered:
        _safe_event(project, "run.recovered", run_id=str(run["run_id"]), state="failed")
    return recovered


def resume_run(project: Path, run_id: str) -> dict[str, Any] | None:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        for run in payload["runs"]:
            if run.get("run_id") == run_id and run.get("state") in {"failed", "paused"}:
                run["state"] = "running"
                run["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_registry(path, payload)
                break
        else:
            return None
    _safe_event(project, "run.resumed", run_id=run_id, state="running")
    return run


def _read_registry(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("runs"), list):
        return {"schema_version": SCHEMA_VERSION, "runs": []}
    return payload


def _write_registry(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _opaque_project_id(project: Path) -> str:
    return hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()


def _evidence_key(project: Path, evidence_path: Path) -> str:
    try:
        value = evidence_path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        value = str(evidence_path.resolve())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _matches_evidence(run: dict[str, Any], project: Path, evidence_path: Path) -> bool:
    key = str(run.get("evidence_key") or "")
    if key:
        return key == _evidence_key(project, evidence_path)
    legacy_default = project.resolve() / ".tao" / "preflight.json"
    return (
        evidence_path.resolve() == legacy_default
        and run.get("evidence_name") == evidence_path.name
    )


def _safe_event(project: Path, event_type: str, *, run_id: str, state: str) -> None:
    try:
        emit_event(project, event_type, run_id=run_id, state=state)
    except (OSError, ValueError):
        return
