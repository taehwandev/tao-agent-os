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
from agent_run_owner import (
    LIVE_OWNER_GRACE_MULTIPLIER,
    owner_death_is_proven,
    owner_is_gone,
    process_owner,
)
from agent_state_lock import project_state_lock, state_lock


SCHEMA_VERSION = 1
REGISTRY_FILENAME = "run-registry.json"
ACTIVE_RUN_STATES = frozenset({"running", "paused", "resuming"})
RUN_STATES = frozenset(
    {*ACTIVE_RUN_STATES, "failed", "completed", "cancelled", "reconcile_required"}
)
MAX_RUNS = 100


def registry_path(project: Path) -> Path:
    return project.resolve() / ".tao" / REGISTRY_FILENAME


def register_run(
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
    *,
    reuse_run_id: str | None = None,
) -> dict[str, Any]:
    """Register a new run without persisting request text or local paths.

    ``reuse_run_id`` is the only way to rebind an active record. Request
    identity does not prove caller identity, so a claim can be resumed solely by
    presenting the opaque id that claim returned.
    """

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        run, is_new = _register_locked(
            payload,
            project,
            evidence_path,
            route,
            request_intake,
            reuse_run_id=reuse_run_id,
        )
        _write_registry(path, payload)
    if is_new:
        _safe_event(project, "run.started", run_id=run["run_id"], state="running")
    return run


