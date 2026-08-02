"""Stable route and preflight fingerprints shared by workflow evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def route_fingerprint(route: dict[str, Any]) -> str:
    """Return a stable hash for the route fields that affect execution."""

    stable = {
        "command": route.get("command"),
        "platform": route.get("platform"),
        "concerns": route.get("concerns") or [],
        "docs": route.get("docs") or [],
        "required_docs": route.get("required_docs") or [],
        "reference_docs": route.get("reference_docs") or [],
        "gates": route.get("gates") or [],
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def request_fingerprint(request_intake: Mapping[str, Any] | None) -> str:
    """Return an opaque identity for the exact preflight request contract.

    The execution capsule intentionally carries no request text.  Binding a
    canonical hash here still prevents a route selected for one request from
    being reused for another request that happens to resolve to the same
    command and document manifest.
    """

    intake = request_intake or {}
    stable = {
        "request": str(intake.get("request") or ""),
        "continuation_scope": str(intake.get("continuation_scope") or ""),
        "request_classified": bool(intake.get("request_classified")),
        "classification_evidence": str(intake.get("classification_evidence") or ""),
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preflight_evidence_sha256(evidence_path: Path) -> str:
    """Hash a preflight evidence file without reading task content into memory."""

    digest = hashlib.sha256()
    with evidence_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def required_docs_for_route(route: dict[str, Any]) -> list[str]:
    """Return the required-document manifest selected by the router."""

    return [
        str(doc)
        for doc in (route.get("required_docs") or [])
        if str(doc).strip()
    ]
