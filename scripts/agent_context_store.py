"""Local Context File System snapshot for route-required documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_docs import current_required_docs, required_doc_failures
from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_route_state import request_fingerprint, route_fingerprint
from agent_state_lock import project_state_lock, state_lock


SCHEMA_VERSION = 2
CONTEXT_FILENAME = "context-snapshot.json"

_REPLACEABLE_CONTEXT_FAILURES = {
    "context snapshot route fingerprint does not match",
    "context snapshot request fingerprint does not match",
    "execution capsule required-doc manifest does not match",
}
_REPLACEABLE_REQUIRED_DOC_FAILURE_PREFIXES = (
    "execution capsule required doc size changed: ",
    "execution capsule required doc hash changed: ",
)


def context_snapshot_path(project: Path) -> Path:
    return project.resolve() / ".tao" / CONTEXT_FILENAME


def context_snapshot_failures_are_replaceable(failures: list[str]) -> bool:
    """Return whether a fresh start may safely replace the prior snapshot."""

    return bool(failures) and all(
        failure in _REPLACEABLE_CONTEXT_FAILURES
        or failure.startswith(_REPLACEABLE_REQUIRED_DOC_FAILURE_PREFIXES)
        for failure in failures
    )


def context_snapshot_failures_are_required_doc_drift(failures: list[str]) -> bool:
    """Return whether every failure proves changed required-document bytes.

    Route or request replacement may legitimately start unrelated work and
    must never carry an earlier repair budget forward.  Only size/hash drift
    keeps the prior task identity intact strongly enough for that rebind.
    """

    return bool(failures) and all(
        failure.startswith(_REPLACEABLE_REQUIRED_DOC_FAILURE_PREFIXES)
        for failure in failures
    )


def refresh_context_snapshot(
    project: Path,
    rules: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None = None,
) -> dict[str, Any]:
    docs = current_required_docs(rules.resolve(), route)
    if docs is None:
        raise ValueError("required context documents are unavailable")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "required_docs": docs,
    }
    path = context_snapshot_path(project)
    with project_state_lock(project), state_lock(path):
        atomic_write_json(path, snapshot)
    return snapshot


def validate_context_snapshot(
    project: Path,
    rules: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None = None,
) -> list[str]:
    path = context_snapshot_path(project)
    with project_state_lock(project), state_lock(path):
        snapshot = read_json_object(path)
        return _validate_snapshot(snapshot, rules, route, request_intake)


def refresh_and_validate_context_snapshot(
    project: Path,
    rules: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Atomically replace a stale snapshot and validate the new binding."""

    docs = current_required_docs(rules.resolve(), route)
    if docs is None:
        raise ValueError("required context documents are unavailable")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "required_docs": docs,
    }
    path = context_snapshot_path(project)
    with project_state_lock(project), state_lock(path):
        atomic_write_json(path, snapshot)
        failures = _validate_snapshot(snapshot, rules, route, request_intake)
    return snapshot, failures


def _validate_snapshot(
    snapshot: dict[str, Any],
    rules: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any] | None,
) -> list[str]:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        return ["context snapshot schema is missing or invalid"]
    if snapshot.get("route_fingerprint") != route_fingerprint(route):
        return ["context snapshot route fingerprint does not match"]
    if snapshot.get("request_fingerprint") != request_fingerprint(request_intake):
        return ["context snapshot request fingerprint does not match"]
    docs = snapshot.get("required_docs")
    if not isinstance(snapshot.get("request_fingerprint"), str) or len(snapshot["request_fingerprint"]) != 64:
        return ["context snapshot request fingerprint is missing or malformed"]
    if not isinstance(docs, list):
        return ["context snapshot required docs are missing"]
    return required_doc_failures(docs, rules.resolve(), route)
