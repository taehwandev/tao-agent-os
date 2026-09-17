"""Refuse unrelated claims on dirty ticket worktrees before workflow start."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from agent_runtime_session import resolve_runtime_evidence, runtime_session


WORKTREE_POLICY_PATH = Path(".agents/shared/worktree-policy.json")
SESSION_AFFINITY_STATES = frozenset(
    {
        "running",
        "paused",
        "resuming",
        "failed",
        "completed",
        "reconcile_required",
        "blocked",
        "interrupted",
    }
)


def task_affinity_denial(
    project: Path,
    request_intake: dict[str, Any],
    *,
    same_runtime_session: bool | None = None,
) -> str | None:
    """Explain why a dirty ticket worktree does not belong to this start.

    A linked worktree and a ticket-shaped branch isolate bytes, but they do not
    prove that a new runtime session owns those bytes.  A dirty worktree may be
    reused only by the session already bound to it or by intake that explicitly
    names the same ticket.  Clean worktrees retain the normal start path.
    """

    project = project.resolve()
    if not (project / ".git").is_file():
        return None
    pattern = _ticket_pattern(project)
    if pattern is None or not _worktree_is_dirty(project):
        return None
    branch = _current_branch(project)
    branch_tickets = _ticket_keys(pattern, branch)
    if not branch_tickets:
        return None
    intake_text = "\n".join(
        str(request_intake.get(field) or "")
        for field in ("request", "continuation_scope")
    )
    if branch_tickets & _ticket_keys(pattern, intake_text):
        return None
    if same_runtime_session is None:
        same_runtime_session = _same_runtime_session_has_run(project)
    if same_runtime_session:
        return None
    ticket = sorted(branch_tickets)[0]
    return (
        "task-affinity mismatch: this linked worktree has uncommitted work on "
        f"ticket `{ticket}`, but the current runtime session and request do not "
        "prove ownership of that task. Worktree location or branch reuse alone "
        "is not continuation evidence. Resume the exact verified run, explicitly "
        f"name `{ticket}` in the continuation context, or use a separate "
        "ticket worktree."
    )


def _ticket_pattern(project: Path) -> re.Pattern[str] | None:
    try:
        policy = json.loads((project / WORKTREE_POLICY_PATH).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if (
        not isinstance(policy, dict)
        or policy.get("require_ticketed_product_branch") is not True
    ):
        return None
    value = policy.get("ticket_key_pattern")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return re.compile(value)
    except re.error:
        return None


def _ticket_keys(pattern: re.Pattern[str], text: str) -> set[str]:
    return {match.group(0).upper() for match in pattern.finditer(text)}


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(project), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _worktree_is_dirty(project: Path) -> bool:
    result = _git(project, "status", "--short", "--untracked-files=all")
    return bool(result and result.returncode == 0 and result.stdout.strip())


def _current_branch(project: Path) -> str:
    result = _git(project, "branch", "--show-current")
    return result.stdout.strip() if result and result.returncode == 0 else ""


def _same_runtime_session_has_run(project: Path) -> bool:
    session = runtime_session()
    if not session:
        return False
    return resolve_runtime_evidence(
        project,
        session,
        states=SESSION_AFFINITY_STATES,
        latest_of_several=True,
    ) is not None
