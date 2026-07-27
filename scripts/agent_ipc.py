"""Content-free local IPC/event channel shared by Tao Agent OS layers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_outbound import assert_no_continuation_outbound
from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_state_lock import project_state_lock, state_lock


SCHEMA_VERSION = 1
EVENTS_FILENAME = "events.json"
MAX_EVENTS = 500
SAFE_ENUM = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SAFE_OPAQUE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def events_path(project: Path) -> Path:
    return project.resolve() / ".tao" / EVENTS_FILENAME


def emit_event(
    project: Path,
    event_type: str,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    state: str | None = None,
    worker_id: str | None = None,
    result_id: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    for label, value in (("event_type", event_type), ("state", state)):
        if value is not None and not SAFE_ENUM.fullmatch(value):
            raise ValueError(f"{label} must be a safe enum")
    for label, value in (("worker_id", worker_id), ("result_id", result_id)):
        if value is not None and not SAFE_OPAQUE.fullmatch(value):
            raise ValueError(f"{label} must be an opaque identifier")
    if attempt is not None and (not isinstance(attempt, int) or attempt < 1):
        raise ValueError("attempt must be a positive integer")
    event = {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "run_id": run_id,
        "task_id": task_id,
        "state": state,
        "worker_id": worker_id,
        "result_id": result_id,
        "attempt": attempt,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    assert_no_continuation_outbound(event, boundary="ipc")
    assert_no_continuation_outbound(event, boundary="telemetry")
    path = events_path(project)
    with project_state_lock(project), state_lock(path):
        payload = read_json_object(path)
        events = payload.get("events") if payload.get("schema_version") == SCHEMA_VERSION else []
        if not isinstance(events, list):
            events = []
        events.append(event)
        atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "events": events[-MAX_EVENTS:]})
    return event


def emit_heartbeat(project: Path, *, run_id: str, task_id: str, worker_id: str, attempt: int = 1) -> dict[str, Any]:
    return emit_event(project, "worker.heartbeat", run_id=run_id, task_id=task_id, state="running", worker_id=worker_id, attempt=attempt)


def emit_worker_result(project: Path, *, run_id: str, task_id: str, worker_id: str, result_id: str, attempt: int = 1) -> dict[str, Any]:
    return emit_event(project, "worker.result", run_id=run_id, task_id=task_id, state="completed", worker_id=worker_id, result_id=result_id, attempt=attempt)


def emit_worker_failure(project: Path, *, run_id: str, task_id: str, worker_id: str, attempt: int = 1) -> dict[str, Any]:
    return emit_event(project, "worker.failure", run_id=run_id, task_id=task_id, state="failed", worker_id=worker_id, attempt=attempt)


def emit_partial_result(project: Path, *, run_id: str, task_id: str, worker_id: str, result_id: str, attempt: int = 1) -> dict[str, Any]:
    return emit_event(project, "worker.partial", run_id=run_id, task_id=task_id, state="paused", worker_id=worker_id, result_id=result_id, attempt=attempt)


def read_events(project: Path, *, event_type: str | None = None) -> list[dict[str, Any]]:
    path = events_path(project)
    with project_state_lock(project), state_lock(path):
        payload = read_json_object(path)
    events = payload.get("events") if payload.get("schema_version") == SCHEMA_VERSION else []
    if not isinstance(events, list):
        return []
    if event_type is None:
        return [event for event in events if isinstance(event, dict)]
    return [event for event in events if isinstance(event, dict) and event.get("event_type") == event_type]


def summarize_events(project: Path) -> dict[str, int]:
    summary: dict[str, int] = {}
    for event in read_events(project):
        event_type = str(event.get("event_type") or "unknown")
        summary[event_type] = summary.get(event_type, 0) + 1
    return summary
