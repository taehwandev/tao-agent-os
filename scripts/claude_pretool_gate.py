#!/usr/bin/env python3
"""Claude Code PreToolUse gate for Tao Agent OS.

This gate enforces two things a purely advisory bridge cannot, at the only point
that actually stops the model -- the moment it calls an edit tool:

1. Workflow entry. Nothing otherwise stops a file edit when the agent skipped the
   ``start`` hook, so the workflow is easy to ignore. The gate denies a file-edit
   tool call when an Tao Agent OS project has no fresh preflight evidence, which
   forces ``start`` (route + preflight) before mutating files.
2. Structural proportionality. Skill docs and the post-hoc review gate cannot
   stop a task from ballooning into many new files/layers -- by review time the
   tokens and analysis are already spent. This gate counts new source files a
   session creates and denies the one past the budget, so sprawl has to be
   collapsed or justified per file before more files are written. A recorded
   justification (the ack file) unlocks the rest of the session; the gate never
   hard-bricks and always fails open.

Contract (Claude Code PreToolUse hook):
- Reads a JSON payload from stdin with ``tool_name``, ``cwd``, ``session_id``,
  and ``tool_input`` (``file_path`` for Write).
- Prints a ``permissionDecision`` JSON object to allow or deny.
- Only file-edit tools are gated; everything else and every unexpected error
  fails open (exit 0, no output) so the gate can never brick ordinary editing.

Requires a Claude Code that puts ``CLAUDE_CODE_SESSION_ID`` in the Bash
subprocess environment (v2.1.128-v2.1.136, Week 19 2026), because that is what
lets the ``start`` hook stamp the session the gate checks. On an older build the
stamp is always absent and every edit is denied; set ``TAO_CLAUDE_GATE=0``
to turn the gate off there.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:  # The gate must never fail to load; the import is only used for a message.
    from claude_continuation_hook import ClaudeContinuationAdapter
    from agent_runtime_session import resolve_runtime_evidence
    from support.stable_launcher import stable_launcher_path
    from support.global_state import is_project_state_dir
except ImportError:  # pragma: no cover - exercised only on a broken install
    def stable_launcher_path() -> Path:
        return Path.home() / ".tao" / "bin" / "tao-hook"

    def is_project_state_dir(path: Path) -> bool:
        return path.is_dir() and path.resolve() != (Path.home() / ".tao").resolve()

    def resolve_runtime_evidence(project: Path, session: dict[str, str]) -> Path | None:
        return None

    ClaudeContinuationAdapter = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Only Write creates a file from nothing; Edit/MultiEdit require an existing
# file, so new-file sprawl flows through Write.
NEW_FILE_TOOLS = {"Write"}
STATE_DIR = ".tao"
SESSION_MARKER_DIR = "claude-pretool-gate"
NEW_FILE_STATE_SUFFIX = ".newfiles"
SPRAWL_ACK_SUFFIX = ".sprawl-ack"
# Shared with claude_stop_gate.py, which blocks a stop when an editing session
# has no passing finish.
EDIT_ACTIVITY_SUFFIX = ".edited"
# User-global, because the Stop gate must find projects outside its own cwd.
SESSION_PROJECT_DIR = "claude-session-projects"
OPT_IN_FILES = ("AGENTS.md", "CLAUDE.md", "CODEX.md")
OPT_IN_TOKEN = "tao"
DEFAULT_MAX_AGE_SECONDS = 8 * 60 * 60
MAX_ROOT_WALK = 40
# New source files past this count in one session must be collapsed or justified.
# Matches the review-time signal in
# agent_review_structure.REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT. Only code source
# files count, so doc/content work (e.g. a writing workspace full of .md drafts)
# is never blocked.
DEFAULT_NEW_FILE_BUDGET = 5
SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".cjs", ".dart", ".go", ".h", ".hpp",
    ".java", ".js", ".jsx", ".kt", ".kts", ".m", ".mjs", ".mm", ".php", ".py",
    ".rb", ".rs", ".sass", ".scss", ".svelte", ".swift", ".ts", ".tsx", ".vue",
}


def gate_enabled() -> bool:
    """Escape hatch for runtimes that cannot supply a session id."""
    return os.environ.get("TAO_CLAUDE_GATE", "").strip() != "0"


def allow() -> int:
    """Fail-open: no output means Claude proceeds with the tool call."""
    return 0


def deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def max_age_seconds() -> int:
    raw = os.environ.get("TAO_CLAUDE_GATE_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_AGE_SECONDS
    return value if value >= 0 else DEFAULT_MAX_AGE_SECONDS


def opts_in(path: Path) -> bool:
    """True when this directory marks a project that uses Tao Agent OS.

    The global install lives in a ``.tao`` too, so directory existence alone
    would classify ``$HOME`` as a project -- see support.global_state.
    """
    if is_project_state_dir(path / STATE_DIR):
        return True
    for name in OPT_IN_FILES:
        candidate = path / name
        try:
            head = candidate.read_text(encoding="utf-8", errors="ignore")[:8192]
        except OSError:
            continue
        if OPT_IN_TOKEN in head.lower():
            return True
    return False


def find_project_root(cwd: Path) -> Path | None:
    """Nearest ancestor (including cwd) that opts into Tao Agent OS."""
    for candidate in (cwd, *cwd.parents):
        if opts_in(candidate):
            return candidate
        if candidate == candidate.parent:
            break
    return None


def evidence_mtime(evidence: Path | None) -> float | None:
    if evidence is None:
        return None
    try:
        return evidence.stat().st_mtime
    except OSError:
        return None


def evidence_is_fresh(evidence: Path | None) -> bool:
    mtime = evidence_mtime(evidence)
    if mtime is None:
        return False
    return (time.time() - mtime) <= max_age_seconds()


def safe_session_id(session_id: str) -> str:
    cleaned = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
    return cleaned or "unknown-session"


def deny_reason(root: Path, session_id: str = "") -> str:
    """Explain the denial in terms of what is actually wrong with the evidence.

    Reporting "no fresh evidence" when a stamped-but-foreign or unstamped
    preflight is sitting right there sends the reader looking for a missing
    file. Each cause has a different fix, so each gets its own sentence.
    """
    evidence = session_evidence(root, session_id)
    if evidence is None:
        cause = (
            "No exact run-local preflight evidence is bound to this runtime session. "
            "Fresh or default-path evidence from another session is not reusable."
        )
    elif not evidence_is_fresh(evidence):
        cause = f"Preflight evidence at {evidence} is older than the freshness window."
    else:
        cause = f"Preflight evidence at {evidence} does not satisfy the workflow entry gate."
    return (
        "Tao Agent OS: run the workflow start hook before editing files in this "
        f"project. {cause} "
        f"Run `{stable_launcher_path()} start --project "
        f"{root} --rules <TAO_ROOT> --command <route> --request \"<user "
        "request>\"`, read the route required_docs, then retry the edit. Set "
        "TAO_CLAUDE_GATE_MAX_AGE_SECONDS to tune the freshness window."
    )


def workflow_entry_allows(root: Path, session_id: str) -> bool:
    """Gate 1: the workflow ``start`` hook must have run this session.

    The gate only reads. ``start`` stamps its own session into the preflight
    evidence, so proof of workflow entry has exactly one writer. Two earlier
    designs failed because the gate wrote that proof itself: first by promoting
    any fresh evidence into a session marker (which let a previous session's
    file unlock this one), then by comparing timestamps (which denied the
    correct ``start`` -> edit order outright, because evidence written before
    the first edit attempt can never be newer than it).

    Freshness stays as a second condition so an abandoned session cannot be
    resumed days later on its original evidence.
    """
    if not session_id:
        # Nothing to attribute the evidence to. Falling back to freshness here
        # would reopen the original bypass on any payload missing a session.
        return False
    evidence = session_evidence(root, session_id)
    return evidence is not None and evidence_is_fresh(evidence)


def session_evidence(root: Path, session_id: str) -> Path | None:
    if not session_id:
        return None
    return resolve_runtime_evidence(
        root,
        {"runtime": "claude", "session_id": session_id},
    )


def record_edit_activity(root: Path, session_id: str) -> None:
    """Note that this session actually mutated files.

    This is an activity record, not gate-passing proof -- the distinction that
    matters here. Writing proof is what let an earlier version of this gate
    fabricate its own workflow entry; writing "this session edited something" is
    only what the Stop gate needs to know a missing finish is worth blocking on.
    A read-only session never gets this marker and is never blocked at Stop.
    """
    marker = root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + EDIT_ACTIVITY_SUFFIX)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
    except OSError:
        pass


def session_projects_index(session_id: str) -> Path:
    """Per-session list of every project this session edited.

    The Stop gate runs once, with one cwd, but a session can edit files in
    several projects. Without this index it only ever checks the cwd project and
    lets an edited-but-unverified project stop silently.
    """
    return Path.home() / STATE_DIR / SESSION_PROJECT_DIR / safe_session_id(session_id)


def record_session_project(root: Path, session_id: str) -> None:
    index = session_projects_index(session_id)
    line = str(root)
    try:
        existing = index.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    if line in existing:
        return
    try:
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def new_file_budget() -> int:
    raw = os.environ.get("TAO_CLAUDE_GATE_NEW_FILE_BUDGET", "").strip()
    if not raw:
        return DEFAULT_NEW_FILE_BUDGET
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_NEW_FILE_BUDGET
    return value if value >= 0 else DEFAULT_NEW_FILE_BUDGET


def write_target_path(payload: dict, cwd: Path) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    target = Path(raw)
    if not target.is_absolute():
        target = cwd / target
    return target


def find_edit_project_root(payload: dict, cwd: Path) -> Path | None:
    """Resolve the project that owns the file being edited, not just the cwd.

    A session's working directory and the file it edits are often different
    projects: this gate let a whole article get rewritten in a writing workspace
    while the cwd sat in another repo, so the writing project's own `start` was
    never required and its edits were recorded against the wrong project. The
    Stop gate then asked the cwd project for a finish, found one, and allowed a
    stop that left the edited project unverified.

    The target path decides. cwd stays as the fallback for tools that report no
    file path.
    """
    target = write_target_path(payload, cwd)
    if target is not None:
        root = find_project_root(target.parent)
        if root is not None:
            return root
    return find_project_root(cwd)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def sprawl_state_file(root: Path, session_id: str) -> Path:
    return root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + NEW_FILE_STATE_SUFFIX)


def sprawl_ack_file(root: Path, session_id: str) -> Path:
    return root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + SPRAWL_ACK_SUFFIX)


def read_new_files(state: Path) -> list[str]:
    try:
        text = state.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def record_new_file(state: Path, key: str) -> None:
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        with state.open("a", encoding="utf-8") as handle:
            handle.write(key + "\n")
    except OSError:
        pass


def sprawl_deny_reason(count: int, budget: int, ack: Path, target: Path, root: Path) -> str:
    return (
        f"Tao Agent OS proportionality gate: this task has already created {count} new "
        f"source file(s) in {root.name} (budget {budget}); creating {target.name} would exceed "
        "it. Turning a task into many files, layers, or abstractions burns tokens and review "
        "time. Collapse the change into fewer files, or -- if each new file protects a concrete "
        f"present risk -- record the per-file justification by writing it to {ack}, then retry. "
        "Tune with TAO_CLAUDE_GATE_NEW_FILE_BUDGET."
    )


def sprawl_deny(tool: str, payload: dict, root: Path, cwd: Path, session_id: str) -> str | None:
    """Gate 2: deny the new source file that pushes a task past its budget."""
    if tool not in NEW_FILE_TOOLS:
        return None
    budget = new_file_budget()
    if budget <= 0:
        return None
    try:
        target = write_target_path(payload, cwd)
        if target is None or target.exists():
            # No path, or editing/overwriting an existing file -- not new-file sprawl.
            return None
        if STATE_DIR in target.parts:
            return None  # agent state (including the ack file itself) never counts
        if not is_relative_to(target, root):
            return None  # outside the project
        if target.suffix.lower() not in SOURCE_SUFFIXES:
            return None  # docs/config/content are not code sprawl

        state = sprawl_state_file(root, session_id)
        recorded = read_new_files(state)
        key = str(target)
        if sprawl_ack_file(root, session_id).exists():
            if key not in recorded:
                record_new_file(state, key)
            return None
        if key in recorded:
            return None  # idempotent retry of an already-counted file
        if len(recorded) + 1 > budget:
            return sprawl_deny_reason(len(recorded), budget, sprawl_ack_file(root, session_id), target, root)
        record_new_file(state, key)
        return None
    except Exception:
        return None


def decide(payload: dict) -> int:
    if not gate_enabled():
        return allow()
    tool = payload.get("tool_name")
    if tool not in EDIT_TOOLS:
        return allow()
    cwd_raw = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(cwd_raw).resolve()
    except OSError:
        return allow()
    root = find_edit_project_root(payload, cwd)
    if root is None:
        # Not an Tao Agent OS project; never block ordinary editing.
        return allow()
    session_id = str(payload.get("session_id") or "")
    if not workflow_entry_allows(root, session_id):
        return deny(deny_reason(root, session_id))
    sprawl_reason = sprawl_deny(tool, payload, root, cwd, session_id)
    if sprawl_reason:
        return deny(sprawl_reason)
    # A missing adapter module is a broken install, not a policy violation. This
    # gate promises never to fail to load; denying every edit because an import
    # failed breaks that promise and removes the means of repairing the install.
    if ClaudeContinuationAdapter is not None:
        continuation_reason = ClaudeContinuationAdapter.pre_mutation(
            payload, root=root, cwd=cwd, session_id=session_id
        )
        if continuation_reason:
            return deny(continuation_reason)
    record_edit_activity(root, session_id)
    record_session_project(root, session_id)
    return allow()


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return allow()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return allow()
        return decide(payload)
    except Exception:
        # Any unexpected failure must fail open.
        return allow()


if __name__ == "__main__":
    sys.exit(main())