def claim_run(
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
    *,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Sweep, check and take an evidence path in one indivisible transaction.

    The old multi-lock sequence let concurrent starts both observe a free path.
    This transaction makes the decision and registration exclusive. The result
    includes the claimant, conflict, recovered runs, and preserved live holders.
    """

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        recovered, held = _sweep_stale_runs(
            payload,
            project,
            stale_after_seconds=stale_after_seconds,
            evidence_path=evidence_path,
        )
        conflict = _has_active_binding(
            payload,
            project,
            evidence_path,
        )
        run: dict[str, Any] | None = None
        is_new = False
        if not conflict:
            run, is_new = _register_locked(
                payload,
                project,
                evidence_path,
                route,
                request_intake,
                reuse_run_id=None,
            )
        if recovered or run is not None:
            _write_registry(path, payload)
    for item in recovered:
        _safe_event(project, "run.recovered", run_id=str(item["run_id"]), state="failed")
    if is_new and run is not None:
        _safe_event(project, "run.started", run_id=run["run_id"], state="running")
    return {"run": run, "conflict": conflict, "recovered": recovered, "held": held}


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
        return [run for run in payload["runs"] if run.get("state") in ACTIVE_RUN_STATES]


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

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        return _has_active_conflict(
            _read_registry(path),
            project,
            evidence_path,
            command=command,
            expected_request=request_fingerprint(request_intake),
        )


def touch_run(
    project: Path,
    evidence_path: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Refresh an active run's heartbeat without changing its state.

    ``updated_at`` was only written when a run was registered or transitioned,
    so a genuinely alive task that spent longer than the staleness window
    between those two points looked abandoned. Every lifecycle hook a working
    agent calls is proof of life and refreshes the timestamp here.
    """

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        candidates = [
            run
            for run in payload["runs"]
            if run.get("state") in ACTIVE_RUN_STATES
            and _matches_evidence(run, project, evidence_path)
            and (not run_id or run.get("run_id") == run_id)
        ]
        if not candidates:
            return None
        target = candidates[-1]
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    return target


def recover_stale_runs(
    project: Path,
    *,
    stale_after_seconds: int = 3600,
    evidence_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Fail abandoned active runs so a later invocation can recover them.

    ``evidence_path`` narrows the sweep to runs bound to that one evidence
    file. Start passes it so releasing the path it needs can never fail an
    unrelated concurrent run that simply has not reached its next hook yet.

    An old timestamp alone is not abandonment: a single long build legitimately
    outlives the window without reaching a hook. A run whose owning process is
    provably gone is failed at the normal window, and one that still looks
    owned only at the far longer grace ceiling, so slow work survives while an
    abandoned path always frees itself without anyone intervening.
    """

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        recovered, _held = _sweep_stale_runs(
            payload,
            project,
            stale_after_seconds=stale_after_seconds,
            evidence_path=evidence_path,
        )
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


def read_registry_state(path: Path) -> dict[str, Any]:
    """Read registry state for a caller already holding the registry locks.

    ``state_lock`` is not reentrant, so the continuation resume transaction --
    which must decide ownership and record it without releasing the lock in
    between -- cannot reach the registry through the public functions above.
    """

    return _read_registry(path)


def resume_holder_state(
    run: dict[str, Any],
    *,
    stale_after_seconds: int = 3600,
    now: datetime | None = None,
) -> str:
    """Classify a resume holder with the registry's shared stale-owner policy."""

    owner = run.get("owner")
    if owner_death_is_proven(owner):
        return "dead_proven"
    moment = now or datetime.now(timezone.utc)
    try:
        updated = datetime.fromisoformat(str(run.get("updated_at")))
    except (TypeError, ValueError):
        return "live" if not owner_is_gone(owner) else "unproven_wait"
    if updated >= moment - timedelta(seconds=stale_after_seconds):
        return "unproven_wait" if owner_is_gone(owner) else "live"
    ceiling = moment - timedelta(
        seconds=stale_after_seconds * LIVE_OWNER_GRACE_MULTIPLIER
    )
    return "live" if updated >= ceiling and not owner_is_gone(owner) else "unproven_expired"


def _register_locked(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
    *,
    reuse_run_id: str | None,
) -> tuple[dict[str, Any], bool]:
    """Add or rebind a run inside a lock the caller already holds.

    ``state_lock`` is not reentrant, so every step of a claim has to reach the
    registry through helpers like this one instead of calling the public
    functions that take the lock themselves.
    """

    run = _new_run(project, evidence_path, route, request_intake)
    if reuse_run_id:
        existing = _reusable_run(payload, project, evidence_path, reuse_run_id)
        if existing is not None:
            existing["route_fingerprint"] = run["route_fingerprint"]
            existing["state"] = "running"
            existing["updated_at"] = run["updated_at"]
            return existing, False
    payload["runs"].append(run)
    payload["runs"] = payload["runs"][-MAX_RUNS:]
    return run, True


def _new_run(
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": uuid.uuid4().hex,
        "project_id": _opaque_project_id(project),
        "evidence_name": evidence_path.name,
        "evidence_key": _evidence_key(project, evidence_path),
        "command": str(route.get("command") or "task"),
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "state": "running",
        "resume_generation": 0,
        "owner": process_owner(),
        "started_at": now,
        "updated_at": now,
    }


def _reusable_run(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
    reuse_run_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in reversed(payload["runs"])
            if item.get("state") in {"running", "paused"}
            and _matches_evidence(item, project, evidence_path)
            and item.get("run_id") == reuse_run_id
        ),
        None,
    )


def _has_active_conflict(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
    *,
    command: str,
    expected_request: str,
) -> bool:
    return any(
        run.get("state") in ACTIVE_RUN_STATES
        and _matches_evidence(run, project, evidence_path)
        and (
            run.get("command") != command
            or run.get("request_fingerprint") != expected_request
        )
        for run in payload["runs"]
    )


def _has_active_binding(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
) -> bool:
    """Return whether any active run already owns this exact evidence path.

    Fingerprints describe work identity, not claimant identity. Two independent
    starts for the same request still have separate processes that would race on
    one preflight file, so only an explicit opaque run-id rebind may reuse an
    active record.
    """

    return any(
        run.get("state") in ACTIVE_RUN_STATES
        and _matches_evidence(run, project, evidence_path)
        for run in payload["runs"]
    )


def _sweep_stale_runs(
    payload: dict[str, Any],
    project: Path,
    *,
    stale_after_seconds: int,
    evidence_path: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split silent runs into abandoned ones and ones a live owner still holds.

    A living owner extends the window it takes to declare a run abandoned; it
    never removes it. Past the grace ceiling the run is failed regardless, so a
    crashed agent whose owning process happens to outlive it cannot hold the
    shared evidence path forever. Proof of a dead owner needs no window at all;
    exclusive claims would otherwise strand an agent retrying its own request.
    """

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    recovered: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for run in payload["runs"]:
        if run.get("state") not in ACTIVE_RUN_STATES:
            continue
        if evidence_path is not None and not _matches_evidence(
            run, project, evidence_path
        ):
            continue
        holder = resume_holder_state(
            run,
            stale_after_seconds=stale_after_seconds,
            now=now,
        )
        if holder not in {"dead_proven", "unproven_expired"}:
            try:
                updated = datetime.fromisoformat(str(run["updated_at"]))
            except (KeyError, TypeError, ValueError):
                continue
            if holder == "live" and updated < cutoff:
                held.append(run)
            continue
        run["state"] = "failed"
        run["updated_at"] = now.isoformat()
        recovered.append(run)
    return recovered, held


def _read_registry(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("runs"), list):
        return {"schema_version": SCHEMA_VERSION, "runs": []}
    for run in payload["runs"]:
        if isinstance(run, dict):
            run.setdefault("resume_generation", 0)
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
