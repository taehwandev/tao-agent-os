"""Identify the runtime session that produced a piece of lifecycle evidence.

Lifecycle evidence files live in the project and are shared by every runtime, so
their presence alone never proves what happened in the session reading them. The
Claude gates need that distinction: `start` must have run in *this* session
before edits, and `finish` must have run in *this* session before it ends.
Stamping the session into the evidence keeps the hooks that write it the only
producers of that proof, and leaves the gates read-only.

A runtime that exposes no session id records nothing. Gates treat that as "not
this session", which fails closed rather than silently accepting foreign
evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_execution_capsule_state import atomic_write_json
from agent_gate_evidence import resync_gate_evidence_ledger
from agent_run_owner import process_owner
from agent_run_registry import active_runs, latest_run_id

SESSION_ENV_VARS = (("claude", "CLAUDE_CODE_SESSION_ID"),)
RUN_ID_LENGTH = 32


def runtime_session() -> dict[str, str]:
    for runtime, variable in SESSION_ENV_VARS:
        value = os.environ.get(variable, "").strip()
        if value:
            return {"runtime": runtime, "session_id": value}
    return {}


def recorded_session_id(payload: object) -> str:
    """Read back a session id stamped by `runtime_session()`."""
    if not isinstance(payload, dict):
        return ""
    session = payload.get("runtime_session")
    if not isinstance(session, dict):
        return ""
    recorded = session.get("session_id")
    return recorded if isinstance(recorded, str) else ""


def resolve_runtime_evidence(
    project: Path,
    session: dict[str, str] | None = None,
) -> Path | None:
    """Resolve one exact active run from its runtime session binding.

    The registry intentionally stores no local path.  Continuation-capable runs
    use their opaque run id as the directory name, so the only candidate path
    is deterministic and is verified against the registry evidence key.  No
    timestamp ordering or newest-file scan participates in the decision.
    """

    identity = session or runtime_session()
    runtime = str(identity.get("runtime") or "")
    session_id = str(identity.get("session_id") or "")
    if not runtime or not session_id:
        return None
    matches: list[Path] = []
    for run in active_runs(project):
        candidate = _run_evidence_candidate(project, run)
        if candidate is None or latest_run_id(project, candidate) != run.get("run_id"):
            continue
        payload = _read_object(candidate)
        bound = payload.get("runtime_session")
        if not isinstance(bound, dict):
            continue
        generation = int(run.get("resume_generation") or 0)
        bound_generation = bound.get("resume_generation", 0)
        if (
            bound.get("runtime") == runtime
            and bound.get("session_id") == session_id
            and bound_generation == generation
        ):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def bind_resumed_runtime_session(
    *,
    project: Path,
    evidence_path: Path,
    run_id: str,
    resume_generation: int,
    runtime: str,
    session_id: str,
) -> None:
    """Bind a completed resume claim to its new runtime session and packet."""

    if resume_generation < 1 or not runtime or not session_id:
        raise ValueError("resume runtime binding requires a claimed generation and session")
    run = next(
        (
            item
            for item in active_runs(project)
            if item.get("run_id") == run_id
            and int(item.get("resume_generation") or 0) == resume_generation
        ),
        None,
    )
    candidate = _run_evidence_candidate(project, run or {})
    if (
        run is None
        or candidate is None
        or candidate.resolve() != evidence_path.resolve()
        or latest_run_id(project, candidate) != run_id
        or (run.get("owner") or {}) != (process_owner() or {})
    ):
        raise ValueError("resume runtime binding no longer owns the exact run")
    payload = _read_object(candidate)
    if not payload:
        raise ValueError("resume runtime binding evidence is unreadable")
    previous = json.loads(json.dumps(payload))
    payload["runtime_session"] = {
        "runtime": runtime,
        "session_id": session_id,
        "resume_generation": resume_generation,
    }
    try:
        atomic_write_json(candidate, payload)
        resync_gate_evidence_ledger(candidate, payload)
        rules = Path(str(payload.get("rules") or project)).resolve()
        write_continuation_checkpoint(
            project=project,
            rules=rules,
            run_id=run_id,
            kind="lifecycle",
            binding_path=candidate,
        )
    except Exception:
        atomic_write_json(candidate, previous)
        resync_gate_evidence_ledger(candidate, previous)
        raise


def _run_evidence_candidate(project: Path, run: dict[str, Any]) -> Path | None:
    run_id = str(run.get("run_id") or "")
    name = str(run.get("evidence_name") or "")
    if (
        len(run_id) != RUN_ID_LENGTH
        or any(character not in "0123456789abcdef" for character in run_id)
        or not name
        or Path(name).name != name
    ):
        return None
    candidate = project.resolve() / ".tao" / "runs" / run_id / name
    return candidate if candidate.is_file() else None


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
