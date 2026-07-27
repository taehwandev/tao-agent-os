"""Closed schema, version 1, for the project-local session continuation packet.

The packet holds the only work state that survives a process which never ran a
shutdown path.  Everything it may hold is enumerated here, because a
prohibition an implementation can silently violate is not a boundary: unknown
fields are refused on read, every collection is capped, and a schema version
newer than this reader is a hard stop rather than a best-effort parse.
"""

from __future__ import annotations

import json
from typing import Any

from agent_continuation_fields import (
    MAX_DEPTH,
    MAX_PROSE_BYTES,
    MAX_SHORT_TEXT,
    MAX_TEXT,
    checkpoint_name,
    closed_object,
    count,
    depth,
    enum_value,
    failure,
    filename,
    items,
    json_text_failures,
    prose,
    relative_path,
    run_id,
    sha256_value,
    slug,
    state_head,
    timestamp,
)


CONTINUATION_SCHEMA_VERSION = 1
CONTINUATION_FILENAME = "continuation.json"
STORAGE_CLASS = "project_local_never_sync"
MAX_PACKET_BYTES = 24 * 1024
PHASES = ("scoped", "acting", "verifying", "reviewing", "blocked", "reconcile_required", "done")
BINDING_KINDS = ("preflight_snapshot", "execution_capsule")
DECISION_STATUSES = ("accepted", "rejected", "superseded")
SCOPE_ROLES = ("modified", "created", "deleted", "renamed", "inspected")
VERIFICATION_KINDS = (
    "unit", "integration", "compile", "lint", "workflow_validate", "vibeguard",
    "graph", "review", "manual",
)
VERIFICATION_RESULTS = ("success", "fail", "skipped")
MUTATION_KINDS = ("create", "update", "move", "delete", "generate", "format")

ROOT_FIELDS = (
    "schema_version", "storage_class", "run_id", "generation", "phase",
    "binding", "drift", "work", "checkpoint", "updated_at",
)
BINDING_FIELDS = ("kind", "filename", "file_sha256", "binding_sha256")
DRIFT_FIELDS = ("project", "rules", "required_docs_sha256")
STATE_FIELDS = ("head", "worktree_fingerprint", "worktree_signature")
WORK_FIELDS = (
    "objective", "non_goals", "decisions", "changed_scope", "inspected_scope",
    "verification", "remaining_work", "blockers",
)
CHECKPOINT_FIELDS = ("last_completed", "first_unfinished", "mutation_pending")
PENDING_FIELDS = ("kind", "paths", "project", "rules", "started_at")
DECISION_FIELDS = ("id", "status", "text")
VERIFICATION_FIELDS = ("id", "kind", "result", "evidence_sha256", "completed_at")


