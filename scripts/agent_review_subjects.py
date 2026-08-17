"""Review subjects that are legitimately clean, and their refusal messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_run_registry import registered_run


REPO_HYGIENE_CONCERNS = frozenset({"branch", "worktree"})

SETTLED_RUN_STATES = frozenset({"completed", "cancelled"})

def clean_read_only_pathspec_review(
    args: Any,
    review_subject: dict[str, Any],
    review_paths: list[str],
) -> bool:
    """Allow evidence-backed inspection of explicit files without inventing a diff."""

    if (
        review_subject.get("kind") == "commit-range"
        or getattr(args, "review_scope", "") != "pathspec"
        or not review_paths
        or not getattr(args, "evidence", None)
    ):
        return False
    try:
        payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not bool((payload.get("execution_mode") or {}).get("read_only")):
        return False

    return explicit_existing_review_paths(args.project, review_paths)

def clean_task_setup_pathspec_review(
    args: Any,
    review_subject: dict[str, Any],
    review_paths: list[str],
) -> bool:
    """Allow a clean task-setup run to attest the exact workflow policy it followed.

    A task route may create an external ticket plus a sibling branch/worktree and
    intentionally leave its protected checkout unchanged.  The follow-on worktree
    starts a separate implementation lifecycle, so manufacturing a source diff in
    the setup checkout would make the review subject less truthful, not more.
    """

    if (
        review_subject.get("kind") == "commit-range"
        or getattr(args, "review_scope", "") != "pathspec"
        or not review_paths
        or not getattr(args, "evidence", None)
    ):
        return False
    try:
        payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    route = payload.get("route") or {}
    effective_effect = (
        ((route.get("request_classification") or {}).get("intent_envelope") or {}).get(
            "effective_effect"
        )
    )
    if route.get("command") != "task" or effective_effect not in {
        "git_write",
        "external_write",
    }:
        return False
    if not any(Path(path).as_posix().endswith("/task/SKILL.md") for path in review_paths):
        return False
    return explicit_existing_review_paths(args.project, review_paths)

def clean_repo_hygiene_review(
    args: Any,
    review_subject: dict[str, Any],
    review_paths: list[str],
) -> bool:
    """Allow a clean checkout after an explicitly destructive Git hygiene task."""

    if (
        review_subject.get("kind") != "working-tree"
        or getattr(args, "review_scope", "") != "repo-hygiene"
        or review_paths
        or not getattr(args, "evidence", None)
    ):
        return False
    try:
        payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    route = payload.get("route") or {}
    effective_effect = (
        ((route.get("request_classification") or {}).get("intent_envelope") or {}).get(
            "effective_effect"
        )
    )
    concerns = {
        concern for concern in (route.get("concerns") or []) if isinstance(concern, str)
    }
    return (
        effective_effect == "destructive"
        and bool(REPO_HYGIENE_CONCERNS.intersection(concerns))
        and not bool((payload.get("execution_mode") or {}).get("read_only"))
    )

def explicit_existing_review_paths(project: Path, review_paths: list[str]) -> bool:
    """Return whether pathspec review paths are concrete existing project paths."""

    project = Path(project).resolve()
    for raw_path in review_paths:
        if any(character in raw_path for character in "*?["):
            return False
        candidate = (project / raw_path).resolve()
        try:
            candidate.relative_to(project)
        except ValueError:
            return False
        if not candidate.exists():
            return False
    return True

def unavailable_structure_review(reason: str) -> dict[str, Any]:
    return {
        "checked_paths": [],
        "checked_path_count": 0,
        "scope": "exact commit snapshot was unavailable",
        "warnings": [],
        "failures": [reason],
        "boundary_note_requirements": [],
        "net_deletion_limit": 0,
        "net_deletions": [],
        "discovery": {"path_metadata": {}},
    }

def invalid_review_subject_details(failure: str) -> list[str]:
    return [
        f"review subject: {failure}",
        "invocation request: provide an ordered, non-empty commit range whose base and "
        "head both resolve to commits in the target repository",
        "review did not start, so no lifecycle checkpoint failed and repair-verify is not required",
    ]

def settled_review_run_state(args: Any) -> str | None:
    """Return the terminal state bound to this review evidence, when present."""

    evidence = getattr(args, "evidence", None)
    if not evidence:
        return None
    evidence_path = Path(evidence)
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        run_id = str(preflight.get("agent_run_id") or "").strip()
        if not run_id:
            return None
        run = registered_run(args.project, evidence_path, run_id=run_id)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    state = str((run or {}).get("state") or "")
    return state if state in SETTLED_RUN_STATES else None

def settled_review_run_invocation_failure_details(state: str) -> list[str]:
    return [
        f"review lifecycle: bound run is already {state}; its gate ledger remains immutable",
        "invocation request: carry the same bounded objective and approvals into a fresh "
        "start/preflight binding, then rerun review against the current worktree",
        "review did not start, so the terminal run has no failed checkpoint to repair; "
        "do not run repair-verify or try to revive the settled run",
    ]

def empty_review_scope_invocation_failure_details(
    failure: str,
    review_scope: str,
) -> list[str]:
    return [
        f"review scope: {review_scope}",
        f"review scope guard: {failure}",
        "invocation request: run the review hook before commit in the worktree that owns "
        "the changed paths; for an existing commit, complete the commit-review workflow and "
        "invoke this hook with --review-scope commit-range, --review-base, and --review-head",
        "review did not start, so no lifecycle checkpoint failed and repair-verify is not required",
    ]
