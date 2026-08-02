#!/usr/bin/env python3
"""Dispatch-CLI resolution helpers for the ``workflow.py dispatch`` action.

These helpers turn parsed CLI arguments plus on-disk delegation and preflight
evidence into the two decisions ``print_dispatch`` needs before it builds a
manifest: whether the dispatch must run isolated, and whether the parent's start
route can be reused as-is. They live here rather than in ``workflow.py`` so the
CLI entry point stays within its line budget and so this cohesive dispatch glue
can be unit-tested directly. This module intentionally depends only on the
delegation-plan and capsule-binding libraries; it must never import
``workflow.py`` so the dependency stays acyclic
(``workflow.py`` -> ``workflow_dispatch_cli`` -> ``agent_delegation_plan``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_delegation_plan import (
    read_delegation_plan,
    validate_delegation_plan_structure,
    worker_declares_worktree_isolation,
)
from agent_execution_capsule_bindings import preflight_identity_failures


def dispatch_isolation_required(args: argparse.Namespace, project: Path) -> bool:
    """Derive effective isolation from the CLI flag and the delegation plan.

    A delegation-plan *file* is a statement of delegation intent: its mere
    presence means dispatch must honor the plan, even when the flag is absent
    and even when the file's contents are malformed. Resolution distinguishes
    three fail-closed states:

    1. **No plan present** -- the default plan file does not exist and no
       explicit ``--delegation-plan`` was given (the resolver returns ``{}``).
       Dispatch is flag-only: ``--require-isolation`` forces isolation, its
       absence leaves a single-worker workspace run. A ``--worker-id`` supplied
       with no plan still fails closed via the resolver, which raises.
    2. **Explicit plan path missing** -- ``--delegation-plan`` names a path that
       does not exist. That is a caller error, not "no plan", so the resolver
       raises naming the path.
    3. **Plan file exists (default or explicit), any shape** -- the file's
       existence makes it an active plan, so it must be structurally valid
       *first*: broken JSON, empty/missing workers, or any other structural
       failure raises before an isolation decision is made. A valid plan then
       requires a ``--worker-id`` so dispatch is bound to a planned worker;
       without it the plan's isolation promise could be silently bypassed into
       an inline/workspace run, so that combination raises rather than
       downgrading. A worker the plan declares worktree-isolated MUST dispatch
       isolated even without the flag, and is never downgraded by omitting it.

    Raises:
        ValueError: when an explicit ``--delegation-plan`` path is missing, when
            an existing plan file is structurally invalid, when an existing plan
            is dispatched without ``--worker-id``, or when a supplied
            ``--worker-id`` cannot be resolved to a single worker.
    """

    worker_id = str(getattr(args, "worker_id", "") or "").strip()
    plan = _resolve_delegation_plan(args, project)

    if not plan:
        # State 1: no plan file present. A worker id with no plan still has to
        # fail closed rather than silently ignore the missing plan, so defer to
        # the resolver, which raises for that case.
        if worker_id:
            return bool(args.require_isolation) or worker_declares_worktree_isolation(
                plan, worker_id
            )
        return bool(args.require_isolation)

    # State 3: a plan file exists, whatever its shape. Its existence is the
    # delegation intent, so it drives dispatch and must be structurally sound
    # first -- broken JSON, empty/missing workers, overlapping scopes, and every
    # other schema failure are rejected before isolation is resolved from
    # unchecked file contents.
    failures = validate_delegation_plan_structure(plan)
    if failures:
        raise ValueError(
            "an active delegation plan is structurally invalid and must not drive "
            "dispatch; fix it before dispatching:\n- " + "\n- ".join(failures)
        )
    if not worker_id:
        raise ValueError(
            "an active delegation plan requires --worker-id <id> so dispatch "
            "matches the planned worker; pass --worker-id or remove the stale plan"
        )
    return bool(args.require_isolation) or worker_declares_worktree_isolation(
        plan, worker_id
    )


def _resolve_delegation_plan(args: argparse.Namespace, project: Path) -> dict[str, object]:
    """Read the delegation plan from an explicit ``--delegation-plan`` or the default.

    An explicit ``--delegation-plan`` naming a missing path is a caller error and
    raises; the default plan file simply being absent is the no-plan state and
    returns ``{}`` (via ``read_delegation_plan``).
    """

    plan_path = getattr(args, "delegation_plan", None)
    if plan_path is not None:
        resolved = Path(plan_path).expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"explicit delegation plan not found: {resolved}")
        return _read_delegation_plan_from(resolved)
    return read_delegation_plan(project)


def _read_delegation_plan_from(path: Path) -> dict[str, object]:
    """Read a delegation plan from an existing explicit path, mirroring read_delegation_plan.

    The caller guarantees ``path`` exists (a missing explicit path is a caller
    error raised in ``_resolve_delegation_plan``), so this only mirrors
    ``read_delegation_plan``'s parse behavior for a file that is present.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable plan (a directory at this path, a permission error, or
        # broken JSON) is a malformed plan, not a crash: return the same
        # invalid_json marker so State-3 structural validation raises the clean
        # ValueError the CLI turns into exit 2, rather than letting a raw
        # IsADirectoryError/PermissionError escape.
        return {"invalid_json": True, "path": str(path)}
    if isinstance(payload, dict):
        payload.setdefault("path", str(path))
        return payload
    return {"invalid_json": True, "path": str(path)}


def parent_dispatch_route(
    evidence_path: Path,
    *,
    command: str,
    request: str,
    continuation_scope: str = "",
    request_classified: bool,
    classification_evidence: str,
    platform: str | None,
    concerns: list[str],
    project: Path,
    rules: Path,
) -> dict[str, object] | None:
    """Reuse the parent start route without mutating its handoff capsule."""

    if not preflight_identity_matches(evidence_path, project=project, rules=rules):
        return None
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    route = payload.get("route") if isinstance(payload, dict) else None
    if not isinstance(route, dict) or route.get("command") != command:
        return None
    if platform and route.get("platform") != platform:
        return None
    routed_concerns = {
        str(item) for item in (route.get("concerns") or []) if str(item).strip()
    }
    if any(concern not in routed_concerns for concern in concerns):
        return None
    intake = payload.get("request_intake")
    if not isinstance(intake, dict):
        return None
    if request_classified:
        if not intake.get("request_classified"):
            return None
        if intake.get("classification_evidence") != classification_evidence:
            return None
        # A classification description is reusable policy evidence, not a
        # request identity.  Reuse a classified parent route only when start
        # also captured the exact current request; otherwise resolve a fresh
        # route and keep the old capsule invalid for this dispatch.
        if not intake.get("request") or intake.get("request") != request:
            return None
    elif intake.get("request") != request:
        return None
    if str(intake.get("continuation_scope") or "") != continuation_scope:
        return None
    return dict(route)


def preflight_identity_matches(
    evidence_path: Path,
    *,
    project: Path,
    rules: Path,
) -> bool:
    return not preflight_identity_failures(evidence_path, project, rules)
