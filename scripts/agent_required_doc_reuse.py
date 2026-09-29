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
MAX_TAKEAWAYS = 3
MAX_TAKEAWAY_CHARS = 400
# Written beside a run's preflight by `review --doc-takeaway`, for routes such
# as commit that have no source-docs gate to carry a takeaway.
DOC_TAKEAWAY_FILE = "doc-takeaway.json"


def required_doc_reuse(
    preflight_path: Path, *, require_takeaway: bool = True
) -> dict[str, list[str]]:
    """Partition required docs into proven same-session reuse and unread docs.

    This is display-only evidence. Any malformed, missing, cross-session, or
    changed record fails closed and leaves the document in ``unread``. The
    notice an agent reads requires the prior run's takeaway; commit-ready's
    automatic re-attestation of an already reviewed diff acts on no document,
    so it asks only whether the same session held them.
    """

    unread: list[str] = []
    try:
        current = _read(preflight_path, MAX_PREFLIGHT_BYTES)
        route = current.get("route") or {}
        docs = _required_paths(route)
        unread = list(docs)
        if not docs:
            return {"reused": [], "unread": unread}

        current_records = _doc_records(current)
        wanted = {current_records[doc] for doc in docs if doc in current_records}
        if not wanted:
            return {"reused": [], "unread": unread}
        reusable_records: set[tuple[str, str, int]] = set()
        takeaways: list[str] = []
        for prior_path, prior in _same_session_priors(preflight_path, current):
            try:
                prior_records = set(_doc_records(prior).values())
            except (ValueError, TypeError):
                continue
            credited = _credit(prior_records, wanted, prior_path, takeaways)
            if not credited and (require_takeaway or not prior_records & wanted):
                continue
            reusable_records.update(prior_records)
            if wanted <= reusable_records:
                break

        reused = [doc for doc in docs if current_records.get(doc) in reusable_records]
        reused_set = set(reused)
        result = {
            "reused": reused,
            "unread": [doc for doc in docs if doc not in reused_set],
        }
        if reused and takeaways:
            result["takeaways"] = takeaways
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"reused": [], "unread": unread}


def project_route_doc_reuse(preflight_path: Path) -> dict[str, list[str]]:
    """Partition project-declared route docs the same way as required docs.

    Project docs live under the project root, not the rules root, so they are
    recorded beside the snapshot as ``project_route_docs`` and compared by
    path, hash and size against completed same-session runs.
    """

    unread: list[str] = []
    try:
        current = _read(preflight_path, MAX_PREFLIGHT_BYTES)
        current_records = _project_records(current)
        unread = list(current_records)
        if not current_records:
            return {"reused": [], "unread": unread}
        wanted = set(current_records.values())
        reusable: set[tuple[str, str, int]] = set()
        takeaways: list[str] = []
        for prior_path, prior in _same_session_priors(preflight_path, current):
            try:
                prior_records = set(_project_records(prior).values())
            except (ValueError, TypeError):
                continue
            if not _credit(prior_records, wanted, prior_path, takeaways):
                continue
            reusable.update(prior_records)
            if wanted <= reusable:
                break
        reused = [doc for doc, record in current_records.items() if record in reusable]
        reused_set = set(reused)
        result = {"reused": reused, "unread": [doc for doc in unread if doc not in reused_set]}
        if reused and takeaways:
            result["takeaways"] = takeaways
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"reused": [], "unread": unread}


def _same_session_priors(preflight_path: Path, current: dict[str, Any]):
    """Yield completed same-session, same-project runs, newest first."""

    project = Path(current["project"]).resolve()
    rules = Path(current["rules"]).resolve()
    run_dir = preflight_path.resolve().parent
    if (
        not RUN_ID.fullmatch(run_dir.name)
        or run_dir.parent != project / ".tao" / "runs"
        or preflight_path.resolve() != run_dir / "preflight.json"
    ):
        return
    session = _session(current)
    if session is None:
        return
    registry = _read(project / ".tao" / "run-registry.json", MAX_REGISTRY_BYTES)
    runs = registry.get("runs")
    if not isinstance(runs, list):
        return
    # Registry entries are appended. Bound history work, not goal length.
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
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        yield prior_path, prior


def record_doc_takeaway(evidence_path: Path, text: str) -> None:
    """Store the agent's takeaway from this run's docs beside its preflight."""

    normalized = _normalize(text)
    if not normalized:
        return
    path = evidence_path.parent / DOC_TAKEAWAY_FILE
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"takeaway": normalized}), encoding="utf-8")
    temporary.replace(path)


def _credit(
    prior_records: set[tuple[str, str, int]],
    wanted: set[tuple[str, str, int]],
    prior_path: Path,
    takeaways: list[str],
) -> bool:
    """Whether a prior run may prove these docs were read, keeping its takeaways.

    A completed run that listed a document proves only that the document was
    required, not that it was read, and a reuse notice with nothing to replay
    after a context compaction told the agent to trust a reading it no longer
    had. So a run counts only when it recorded what it took from its docs; one
    that recorded nothing leaves them unread. The takeaways are keyed by the
    documents a run read, not by its route, so a commit run reusing a document
    replays what an earlier run of any route recorded.
    """

    if not prior_records & wanted:
        return False
    recorded = [text for text in (_source_docs_takeaway(prior_path), _review_takeaway(prior_path)) if text]
    for text in recorded:
        if len(takeaways) < MAX_TAKEAWAYS and text not in takeaways:
            takeaways.append(text)
    # Only a run whose takeaway the notice actually shows is credited. Past
    # the display cap a run's documents would otherwise leave the unread list
    # with nothing replayed for them -- the gap the takeaway rule closes.
    return any(text in takeaways for text in recorded)


def _source_docs_takeaway(prior_path: Path) -> str:
    try:
        ledger = _read(prior_path.parent / "gate-evidence.json", MAX_PREFLIGHT_BYTES)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ""
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get("gate") != "source docs":
            continue
        if entry.get("status") != "SUCCESS":
            return ""
        return _normalize((entry.get("fields") or {}).get("takeaway"))
    return ""


def _review_takeaway(prior_path: Path) -> str:
    try:
        record = _read(prior_path.parent / DOC_TAKEAWAY_FILE, MAX_TAKEAWAY_CHARS * 8)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    return _normalize(record.get("takeaway"))


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_TAKEAWAY_CHARS]


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
    return _records((preflight.get("execution_snapshot") or {}).get("required_docs") or [])


def _project_records(preflight: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    return _records(preflight.get("project_route_docs") or [])


def _records(records: Any) -> dict[str, tuple[str, str, int]]:
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
