"""What a request is allowed to do, decided independently of what it claims.

The runtime states the effects it believes it needs. That statement is one
input, never the answer: the route it selected has a floor of its own, and the
tool actually invoked has an effect the caller does not get to redescribe. The
effective risk is the union of all three, so a claim can raise the bar and can
never lower it. That asymmetry is the whole safety argument -- a self-asserted
`read` next to a release route is a release, and is refused without approval.
"""

from __future__ import annotations

from typing import Any

from workflow_intent_envelope import EFFECT_RANK, highest_effect, validate_envelope


# The floor each route carries whatever the caller says. Answer- and
# review-shaped routes read; ordinary code routes write locally; commit routes
# touch history; shipping routes reach outside the machine.
ROUTE_MINIMUM_EFFECT = {
    "ambiguity": "read",
    "analysis": "read",
    "docs-review": "read",
    "retrospective": "read",
    "review": "read",
    "triage": "read",
    "plan": "read",
    "planning": "read",
    "bugfix": "local_write",
    "build": "local_write",
    "code-simplify": "local_write",
    "docs": "local_write",
    "feature": "local_write",
    "multi-agent": "local_write",
    "prd": "local_write",
    "product": "local_write",
    "refactor": "local_write",
    "spec": "local_write",
    "task": "local_write",
    "test": "local_write",
    "webperf": "local_write",
    "workflow-setup": "local_write",
    "commit": "git_write",
    "git_commit": "git_write",
    "release": "external_write",
    "ship": "external_write",
}
# Effects at or above this rank are not self-serviceable: they need an approval
# bound to this exact request, target and effect.
APPROVAL_REQUIRED_FROM = "git_write"

_UNKNOWN_ROUTE_FLOOR = "external_write"


def route_minimum_effect(command: str) -> str:
    """Return the floor for a route, defaulting an unknown route to the top.

    An unrecognised route is treated as the most dangerous rather than the
    least, so adding a route without declaring its floor fails closed.
    """

    return ROUTE_MINIMUM_EFFECT.get(command, _UNKNOWN_ROUTE_FLOOR)


def effective_effect(
    command: str,
    envelope: dict[str, Any],
    *,
    tool_effect: str = "read",
) -> str:
    """Return the union of the claimed, the route's and the tool's effect."""

    return highest_effect(
        [
            highest_effect(envelope.get("requested_effects")),
            route_minimum_effect(command),
            tool_effect if tool_effect in EFFECT_RANK else _UNKNOWN_ROUTE_FLOOR,
        ]
    )


def effect_decision(
    command: str,
    envelope: dict[str, Any],
    *,
    tool_effect: str = "read",
    approval: dict[str, Any] | None = None,
    request_fingerprint: str = "",
    runtime_session_id: str = "",
) -> list[str]:
    """Return every reason this request may not proceed at its effective effect.

    ``request_fingerprint`` and ``runtime_session_id`` are the caller's own view
    of what is running now. An envelope naming a different request or session is
    a judgement about other work, so it is refused rather than applied here.
    """

    # Validate before reading anything. Every check below is a condition the
    # envelope states about itself, so acting on an unvalidated one recreates
    # the hole this contract exists to close: an envelope that simply omits
    # `ambiguity` or misspells it silently passed the blocking check.
    schema_failures = validate_envelope(envelope)
    if schema_failures:
        return schema_failures

    failures: list[str] = []
    failures.extend(_binding_failures(envelope, request_fingerprint, runtime_session_id))
    effect = effective_effect(command, envelope, tool_effect=tool_effect)
    # Prohibiting an effect prohibits everything at least as dangerous.
    # Comparing names for equality let a request that forbade external_write
    # proceed at destructive, which is strictly worse than what it refused.
    prohibited = highest_effect(envelope.get("prohibited_effects"))
    if envelope.get("prohibited_effects") and (
        EFFECT_RANK[effect] >= EFFECT_RANK[prohibited]
    ):
        failures.append(
            f"the effective effect `{effect}` is at or above the prohibited "
            f"`{prohibited}`; the selected route or the invoked tool requires it"
        )
    if envelope.get("ambiguity") == "blocking":
        failures.append(
            "the runtime reported the request as ambiguous; resolve it before work"
        )
    if envelope.get("mode") == "answer" and EFFECT_RANK[effect] > EFFECT_RANK["read"]:
        failures.append(
            f"answer mode cannot reach the effective effect `{effect}`"
        )
    failures.extend(_approval_failures(command, envelope, effect, approval))
    return failures


def _binding_failures(
    envelope: dict[str, Any],
    request_fingerprint: str,
    runtime_session_id: str,
) -> list[str]:
    """Reject an envelope that describes a different request or session.

    Without this an envelope kept from earlier work authorises whatever runs
    next, which is a replay of a judgement nobody made about the current task.
    """

    failures: list[str] = []
    if request_fingerprint and envelope.get("request_fingerprint") != request_fingerprint:
        failures.append(
            "the intent envelope describes a different request; the binding covers "
            "the exact --request, --continuation-scope, and classification flags of "
            "this call, so recompute it with agent-hook.py fingerprint using the "
            "same arguments instead of asking the user to reword the request"
        )
    if runtime_session_id and envelope.get("runtime_session_id") != runtime_session_id:
        failures.append("the intent envelope was issued by a different runtime session")
    return failures


def _approval_failures(
    command: str,
    envelope: dict[str, Any],
    effect: str,
    approval: dict[str, Any] | None,
) -> list[str]:
    if EFFECT_RANK[effect] < EFFECT_RANK[APPROVAL_REQUIRED_FROM]:
        return []
    if not isinstance(approval, dict):
        return [
            f"the effective effect `{effect}` requires a recorded user approval; "
            "an envelope cannot approve itself"
        ]
    # The approval is bound to one request, one target and one effect ceiling.
    # Without all three an approval for one deployment would authorise the next.
    if approval.get("request_fingerprint") != envelope.get("request_fingerprint"):
        return ["the recorded approval is bound to a different request"]
    if str(approval.get("target_summary") or "") != str(envelope.get("target_summary") or ""):
        return ["the recorded approval is bound to a different target"]
    approved = str(approval.get("effect") or "")
    if approved not in EFFECT_RANK:
        return ["the recorded approval names no known effect"]
    if EFFECT_RANK[approved] < EFFECT_RANK[effect]:
        return [
            f"the recorded approval covers `{approved}` but the effective effect "
            f"is `{effect}`"
        ]
    # The route binding is required, not defaulted. Filling a missing `command`
    # in from the current call made an unbound approval look bound, so one
    # granted for `release` was replayed on `ship`.
    if str(approval.get("command") or "") != command:
        return ["the recorded approval is bound to a different route"]
    return []
