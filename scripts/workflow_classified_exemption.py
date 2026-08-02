"""Bind the ``--request-classified`` exemption to a valid parent capsule.

``--request-classified`` exists for one narrow case: a delegated worker holds
only a short acknowledgement as its request identity, and reclassifying that
text would falsely reopen clarification/Grill-Me after the parent already
resolved it.

The flag used to be self-asserting. Passing it skipped ``classify_request``
entirely, which left ``route_block_reason`` inspecting ``None`` and returning
immediately -- the clarify-first/Grill-Me check was not satisfied, it was never
evaluated. The only surviving check read free text the caller wrote about
itself, so any caller could open any work route by asserting it had already
classified the request.

The exemption is now proof-carrying: it is honored only when a ready and valid
parent execution capsule shows a parent actually resolved this request. Without
that proof the classifier runs on ``--request`` exactly as it would have
without the flag, and a caller that supplies neither is rejected rather than
sailing through an unevaluated check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PARENT_EVIDENCE_NAME = "preflight.json"

# Case 3: --request-classified with no capsule and no request. Returning the
# unevaluated classification here is what made the original hole silent, so
# this text has to tell a reader hitting it from a hook exactly what to change.
MISSING_REQUEST_INTAKE_REASON = (
    "Route requires request intake evidence. `--request-classified` is honored only "
    "for a delegated worker whose parent left a ready and valid execution capsule; "
    "no such capsule was found, so the current request must be classified here. "
    'Pass --request "<USER_REQUEST>" with the real user request. '
    "If the caller only needs the document listing and label context and is not "
    "asserting request intake, use `--advisory` instead: it never satisfies a "
    "downstream gate."
)


NO_INTAKE_REASON = (
    'Route requires request intake evidence. Pass --request "<USER_REQUEST>" '
    "with the real current request. Only a delegated worker whose matching "
    "parent capsule is ready and valid may also use --request-classified."
)


def classified_intake_decision(
    command: str,
    request: str | None,
    request_classified: bool,
    classification_evidence: str,
    continuation_scope: str = "",
    *,
    project: Path | None = None,
    rules: Path | None = None,
    parent_evidence: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve the request classification and any reason to block the route.

    An empty block reason means the route may proceed. This is the single place
    that decides whether ``--request-classified`` skips classification, so
    ``workflow.py``, ``agent-preflight.py``, and ``workflow_dispatch.py`` cannot
    drift into three different answers for the same flag.
    """

    from workflow_request import (
        classified_route_block_reason,
        classify_request,
        route_block_reason,
    )

    if request_classified and not request:
        return None, MISSING_REQUEST_INTAKE_REASON

    exempt = False
    if request_classified:
        exempt, _reason = parent_capsule_exemption(
            project,
            rules,
            parent_evidence,
            command=command,
            request=request,
            continuation_scope=continuation_scope,
        )

    if not exempt and not request:
        # Without a capsule the flag proves nothing, so there is nothing left to
        # classify. Falling through with ``None`` here is the original hole: it
        # made every downstream check pass by having nothing to inspect.
        return None, MISSING_REQUEST_INTAKE_REASON if request_classified else NO_INTAKE_REASON

    classification = (
        None
        if exempt
        else classify_request(
            request or "",
            continuation_scope=continuation_scope,
        )
    )
    block_reason = route_block_reason(command, classification)
    if not block_reason and request_classified:
        block_reason = classified_route_block_reason(command, classification_evidence or "")
    return classification, block_reason or ""


def parent_evidence_path(project: Path | None, explicit: Path | None) -> Path | None:
    """Locate the parent preflight evidence that a capsule would sit beside.

    A worker writes its own isolated evidence, so the worker's ``--evidence``
    path is an output, never the parent's proof. The parent capsule always
    lives beside the project-default parent evidence unless a caller names a
    different parent explicitly.
    """

    if explicit is not None:
        return explicit.expanduser().absolute()
    if project is None:
        return None
    return project.expanduser().absolute() / ".tao" / PARENT_EVIDENCE_NAME


def parent_capsule_exemption(
    project: Path | None,
    rules: Path | None,
    parent_evidence: Path | None,
    *,
    command: str,
    request: str | None,
    continuation_scope: str = "",
) -> tuple[bool, str]:
    """Return whether a ready and valid parent capsule honors the exemption.

    The second element explains the refusal so callers can surface why the
    classifier ran instead of being skipped. Any unexpected failure refuses the
    exemption: an unreadable capsule is not proof that a parent resolved
    anything.
    """

    if parent_evidence is None or project is None or rules is None:
        return False, "no parent execution capsule location was resolvable"
    # Imported lazily: capsule validation pulls in git fingerprinting, and a
    # caller that never passes --request-classified must not pay for it.
    try:
        from agent_execution_capsule import read_execution_capsule, validate_execution_capsule
        from agent_execution_capsule_state import capsule_path_for_evidence
    except ImportError as error:  # pragma: no cover - broken install only
        return False, f"execution capsule validation is unavailable: {error}"

    capsule_path = capsule_path_for_evidence(parent_evidence)
    try:
        capsule = read_execution_capsule(capsule_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False, f"parent execution capsule is unreadable: {capsule_path}"
    if not capsule:
        return False, f"no parent execution capsule at {capsule_path}"

    preflight = _parent_preflight(parent_evidence)
    route = preflight.get("route") if isinstance(preflight, dict) else None
    if not isinstance(route, dict):
        return False, f"parent preflight evidence has no route manifest: {parent_evidence}"
    if str(route.get("command") or "") != command:
        return False, "current workflow command does not match the parent execution capsule"
    request_intake = preflight.get("request_intake")
    parent_request = (
        str(request_intake.get("request") or "")
        if isinstance(request_intake, dict)
        else ""
    )
    if not request or request != parent_request:
        return False, "current request does not match the parent execution capsule"
    parent_scope = (
        str(request_intake.get("continuation_scope") or "")
        if isinstance(request_intake, dict)
        else ""
    )
    if continuation_scope != parent_scope:
        return False, "current continuation scope does not match the parent execution capsule"

    try:
        failures = validate_execution_capsule(
            capsule,
            project=Path(project).expanduser().resolve(),
            rules=Path(rules).expanduser().resolve(),
            evidence_path=parent_evidence,
            route=route,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        return False, f"parent execution capsule could not be validated: {error}"
    if failures:
        return False, "; ".join(str(failure) for failure in failures)
    return True, ""


def _parent_preflight(parent_evidence: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(parent_evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
