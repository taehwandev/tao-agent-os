"""Finish-time documentation exceptions for the source-doc snapshot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_execution_capsule_docs import validated_required_doc_update_receipt
from agent_gate_evidence import SCHEMA_VERSION, gate_evidence_path_for_preflight, read_gate_evidence_ledger
from agent_route_state import preflight_evidence_sha256, required_docs_for_route, route_fingerprint


def documented_required_doc_updates(
    *,
    evidence_path: Path,
    route: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Return exact required-doc updates backed by trusted final-byte receipts."""

    required_docs = set(required_docs_for_route(route))
    if not required_docs:
        return {}
    ledger = read_gate_evidence_ledger(gate_evidence_path_for_preflight(evidence_path))
    if not _ledger_matches_route(ledger, evidence_path, route):
        return {}
    updates: dict[str, dict[str, str]] = {}
    for entry in ledger.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("gate") or "") != "documentation":
            continue
        fields = {str(key): str(value) for key, value in (entry.get("fields") or {}).items()}
        target = fields.get("target", "").strip()
        if target not in required_docs:
            continue
        updates.pop(target, None)
        if entry.get("status") != "SUCCESS":
            continue
        if fields.get("decision", "").strip().lower() != "updated":
            continue
        receipt = validated_required_doc_update_receipt(fields)
        if receipt is not None:
            updates[target] = receipt
    return updates


def required_doc_target_failures(*, target: str, route: dict[str, Any]) -> list[str]:
    """Reject a combined documentation target that embeds a required-doc path.

    Required-document snapshot exceptions are exact-path capabilities.  A
    documentation record may describe other artifacts freely, but once it
    names a routed required doc it must dedicate one record to that exact path.
    This keeps the exception finite and prevents a late, opaque finish failure.
    """

    normalized = target.strip()
    required_docs = set(required_docs_for_route(route))
    if not normalized or normalized in required_docs:
        return []
    embedded = sorted(
        path for path in required_docs if _contains_standalone_path(normalized, path)
    )
    if not embedded:
        return []
    return [
        "documentation target embeds route required_docs but is not one exact "
        "route-relative path: "
        + ", ".join(embedded)
        + "; record one documentation SUCCESS entry per required doc"
    ]


def _contains_standalone_path(value: str, path: str) -> bool:
    """Return whether ``path`` appears as one complete path token in ``value``."""

    path_character = r"[\w./\\-]"
    pattern = rf"(?<!{path_character}){re.escape(path)}(?!{path_character})"
    return re.search(pattern, value) is not None


def _ledger_matches_route(ledger: dict[str, Any], evidence_path: Path, route: dict[str, Any]) -> bool:
    try:
        same_path = Path(str(ledger.get("preflight_evidence"))).expanduser().resolve() == evidence_path.resolve()
    except (OSError, RuntimeError, ValueError):
        same_path = False
    return (
        ledger.get("schema_version") == SCHEMA_VERSION
        and same_path
        and ledger.get("preflight_evidence_sha256") == preflight_evidence_sha256(evidence_path)
        and ledger.get("route_fingerprint") == route_fingerprint(route)
    )
