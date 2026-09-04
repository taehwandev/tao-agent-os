"""Remember which advisory route a runtime session has already been given.

Owner: the per-session delivery state of the advisory route.
Allowed imports: the standard library only. This runs inside a prompt hook, so
it must not pull the route builder in behind it.
Callers/tests: ``workflow.print_route``; coverage lives in
``tests/test_workflow_advisory_echo.py``.
Verification: run that module, which covers a first delivery, a repeat, a
changed route, an unknown session, and an unwritable cache.

The advisory route runs on every user prompt and never sees the prompt: it
lists the same documents for a bug fix, a haiku and a release, byte for byte.
On the reference machine that was 10,262 bytes -- roughly 2,600 tokens --
re-injected into the model's context on every turn, carrying no information it
did not already have from the turn before.

Delivering it once per session keeps what the hook is for (the label context it
writes, and telling a fresh session where the guidance is) and drops the
repetition. The state is keyed by runtime session id, so a new session is told
again, and by a digest of the rendered route, so an edit to the guidance is
re-delivered to a session that already holds the old one.

Failing towards delivery is deliberate throughout: an unknown session, an
unreadable cache or an unwritable one all end with the route printed in full,
which is the behaviour this module replaced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# One entry per session, and sessions are short. The bound exists so an
# unattended machine cannot grow this file without limit, not to be tuned.
MAX_REMEMBERED_SESSIONS = 32
SCHEMA_VERSION = 1


def _state_path(root: Path) -> Path | None:
    """The run-state cache, only where run state already exists.

    `.tao` carries its own ignore file, so writing under it stays out of the
    repository, and a project that has never run a hook has no `.tao` to write
    into.
    """

    state = root / ".tao"
    return state / "cache" / "advisory-route.json" if state.is_dir() else None


def _read_deliveries(root: Path) -> list[dict[str, str]]:
    path = _state_path(root)
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return []
    deliveries = payload.get("deliveries")
    if not isinstance(deliveries, list):
        return []
    return [entry for entry in deliveries if isinstance(entry, dict)]


def already_delivered(root: Path, session_id: str, digest: str) -> bool:
    """Whether this session was already given this exact route."""

    if not session_id or not digest:
        return False
    return any(
        entry.get("session_id") == session_id and entry.get("digest") == digest
        for entry in _read_deliveries(root)
    )


def record_delivery(root: Path, session_id: str, digest: str) -> None:
    """Record that this session now holds this route. Never raises."""

    path = _state_path(root)
    if path is None or not session_id or not digest:
        return
    # The session's previous entry is dropped rather than kept: a session holds
    # one route at a time, and keeping the old digest would let a route that
    # was edited back and forth be suppressed on the strength of a copy the
    # session no longer has in view.
    deliveries = [
        entry for entry in _read_deliveries(root) if entry.get("session_id") != session_id
    ]
    deliveries.append({"session_id": session_id, "digest": digest})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "deliveries": deliveries[-MAX_REMEMBERED_SESSIONS:],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # A cache that cannot be written costs the next prompt a full route,
        # which is the outcome this module exists to make rarer, not a failure.
        return


def hook_session_id(payload_text: str) -> str:
    """Read the session id out of a runtime hook payload, or return "".

    Only the session id is taken. The payload also carries the user's prompt,
    and nothing here may read, store or digest that.
    """

    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    session_id = payload.get("session_id")
    return session_id if isinstance(session_id, str) else ""
