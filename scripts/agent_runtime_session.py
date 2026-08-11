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
from agent_run_registry import (
    active_run_bindings,
    active_runs,
    evidence_binding_key,
    latest_run_id,
)
from agent_worker_evidence import is_isolated_worker_evidence

SESSION_ENV_VARS = (
    ("claude", "CLAUDE_CODE_SESSION_ID"),
    ("codex", "CODEX_THREAD_ID"),
)
WORKER_EVIDENCE_ENV = "TAO_WORKER_EVIDENCE"
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


def is_run_local_continuation_evidence(
    project: Path, evidence: Path | None
) -> bool:
    """Return whether an evidence file can own a run-local continuation packet."""

    if evidence is None:
        return False
    try:
        relative = evidence.resolve().relative_to(
            project.resolve() / ".tao" / "runs"
        )
    except (OSError, ValueError):
        return False
    parts = relative.parts
    return (
        len(parts) == 2
        and len(parts[0]) == RUN_ID_LENGTH
        and all(character in "0123456789abcdef" for character in parts[0])
        and bool(parts[1])
    )


def resolve_runtime_evidence(
    project: Path,
    session: dict[str, str] | None = None,
) -> Path | None:
    """Resolve one exact active run from its runtime session binding.

    The registry intentionally stores no local path.  Continuation-capable runs
    use their opaque run id as the directory name.  Other project-local evidence
    is discovered only by the registry's safe basename below ``.tao`` and then
    verified against the exact registry evidence key.  No timestamp ordering or
    newest-file selection participates in the decision.  The launcher-issued
    worker evidence path narrows an isolated worker to its own claim.  Without
    that binding, worker evidence is outside the parent session's candidate
    scope.
    """

    project = project.resolve()
    identity = session or runtime_session()
    runtime = str(identity.get("runtime") or "")
    session_id = str(identity.get("session_id") or "")
    if not runtime or not session_id:
        return None
    bindings = active_run_bindings(project)
    if not bindings:
        return None
    worker_scope, worker_evidence = _worker_evidence_scope(project)
    if worker_scope:
        if worker_evidence is None:
            return None
        candidates: tuple[Path, ...] = (worker_evidence,)
        out_of_scope: tuple[Path, ...] = ()
        complete = True
    else:
        evidence_names = {
            str(run.get("evidence_name") or "")
            for run in bindings.values()
            if _safe_evidence_name(run)
        }
        candidates, out_of_scope, complete = _runtime_evidence_candidates(
            project, evidence_names
        )
    matches: list[Path] = []
    resolved_keys: set[str] = set()
    for candidate in candidates:
        key = evidence_binding_key(project, candidate)
        run = bindings.get(key)
        if run is None:
            continue
        resolved_keys.add(key)
        if not _session_binding_matches(
            candidate, run, runtime=runtime, session_id=session_id
        ):
            continue
        matches.append(candidate)
    # Isolated worker evidence is deliberately outside the parent's candidate
    # scope, but its claim is still accounted for here. Otherwise an active
    # worker binding could never be resolved, and the completeness rule below
    # would deny the parent for every incomplete scan.
    resolved_keys.update(
        key
        for key in (evidence_binding_key(project, path) for path in out_of_scope)
        if key in bindings
    )
    # A file the scan missed can only add a match through an active binding
    # key. Once every active key already has its file, no unseen file can
    # change the decision; until then an incomplete scan must fail closed so a
    # skipped subtree cannot hide the second claim the single-match rule exists
    # to catch.
    if not complete and resolved_keys != set(bindings):
        return None
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
    if not name or Path(name).name != name:
        return None
    candidate = project.resolve() / ".tao" / "runs" / run_id / name
    return (
        candidate
        if candidate.is_file()
        and is_run_local_continuation_evidence(project, candidate)
        else None
    )


def _worker_evidence_scope(project: Path) -> tuple[bool, Path | None]:
    raw = os.environ.get(WORKER_EVIDENCE_ENV, "").strip()
    if not raw:
        return False, None
    candidate = Path(raw).expanduser().absolute()
    if not is_isolated_worker_evidence(project, candidate):
        return True, None
    return True, candidate.resolve()


def _safe_evidence_name(run: dict[str, Any]) -> bool:
    name = str(run.get("evidence_name") or "")
    return bool(name) and Path(name).name == name


def _within_worker_root(filename: object, worker_root: Path) -> bool:
    """Return whether a walk error came from the isolated worker subtree."""

    if not isinstance(filename, (str, bytes, os.PathLike)):
        return False
    try:
        path = Path(os.fsdecode(filename))
    except (TypeError, ValueError, UnicodeDecodeError):
        return False
    return path == worker_root or worker_root in path.parents


def _runtime_evidence_candidates(
    project: Path, evidence_names: set[str]
) -> tuple[tuple[Path, ...], tuple[Path, ...], bool]:
    """Enumerate the parent session's evidence files once.

    Returns the in-scope candidates, the isolated-worker files that were found
    but stay out of the parent's scope, and whether the enumeration saw every
    place a parent candidate could be. Worker files are reported rather than
    skipped because the caller still has to account for their registry claim;
    dropping them made an active worker binding permanently unresolvable.

    ``.tao`` also holds unrelated run, worker and worktree state that a
    concurrent run creates and removes, so one unreadable or vanishing
    directory must skip that subtree rather than discard the scan -- aborting
    denied every edit over state the decision never depended on. Completeness
    is reported instead of assumed so the caller can still fail closed when a
    file the scan could not see might have changed the decision. An error
    inside the worker root never counts against it: nothing there can become a
    parent candidate, so an unreadable worker directory is not a reason to deny
    the parent session.
    """

    if not evidence_names:
        return (), (), True
    candidates: list[Path] = []
    worker_scoped: list[Path] = []
    complete = True
    project_state = project.resolve() / ".tao"
    worker_root = project_state / "workers"

    def note_error(error: OSError) -> None:
        nonlocal complete
        if not _within_worker_root(error.filename, worker_root):
            complete = False

    for root, directories, filenames in os.walk(
        project_state, topdown=True, onerror=note_error, followlinks=False
    ):
        current = Path(root)
        directories[:] = sorted(directories)
        inside_worker_root = current == worker_root or worker_root in current.parents
        for filename in sorted(filenames):
            if filename not in evidence_names:
                continue
            candidate = current / filename
            try:
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                resolved = candidate.resolve()
            except OSError:
                complete = False
                continue
            if inside_worker_root:
                worker_scoped.append(resolved)
            else:
                candidates.append(resolved)
    return tuple(candidates), tuple(worker_scoped), complete


def _session_binding_matches(
    candidate: Path,
    run: dict[str, Any],
    *,
    runtime: str,
    session_id: str,
) -> bool:
    payload = _read_object(candidate)
    bound = payload.get("runtime_session")
    if not isinstance(bound, dict):
        return False
    return (
        bound.get("runtime") == runtime
        and bound.get("session_id") == session_id
        and bound.get("resume_generation", 0)
        == int(run.get("resume_generation") or 0)
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
