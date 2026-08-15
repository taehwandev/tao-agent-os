"""Content-free local registry for Tao Agent OS run lifecycle state."""

from __future__ import annotations

import hashlib
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_route_state import request_fingerprint, route_fingerprint
from agent_ipc import emit_event
from agent_run_owner import (
    LIVE_OWNER_GRACE_MULTIPLIER,
    is_recorded_owner,
    owner_death_is_proven,
    owner_is_gone,
    process_owner,
)
from agent_state_lock import project_state_lock, state_lock


SCHEMA_VERSION = 1
REGISTRY_FILENAME = "run-registry.json"
RUNS_DIR = "runs"
RUN_DIRECTORY_RE = re.compile(r"^[0-9a-f]{32}$")
ACTIVE_RUN_STATES = frozenset({"running", "paused", "resuming"})
CLAIMING_RUN_STATE = "claiming"
CLAIM_HOLDING_RUN_STATES = frozenset({*ACTIVE_RUN_STATES, CLAIMING_RUN_STATE})
RUN_STATES = frozenset(
    {
        *CLAIM_HOLDING_RUN_STATES,
        "failed",
        "completed",
        "cancelled",
        "reconcile_required",
    }
)
TRANSFER_CANCELLABLE_RUN_STATES = frozenset(
    {*ACTIVE_RUN_STATES, "failed", "reconcile_required"}
)
# States whose owner may still append gate evidence. Recovery happens after a
# run stops being active: a failed finish must be answered by recording the
# gates it named, and a repair cycle parks the run at reconcile_required for
# the same reason. A settled run must not gain new evidence, so completed and
# cancelled are excluded.
LEDGER_WRITABLE_RUN_STATES = frozenset(
    {*ACTIVE_RUN_STATES, CLAIMING_RUN_STATE, "failed", "reconcile_required"}
)
# The registry's shared stale window, repeated here as a name so the owner-less
# compatibility path is bounded by the same number the sweep uses.
DEFAULT_STALE_AFTER_SECONDS = 3600
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

    ``reuse_run_id`` is the only way to promote a transient claim. Request
    identity does not prove caller identity, so promotion requires both the
    opaque id and current-process owner recorded by that exact claim.
    """

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        run, started = _register_locked(
            payload,
            project,
            evidence_path,
            route,
            request_intake,
            reuse_run_id=reuse_run_id,
        )
        _write_registry(path, payload)
    if started:
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
        refresh = _refreshable_active_run(
            payload,
            project,
            evidence_path,
            command=str(route.get("command") or "task"),
            expected_request=request_fingerprint(request_intake),
        )
        conflict = refresh is None and _has_active_binding(
            payload,
            project,
            evidence_path,
        )
        run: dict[str, Any] | None = None
        is_new = False
        if refresh is not None:
            run = _claim_active_run_for_refresh(refresh)
            is_new = True
        elif not conflict:
            run, is_new = _register_locked(
                payload,
                project,
                evidence_path,
                route,
                request_intake,
                reuse_run_id=None,
                initial_state=CLAIMING_RUN_STATE,
            )
        if recovered or run is not None:
            _write_registry(path, payload)
    for item in recovered:
        _safe_event(project, "run.recovered", run_id=str(item["run_id"]), state="failed")
    if is_new and run is not None:
        _safe_event(project, "run.claimed", run_id=run["run_id"], state=CLAIMING_RUN_STATE)
    return {"run": run, "conflict": conflict, "recovered": recovered, "held": held}


def release_run_claim(
    project: Path,
    evidence_path: Path,
    run_id: str,
    *,
    restore_refresh: bool = True,
) -> dict[str, Any] | None:
    """Release a failed start claim, restoring a preflight refresh owner."""

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        target = _reusable_run(payload, project, evidence_path, run_id)
        if target is None:
            return None
        _require_current_process_claim_owner(target)
        previous_state = str(target.pop("refresh_previous_state", "") or "")
        previous_owner = target.pop("refresh_previous_owner", None)
        target.pop("claim_owner", None)
        if (
            restore_refresh
            and previous_state in ACTIVE_RUN_STATES
            and is_recorded_owner(previous_owner)
        ):
            target["state"] = previous_state
            target["owner"] = previous_owner
        else:
            target["state"] = "cancelled"
            target.pop("owner", None)
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=target["run_id"], state=target["state"])
    return target


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
    if state == CLAIMING_RUN_STATE:
        raise ValueError("claiming is a creation-only run state")
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
        if target.get("state") == CLAIMING_RUN_STATE:
            _require_current_process_claim_owner(target)
            if state in ACTIVE_RUN_STATES:
                raise ValueError(
                    "a transient claim can become runtime-active only through atomic promotion"
                )
        target["state"] = state
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=target["run_id"], state=state)
    return target


def cancel_run(
    project: Path,
    evidence_path: Path,
    *,
    run_id: str,
) -> dict[str, Any] | None:
    """Atomically settle one still-owned, non-terminal transferred run."""

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        candidates = [
            run
            for run in payload["runs"]
            if run.get("run_id") == run_id
            and _matches_evidence(run, project, evidence_path)
        ]
        if not candidates:
            return None
        target = candidates[-1]
        if (
            target.get("state") not in TRANSFER_CANCELLABLE_RUN_STATES
            or not _closeout_owner_matches(target)
        ):
            return None
        target["state"] = "cancelled"
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=run_id, state="cancelled")
    return target


def cancel_active_run_if_current(
    project: Path,
    evidence_path: Path,
    *,
    run_id: str,
    expected_resume_generation: int,
    expected_started_at: str,
) -> dict[str, Any] | None:
    """Cancel one exact active generation without overwriting a newer result.

    Session-level supersession first discovers candidates from a registry
    snapshot, then reads their evidence files. The run can finish or be rebound
    before that caller asks to cancel it, or a new run can adopt the terminal
    id. The run-instance, active-state, and generation checks therefore belong
    in the same registry transaction as the write.
    """

    if not run_id or not expected_started_at:
        return None
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        target = next(
            (
                run
                for run in payload["runs"]
                if run.get("run_id") == run_id
                and _matches_evidence(run, project, evidence_path)
            ),
            None,
        )
        if target is None:
            return None
        if target.get("state") not in ACTIVE_RUN_STATES:
            return None
        if int(target.get("resume_generation") or 0) != expected_resume_generation:
            return None
        if target.get("started_at") != expected_started_at:
            return None
        target["state"] = "cancelled"
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=run_id, state="cancelled")
    return target


# A pending closeout may revive the run that owes the work, and nothing else.
# Reviving from a settled state would resurrect a run that already reported its
# outcome, so only a run that is still active or that failed with work owed can
# come back. `claiming` is excluded because a transient claim becomes active
# only through atomic promotion.
RESUMABLE_FOR_CLOSEOUT_RUN_STATES = frozenset({*ACTIVE_RUN_STATES, "failed"})


def resume_run_for_closeout(
    project: Path,
    evidence_path: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an unsettled run to an active state so it can finish owed work.

    Unlike ``transition_run`` this refuses a settled run and a run owned by
    another process, so a late or replayed closeout cannot resurrect a run that
    already completed or hand one process's run to another.
    """

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
        if target.get("state") not in RESUMABLE_FOR_CLOSEOUT_RUN_STATES:
            return None
        if not _closeout_owner_matches(target):
            return None
        target["state"] = "resuming"
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_registry(path, payload)
    _safe_event(project, "run.transitioned", run_id=target["run_id"], state="resuming")
    return target


