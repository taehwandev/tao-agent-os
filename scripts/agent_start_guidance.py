"""Start's static guidance, printed once per runtime session and project.

Most of a `start` summary is policy prose that is identical on every start:
the reading boundary, work continuity, closeout reuse and similar paragraphs.
An agent in a goal loop starts many runs per session and was re-reading the
same kilobytes each time. The first start in a session prints each paragraph
in full; a later start omits a paragraph whose exact text that session already
saw here and leaves one pointer line in its place. Run-specific lines (route,
gates, required docs, evidence, run id, field requirements, errors) are never
treated as static.

Keyed by (runtime, session id, project) plus a hash of the paragraph text, so a
new session or a changed paragraph prints again. No session binding, or any
state read/write problem, prints everything: the failure mode is the old,
longer output, never missing guidance.

Also owns the review hook's argument shape (`--review-scope` choices and which
scopes need extra arguments) so the parser, its validation and the start
advertisement read one definition.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Iterable

from agent_hook_continuation import WORK_CHECKPOINT_COMMAND_LEAD, WORK_CHECKPOINT_LEAD

STATE_FILE = Path(".tao") / "start-guidance-shown.json"
MAX_SESSIONS = 32
POINTER = (
    "Guidance unchanged since this session's first start in this project "
    "({count} static paragraphs omitted; see that start's output)."
)

# A detail is static when it starts with one of these. Every entry is a fixed
# paragraph whose wording does not depend on this run.
STATIC_PREFIXES: tuple[str, ...] = (
    "Scope-change lifecycle:",
    "Reading boundary:",
    "Checkpoint input:",
    "Analysis transition:",
    "Commit reuse:",
    "Publication scope:",
    "Publication continuity:",
    "Release authority:",
    "Release reuse:",
    "Deployment monitoring:",
    "Work continuity:",
    "Closeout reuse:",
    "Commit readiness: finish derives",
    "Closeout gate reminder:",
    "Performance: record",
    "execution capsule creation deferred",
    "later hooks in this runtime session find this run",
    WORK_CHECKPOINT_LEAD,
    WORK_CHECKPOINT_COMMAND_LEAD,
    "  the work object's fields",
)

# The copyable checkpoint command names this run's evidence path; the rest of
# it is the same every time, and later hooks in the session find the run alone.
_RUN_PATH = re.compile(r"/\.tao/runs/[0-9a-f]{32}/")

REVIEW_SCOPE_CHOICES: tuple[str, ...] = (
    "working-tree", "pathspec", "repo-hygiene", "local-config", "commit-range",
)
REVIEW_SCOPES_NEEDING_PATH = frozenset({"pathspec", "local-config"})
REVIEW_RANGE_SCOPE = "commit-range"
STRUCTURE_FLAG = "--structure-review-evidence"


def review_shape_line(required_flags: Iterable[str]) -> str:
    """One line naming the review hook's accepted argument shape."""

    scopes = []
    for scope in REVIEW_SCOPE_CHOICES:
        if scope in REVIEW_SCOPES_NEEDING_PATH:
            scope += " (+--review-path)"
        elif scope == REVIEW_RANGE_SCOPE:
            scope += " (+--review-base/--review-head)"
        scopes.append(scope)
    flags = list(required_flags)
    required = " ".join(f'{flag} "<text>"' for flag in flags)
    structure = "" if STRUCTURE_FLAG in flags else (
        f" [{STRUCTURE_FLAG} \"owner: ...; allowed imports: ...; forbidden imports: ...; "
        "callers/tests: ...; verification: ...\" if changed dev files exceed size limits "
        "or a multi-role package changes]"
    )
    return (
        f"Review shape: review --review-outcome pass|findings {required}{structure} "
        "(evidence text, not a file path); --review-scope "
        + "|".join(scopes) + " (default working-tree)."
    )


def is_static(detail: str) -> bool:
    return detail.startswith(STATIC_PREFIXES)


def _digest(detail: str) -> str:
    return hashlib.sha256(_RUN_PATH.sub("/.tao/runs/<run>/", detail).encode("utf-8")).hexdigest()[:24]


def _session_key(session: dict[str, str], project: Path) -> str:
    runtime = str(session.get("runtime") or "")
    session_id = str(session.get("session_id") or "")
    if not runtime or not session_id:
        return ""
    material = f"{runtime}\0{session_id}\0{project.resolve()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _read_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return state if isinstance(state, dict) else {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def collapse_repeated_guidance(
    project: Path, session: dict[str, str], details: list[str],
) -> list[str]:
    """Drop static paragraphs this session already saw; fail open to full text."""

    key = _session_key(session, Path(project))
    if not key:
        return details
    path = Path(project) / STATE_FILE
    try:
        state = _read_state(path)
        entry = state.get(key) if isinstance(state.get(key), dict) else {}
        seen = set(entry.get("hashes") or [])
        kept: list[str] = []
        omitted = 0
        pointer_at = -1
        for detail in details:
            if not is_static(detail):
                kept.append(detail)
                continue
            digest = _digest(detail)
            if digest in seen:
                omitted += 1
                if pointer_at < 0:
                    pointer_at = len(kept)
                continue
            seen.add(digest)
            kept.append(detail)
        state[key] = {"hashes": sorted(seen), "updated": time.time()}
        if len(state) > MAX_SESSIONS:
            newest = sorted(
                state, key=lambda name: (state[name] or {}).get("updated", 0), reverse=True,
            )[:MAX_SESSIONS]
            state = {name: state[name] for name in newest}
        _write_state(path, state)
    except (OSError, ValueError, TypeError, AttributeError):
        return details
    if omitted:
        kept.insert(pointer_at, POINTER.format(count=omitted))
    return kept
