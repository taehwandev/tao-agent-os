"""Bounded local retention policy for Tao Agent OS runtime state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_ipc import events_path
from agent_run_registry import SETTLED_RUN_STATES, registry_path
from agent_scheduler import scheduler_path
from agent_state_lock import project_state_lock, state_lock


# Scheduler tasks end in any of these. Runs do not: a `failed` run is one a
# later session recovers, and pruning its record while its directory stayed
# left a packet nothing could settle. A run record is pruned only once it is
# settled, which is what the run-evidence policy also calls finished.
TERMINAL_STATES = {"completed", "failed", "cancelled"}
RUN_TERMINAL_STATES = frozenset(SETTLED_RUN_STATES)


def prune_runtime_state(
    project: Path,
    *,
    retention_seconds: int = 30 * 24 * 60 * 60,
    max_records: int = 100,
    apply: bool = True,
    assume_settled: Iterable[str] = (),
    protected_runs: Iterable[str] = (),
) -> dict[str, int]:
    """Prune old terminal records; with ``apply`` false only count them.

    ``assume_settled`` lets a report count run records a settlement pass in the
    same maintenance run would have settled first; ``protected_runs`` names run
    records kept whatever their age (a live owner active moments ago). A report
    takes no lock and writes nothing, so it creates nothing in the checkout it
    inspects.
    """

    if retention_seconds < 1 or max_records < 1:
        raise ValueError("retention_seconds and max_records must be positive")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)
    settled = frozenset(assume_settled)
    held = frozenset(protected_runs)
    targets = (
        (registry_path(project), "runs", RUN_TERMINAL_STATES),
        (scheduler_path(project), "tasks", TERMINAL_STATES),
        (events_path(project), "events", TERMINAL_STATES),
    )
    if not apply:
        return {
            key: _prune_file(path, key, cutoff, max_records, terminal, settled, held, apply=False)
            for path, key, terminal in targets
        }
    with project_state_lock(project):
        return {
            key: _prune_file(path, key, cutoff, max_records, terminal, settled, held, apply=True)
            for path, key, terminal in targets
        }


def _prune_file(
    path: Path,
    key: str,
    cutoff: datetime,
    max_records: int,
    terminal_states: frozenset[str] | set[str],
    assume_settled: frozenset[str],
    held: frozenset[str],
    *,
    apply: bool,
) -> int:
    if not apply:
        return _plan_prune(
            read_json_object(path), key, cutoff, max_records, terminal_states, assume_settled, held
        )[0]
    with state_lock(path):
        payload = read_json_object(path)
        removed, kept = _plan_prune(
            payload, key, cutoff, max_records, terminal_states, assume_settled, held
        )
        if removed:
            payload[key] = kept
            atomic_write_json(path, payload)
        return removed


def _plan_prune(
    payload: dict,
    key: str,
    cutoff: datetime,
    max_records: int,
    terminal_states: frozenset[str] | set[str],
    assume_settled: frozenset[str],
    held: frozenset[str],
) -> tuple[int, list]:
    records = payload.get(key)
    if not isinstance(records, list):
        return 0, []
    active_indexes: list[int] = []
    terminal_indexes: list[int] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if key == "events":
            terminal = True
            timestamp = record.get("created_at")
        else:
            terminal = record.get("state") in terminal_states or (
                key == "runs" and str(record.get("run_id") or "") in assume_settled
            )
            timestamp = record.get("updated_at") or record.get("queued_at")
            if key == "runs" and str(record.get("run_id") or "") in held:
                terminal = False
        try:
            old = datetime.fromisoformat(str(timestamp))
        except (TypeError, ValueError):
            old = datetime.now(timezone.utc)
        if old.tzinfo is None:
            old = old.replace(tzinfo=timezone.utc)
        if not terminal:
            active_indexes.append(index)
        elif old >= cutoff:
            terminal_indexes.append(index)
    # max_records bounds retained terminal history only; active state is never
    # discarded merely because the history limit was reached.
    keep_indexes = set(active_indexes + terminal_indexes[-max_records:])
    kept = [record for index, record in enumerate(records) if index in keep_indexes]
    return len(records) - len(kept), kept