def _closeout_owner_matches(run: dict[str, Any]) -> bool:
    """Allow the revive only for the session that holds the run.

    ``owner`` records the session that registered the run, not the short-lived
    process running one hook, so this compares against the same identity
    ``register_run`` stored. An unrecorded owner is treated as a match so runs
    written before the field existed stay recoverable.
    """

    owner = run.get("owner")
    if not is_recorded_owner(owner):
        return True
    return owner == process_owner()


def active_runs(project: Path) -> list[dict[str, Any]]:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        return [run for run in payload["runs"] if run.get("state") in ACTIVE_RUN_STATES]


def active_run_bindings(project: Path) -> dict[str, dict[str, Any]]:
    """Return the latest active run for each content-free evidence key.

    Runtime evidence discovery may inspect several candidate files, but it must
    not reopen and rescan the registry once per candidate.  Build the exact
    latest-binding view under the registry lock once instead.  A newer terminal
    record suppresses an older active record for the same evidence path, which
    preserves ``latest_run_id`` semantics without exposing or persisting paths.
    A transient ``claiming`` record is intentionally absent: preflight has not
    committed its evidence yet, so publishing it as a runtime binding would let
    an interrupted start create a false active session or an ambiguous match.
    """

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        latest: dict[str, dict[str, Any]] = {}
        legacy_default = project.resolve() / ".tao" / "preflight.json"
        legacy_key = _evidence_key(project, legacy_default)
        for run in payload["runs"]:
            key = str(run.get("evidence_key") or "")
            if not key and run.get("evidence_name") == legacy_default.name:
                key = legacy_key
            if key:
                latest[key] = run
        return {
            key: run
            for key, run in latest.items()
            if run.get("state") in ACTIVE_RUN_STATES
        }


