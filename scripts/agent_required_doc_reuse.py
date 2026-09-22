"""Prove which documents are already loaded in this session, for every route."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_REGISTRY_BYTES = 4 * 1024 * 1024
MAX_PREFLIGHT_BYTES = 8 * 1024 * 1024
MAX_RUNS = 100


def required_doc_reuse(preflight_path: Path) -> dict[str, list[str]]:
    """Partition required docs into proven same-session reuse and unread docs.

    This is display-only evidence. Any malformed, missing, cross-session, or
    changed record fails closed and leaves the document in ``unread``.
    """

    unread: list[str] = []
    try:
        current = _read(preflight_path, MAX_PREFLIGHT_BYTES)
        route = current.get("route") or {}
        docs = _required_paths(route)
        unread = list(docs)
        if not docs:
            return {"reused": [], "unread": unread}

        project = Path(current["project"]).resolve()
        rules = Path(current["rules"]).resolve()
        run_dir = preflight_path.resolve().parent
        if (
            not RUN_ID.fullmatch(run_dir.name)
            or run_dir.parent != project / ".tao" / "runs"
            or preflight_path.resolve() != run_dir / "preflight.json"
        ):
            return {"reused": [], "unread": unread}
        session = _session(current)
        if session is None:
            return {"reused": [], "unread": unread}

        current_records = _doc_records(current)
        reusable_records: set[tuple[str, str, int]] = set()
        registry = _read(project / ".tao" / "run-registry.json", MAX_REGISTRY_BYTES)
        runs = registry.get("runs")
        if not isinstance(runs, list):
            return {"reused": [], "unread": unread}
        # Registry entries are appended. Bound history work, not goal length.
        wanted = {current_records[doc] for doc in docs if doc in current_records}
        if not wanted:
            return {"reused": [], "unread": unread}
        for record in reversed(runs[-MAX_RUNS:]):
            if not isinstance(record, dict) or record.get("state") != "completed":
                continue
            run_id = record.get("run_id")
            if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
                continue
            evidence_name = record.get("evidence_name", "preflight.json")
            if evidence_name != "preflight.json" or run_id == run_dir.name:
                continue
            prior_path = project / ".tao" / "runs" / run_id / evidence_name
            try:
                prior = _read(prior_path, MAX_PREFLIGHT_BYTES)
                if (
                    prior.get("agent_run_id") != run_id
                    or Path(prior["project"]).resolve() != project
                    or Path(prior["rules"]).resolve() != rules
                    or _session(prior) != session
                ):
                    continue
                reusable_records.update(_doc_records(prior).values())
                if wanted <= reusable_records:
                    break
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue

        reused = [doc for doc in docs if current_records.get(doc) in reusable_records]
        reused_set = set(reused)
        return {
            "reused": reused,
            "unread": [doc for doc in docs if doc not in reused_set],
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"reused": [], "unread": unread}


def _read(path: Path, limit: int) -> dict[str, Any]:
    if path.stat().st_size > limit:
        raise ValueError("oversized lifecycle evidence")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid lifecycle evidence")
    return value


def _required_paths(route: dict[str, Any]) -> list[str]:
    docs = route.get("required_docs") or []
    if not isinstance(docs, list) or any(not isinstance(doc, str) for doc in docs):
        raise ValueError("invalid required document manifest")
    return list(dict.fromkeys(docs))


def _session(preflight: dict[str, Any]) -> tuple[str, str] | None:
    session = preflight.get("runtime_session") or {}
    runtime, session_id = session.get("runtime"), session.get("session_id")
    if not isinstance(runtime, str) or not isinstance(session_id, str):
        return None
    if not runtime or not session_id:
        return None
    return runtime, session_id


def _doc_records(preflight: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    records = (preflight.get("execution_snapshot") or {}).get("required_docs") or []
    if not isinstance(records, list):
        raise ValueError("invalid required document snapshot")
    result: dict[str, tuple[str, str, int]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid required document record")
        path = record.get("path")
        sha256 = record.get("sha256")
        size = record.get("size_bytes")
        if (
            not isinstance(path, str)
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise ValueError("invalid required document record")
        result[path] = (path, sha256, size)
    return result