class ContinuationPacketError(ValueError):
    """A packet was refused; ``failures`` carries stable rule ids and pointers."""

    def __init__(self, failures: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{item['rule']} at {item['pointer']}" for item in failures))
        self.failures = failures


def validate_continuation_packet(payload: Any) -> list[dict[str, str]]:
    """Return every rule violation as a stable rule id and JSON pointer."""

    if not isinstance(payload, dict):
        return [failure("invalid_type", "")]
    text_failures = json_text_failures(payload)
    if text_failures:
        return text_failures
    version = payload.get("schema_version")
    if version != CONTINUATION_SCHEMA_VERSION:
        # A newer packet may hold fields whose meaning this reader cannot know,
        # so there is no partial read: refuse the whole record.
        if (
            isinstance(version, int)
            and not isinstance(version, bool)
            and version > CONTINUATION_SCHEMA_VERSION
        ):
            return [failure("schema_version_unsupported", "/schema_version")]
        return [failure("invalid_enum", "/schema_version")]
    failures: list[dict[str, str]] = []
    closed_object(payload, ROOT_FIELDS, "", failures)
    if payload.get("storage_class") != STORAGE_CLASS:
        failures.append(failure("invalid_enum", "/storage_class"))
    run_id(payload.get("run_id"), "/run_id", failures)
    count(payload.get("generation"), "/generation", failures)
    enum_value(payload.get("phase"), PHASES, "/phase", failures)
    timestamp(payload.get("updated_at"), "/updated_at", failures)
    _binding(payload.get("binding"), failures)
    _drift(payload.get("drift"), failures)
    _work(payload.get("work"), failures)
    _checkpoint(payload.get("checkpoint"), failures)
    _budgets(payload, failures)
    return failures


def canonical_packet_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize one deterministic byte sequence for storage and hashing."""

    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _binding(value: Any, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", "/binding"))
        return
    closed_object(value, BINDING_FIELDS, "/binding", failures)
    enum_value(value.get("kind"), BINDING_KINDS, "/binding/kind", failures)
    filename(value.get("filename"), "/binding/filename", failures)
    sha256_value(value.get("file_sha256"), "/binding/file_sha256", failures)
    sha256_value(value.get("binding_sha256"), "/binding/binding_sha256", failures)


def _state(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", pointer))
        return
    closed_object(value, STATE_FIELDS, pointer, failures)
    state_head(value.get("head"), f"{pointer}/head", failures)
    sha256_value(value.get("worktree_fingerprint"), f"{pointer}/worktree_fingerprint", failures)
    sha256_value(value.get("worktree_signature"), f"{pointer}/worktree_signature", failures)


def _drift(value: Any, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", "/drift"))
        return
    closed_object(value, DRIFT_FIELDS, "/drift", failures)
    _state(value.get("project"), "/drift/project", failures)
    _state(value.get("rules"), "/drift/rules", failures)
    sha256_value(value.get("required_docs_sha256"), "/drift/required_docs_sha256", failures)


def _work(value: Any, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", "/work"))
        return
    closed_object(value, WORK_FIELDS, "/work", failures)
    prose(value.get("objective"), "/work/objective", failures, MAX_TEXT)
    items(value.get("non_goals"), "/work/non_goals", failures, 4,
          lambda item, pointer: prose(item, pointer, failures, MAX_SHORT_TEXT))
    items(value.get("blockers"), "/work/blockers", failures, 4,
          lambda item, pointer: prose(item, pointer, failures, MAX_TEXT))
    items(value.get("decisions"), "/work/decisions", failures, 12,
          lambda item, pointer: _decision(item, pointer, failures))
    items(value.get("changed_scope"), "/work/changed_scope", failures, 64,
          lambda item, pointer: _scope(item, pointer, failures))
    items(value.get("inspected_scope"), "/work/inspected_scope", failures, 64,
          lambda item, pointer: _scope(item, pointer, failures))
    items(value.get("verification"), "/work/verification", failures, 32,
          lambda item, pointer: _verification(item, pointer, failures))
    items(value.get("remaining_work"), "/work/remaining_work", failures, 12,
          lambda item, pointer: _remaining(item, pointer, failures))


def _decision(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", pointer))
        return
    closed_object(value, DECISION_FIELDS, pointer, failures)
    slug(value.get("id"), f"{pointer}/id", failures, 40)
    enum_value(value.get("status"), DECISION_STATUSES, f"{pointer}/status", failures)
    prose(value.get("text"), f"{pointer}/text", failures, MAX_TEXT)


def _scope(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", pointer))
        return
    if value.get("role") == "renamed":
        closed_object(value, ("from", "to", "role"), pointer, failures)
        relative_path(value.get("from"), f"{pointer}/from", failures)
        relative_path(value.get("to"), f"{pointer}/to", failures)
        return
    closed_object(value, ("path", "role"), pointer, failures)
    relative_path(value.get("path"), f"{pointer}/path", failures)
    enum_value(value.get("role"), SCOPE_ROLES, f"{pointer}/role", failures)


def _verification(value: Any, pointer: str, failures: list) -> None:
    """Record that a check ran and how it ended, never how it was invoked."""

    if not isinstance(value, dict):
        failures.append(failure("invalid_type", pointer))
        return
    closed_object(value, VERIFICATION_FIELDS, pointer, failures)
    slug(value.get("id"), f"{pointer}/id", failures, 40)
    enum_value(value.get("kind"), VERIFICATION_KINDS, f"{pointer}/kind", failures)
    enum_value(value.get("result"), VERIFICATION_RESULTS, f"{pointer}/result", failures)
    sha256_value(value.get("evidence_sha256"), f"{pointer}/evidence_sha256", failures, optional=True)
    timestamp(value.get("completed_at"), f"{pointer}/completed_at", failures, optional=True)


def _remaining(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", pointer))
        return
    closed_object(value, ("checkpoint", "action"), pointer, failures)
    checkpoint_name(value.get("checkpoint"), f"{pointer}/checkpoint", failures)
    prose(value.get("action"), f"{pointer}/action", failures, MAX_TEXT)


def _checkpoint(value: Any, failures: list) -> None:
    if not isinstance(value, dict):
        failures.append(failure("invalid_type", "/checkpoint"))
        return
    closed_object(value, CHECKPOINT_FIELDS, "/checkpoint", failures)
    checkpoint_name(value.get("last_completed"), "/checkpoint/last_completed", failures, optional=True)
    checkpoint_name(value.get("first_unfinished"), "/checkpoint/first_unfinished", failures, optional=True)
    pending = value.get("mutation_pending")
    if pending is None:
        return
    if not isinstance(pending, dict):
        failures.append(failure("invalid_type", "/checkpoint/mutation_pending"))
        return
    closed_object(pending, PENDING_FIELDS, "/checkpoint/mutation_pending", failures)
    enum_value(pending.get("kind"), MUTATION_KINDS, "/checkpoint/mutation_pending/kind", failures)
    items(pending.get("paths"), "/checkpoint/mutation_pending/paths", failures, 64,
          lambda item, pointer: relative_path(item, pointer, failures))
    _state(pending.get("project"), "/checkpoint/mutation_pending/project", failures)
    _state(pending.get("rules"), "/checkpoint/mutation_pending/rules", failures)
    timestamp(pending.get("started_at"), "/checkpoint/mutation_pending/started_at", failures)


def _budgets(payload: dict[str, Any], failures: list) -> None:
    if len(canonical_packet_bytes(payload)) > MAX_PACKET_BYTES:
        failures.append(failure("packet_too_large", ""))
    if depth(payload) > MAX_DEPTH:
        failures.append(failure("depth_exceeded", ""))
    work = payload.get("work") if isinstance(payload.get("work"), dict) else {}
    text: list[str] = [str(work.get("objective") or "")]
    for key in ("non_goals", "blockers"):
        text.extend(item for item in work.get(key) or [] if isinstance(item, str))
    for key, field in (("decisions", "text"), ("remaining_work", "action")):
        text.extend(
            str(item.get(field) or "") for item in work.get(key) or [] if isinstance(item, dict)
        )
    if sum(len(item.encode("utf-8")) for item in text) > MAX_PROSE_BYTES:
        failures.append(failure("prose_budget_exceeded", "/work"))