def evidence_binding_key(project: Path, evidence_path: Path) -> str:
    """Return the content-free registry key for one evidence candidate."""

    return _evidence_key(project, evidence_path)


def ledger_writable_run_claim_is_owned(
    project: Path,
    evidence_path: Path,
    run_id: str,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> bool:
    """Return whether the caller still owns an evidence claim it may append to.

    A preflight hash proves which bytes a ledger entry describes; it does not
    prove which live session may append the entry. When process-owner evidence
    exists, require the same launcher-anchored owner that won start's claim.

    Legacy or non-POSIX runs record no owner, and for them the only identity
    left is recency, so their compatibility path is bounded by the registry's
    shared stale window. That bound has to be applied, not merely described:
    admitting every owner-less run let a run silent for hours keep accepting
    ledger writes, which is the same unbounded hold the sweep exists to end. A
    run whose timestamp is missing or unparsable offers no recency evidence
    either, so it is treated as stale rather than trusted.

    Ownership, not liveness, is what this decides, so the writable set is wider
    than the active set. A failing finish transitions the run to ``failed`` and
    a repair cycle parks it at ``reconcile_required``, yet both states exist
    precisely so the owner can record the missing gate facts and rerun finish.
    Requiring an active state closed that door and left the documented recovery
    unreachable. ``completed`` and ``cancelled`` stay closed because a settled
    run must not gain new evidence.
    """

    path = registry_path(project)
    current_owner = process_owner()
    current_claim_owner = process_owner(current_process=True)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        return _ledger_writable_run_claim_is_owned_locked(
            payload,
            project,
            evidence_path,
            run_id,
            current_owner=current_owner,
            current_claim_owner=current_claim_owner,
            stale_after_seconds=stale_after_seconds,
        )


@contextmanager
def ledger_writable_run_claim_transaction(
    project: Path,
    evidence_path: Path,
    run_id: str,
    ledger_path: Path,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> Iterator[bool]:
    """Hold one claim decision stable through its ledger mutation.

    The global lock order for claimed gate evidence is:

    1. project state lock,
    2. run-registry file lock,
    3. gate-ledger file lock.

    Every registry mutation already uses the first two locks in that order.
    Taking the ledger lock last makes the ownership decision and the ledger
    write one transaction: a transition cannot settle or replace the run after
    validation but before its evidence bytes are durable. Registry-free ledger
    callers retain their ledger-only compatibility path in the caller.
    """

    path = registry_path(project)
    current_owner = process_owner()
    current_claim_owner = process_owner(current_process=True)
    with project_state_lock(project), state_lock(path), state_lock(ledger_path):
        payload = _read_registry(path)
        matches = [
            run
            for run in payload["runs"]
            if _matches_evidence(run, project, evidence_path)
        ]
        selected_run_id = run_id or (
            str(matches[-1].get("run_id") or "") if matches else ""
        )
        yield _ledger_writable_run_claim_is_owned_locked(
            payload,
            project,
            evidence_path,
            selected_run_id,
            current_owner=current_owner,
            current_claim_owner=current_claim_owner,
            stale_after_seconds=stale_after_seconds,
        )


def _ledger_writable_run_claim_is_owned_locked(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
    run_id: str,
    *,
    current_owner: dict[str, Any] | None,
    current_claim_owner: dict[str, Any] | None,
    stale_after_seconds: int,
) -> bool:
    """Validate one ledger claim while the caller holds the registry lock."""

    matches = [
        run
        for run in payload["runs"]
        if _matches_evidence(run, project, evidence_path)
    ]
    if not matches:
        return False
    target = matches[-1]
    if (
        target.get("run_id") != run_id
        or target.get("state") not in LEDGER_WRITABLE_RUN_STATES
    ):
        return False
    if target.get("state") == CLAIMING_RUN_STATE:
        recorded_owner = target.get("claim_owner")
        expected_owner = current_claim_owner
    else:
        recorded_owner = target.get("owner")
        expected_owner = current_owner
    if not isinstance(recorded_owner, dict) or not recorded_owner:
        return not _claim_recency_expired(
            target, stale_after_seconds=stale_after_seconds
        )
    return bool(expected_owner) and recorded_owner == expected_owner


def _claim_recency_expired(
    run: dict[str, Any],
    *,
    stale_after_seconds: int,
) -> bool:
    """Return whether an owner-less claim has outlived its compatibility window."""

    try:
        updated = datetime.fromisoformat(str(run.get("updated_at")))
    except (TypeError, ValueError):
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated < datetime.now(timezone.utc) - timedelta(
        seconds=stale_after_seconds
    )


def latest_run_id(project: Path, evidence_path: Path) -> str | None:
    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_registry(path)
        matches = [
            run for run in payload["runs"] if _matches_evidence(run, project, evidence_path)
        ]
        return str(matches[-1]["run_id"]) if matches and matches[-1].get("run_id") else None


def registered_run(
    project: Path,
    evidence_path: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Return a copy of one exact registry binding under the registry lock."""

    path = registry_path(project)
    with project_state_lock(project), state_lock(path):
        matches = [
            run
            for run in _read_registry(path)["runs"]
            if _matches_evidence(run, project, evidence_path)
            and (not run_id or run.get("run_id") == run_id)
        ]
        return dict(matches[-1]) if matches else None


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

    owner = (
        run.get("claim_owner")
        if run.get("state") == CLAIMING_RUN_STATE
        else run.get("owner")
    )
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
    initial_state: str = "running",
) -> tuple[dict[str, Any], bool]:
    """Add or rebind a run inside a lock the caller already holds.

    ``state_lock`` is not reentrant, so every step of a claim has to reach the
    registry through helpers like this one instead of calling the public
    functions that take the lock themselves.
    """

    if reuse_run_id:
        existing = _reusable_run(payload, project, evidence_path, reuse_run_id)
        if existing is None:
            raise ValueError("reuse_run_id does not identify the active transient claim")
        _require_current_process_claim_owner(existing)
    elif initial_state != CLAIMING_RUN_STATE and _has_transient_claim(
        payload, project, evidence_path
    ):
        raise ValueError("an active transient claim requires its reuse_run_id")

    run = _new_run(
        project,
        evidence_path,
        route,
        request_intake,
        run_id=_run_id_for(payload, project, evidence_path),
        state=initial_state,
    )
    if reuse_run_id:
        existing["command"] = run["command"]
        existing["route_fingerprint"] = run["route_fingerprint"]
        existing["request_fingerprint"] = run["request_fingerprint"]
        existing["state"] = "running"
        existing["owner"] = process_owner()
        existing.pop("claim_owner", None)
        existing.pop("refresh_previous_state", None)
        existing.pop("refresh_previous_owner", None)
        existing["updated_at"] = run["updated_at"]
        return existing, True
    # An adopted id can only come from a terminal record for the same isolated
    # evidence directory: that record's evidence file is about to be overwritten
    # in place, so it would describe a run whose evidence no longer exists.
    # Replacing it here keeps one record per id without deleting anything a
    # resolver still needs while the id is being chosen.
    payload["runs"] = [
        item for item in payload["runs"] if item.get("run_id") != run["run_id"]
    ]
    payload["runs"].append(run)
    payload["runs"] = payload["runs"][-MAX_RUNS:]
    return run, True


def _require_current_process_claim_owner(run: dict[str, Any]) -> None:
    """Reject mutation of a transient claim by any process but its creator."""

    if run.get("claim_owner") != process_owner(current_process=True):
        raise ValueError("transient claim is owned by another process")


def _has_transient_claim(
    payload: dict[str, Any], project: Path, evidence_path: Path
) -> bool:
    return any(
        item.get("state") == CLAIMING_RUN_STATE
        and _matches_evidence(item, project, evidence_path)
        for item in payload["runs"]
    )


def _run_id_for(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
) -> str:
    """Adopt an isolated-run evidence directory as this run's opaque id.

    A continuation packet lives at ``.tao/runs/<run-id>/continuation.json``,
    beside the trust record it binds to, so a run only has a reachable packet
    when the opaque directory the agent was told to isolate its evidence in *is*
    the run id. Adopting it costs nothing -- the directory name is already an
    opaque 32-hex token chosen per lifecycle -- and any other evidence path
    keeps a freshly minted id and simply has no packet.

    Only an *active* run blocks adoption. Two live records sharing one opaque id
    would make "the run" ambiguous for every later lookup, so that case still
    mints a fresh id. A terminal record must not block it: a ``start`` rejected
    after registering -- an unclear request, a failed route -- leaves its id
    behind, and refusing to adopt it again meant the obvious retry with the same
    isolated path silently minted a different id. The evidence then sat in the
    directory the agent chose while the registry pointed at one that was never
    written, so no lookup could resolve the run and every later edit was denied.

    The terminal record is left in place rather than dropped. Deleting it would
    also delete the record a later resolver traverses to account for this id,
    and the resolvers already read active state, so a superseded duplicate is
    inert where a missing record is not.
    """

    directory = evidence_path.resolve().parent
    name = directory.name
    if not (
        RUN_DIRECTORY_RE.match(name)
        and directory.parent == project.resolve() / ".tao" / RUNS_DIR
    ):
        return uuid.uuid4().hex
    if any(
        run.get("run_id") == name and run.get("state") in ACTIVE_RUN_STATES
        for run in payload["runs"]
    ):
        return uuid.uuid4().hex
    return name


def _new_run(
    project: Path,
    evidence_path: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
    *,
    run_id: str = "",
    state: str = "running",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": run_id or uuid.uuid4().hex,
        "project_id": _opaque_project_id(project),
        "evidence_name": evidence_path.name,
        "evidence_key": _evidence_key(project, evidence_path),
        "command": str(route.get("command") or "task"),
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "state": state,
        "resume_generation": 0,
        "started_at": now,
        "updated_at": now,
    }
    if state == CLAIMING_RUN_STATE:
        run["claim_owner"] = process_owner(current_process=True)
    else:
        run["owner"] = process_owner()
    return run


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
            if item.get("state") == CLAIMING_RUN_STATE
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
        run.get("state") in CLAIM_HOLDING_RUN_STATES
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
        run.get("state") in CLAIM_HOLDING_RUN_STATES
        and _matches_evidence(run, project, evidence_path)
        for run in payload["runs"]
    )


def _refreshable_active_run(
    payload: dict[str, Any],
    project: Path,
    evidence_path: Path,
    *,
    command: str,
    expected_request: str,
) -> dict[str, Any] | None:
    """Return the current owner's exact active run for preflight refresh."""

    owner = process_owner()
    if not is_recorded_owner(owner):
        return None
    return next(
        (
            run
            for run in reversed(payload["runs"])
            if run.get("state") in ACTIVE_RUN_STATES
            and _matches_evidence(run, project, evidence_path)
            and run.get("command") == command
            and run.get("request_fingerprint") == expected_request
            and run.get("owner") == owner
        ),
        None,
    )


def _claim_active_run_for_refresh(run: dict[str, Any]) -> dict[str, Any]:
    run["refresh_previous_state"] = run["state"]
    run["refresh_previous_owner"] = run["owner"]
    run["state"] = CLAIMING_RUN_STATE
    run["claim_owner"] = process_owner(current_process=True)
    run.pop("owner", None)
    run["updated_at"] = datetime.now(timezone.utc).isoformat()
    return run


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
        if run.get("state") not in CLAIM_HOLDING_RUN_STATES:
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
