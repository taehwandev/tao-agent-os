"""Run the legacy classifier beside the envelope, for diagnosis only.

The transition needs to know whether adapters emit envelopes that agree with
what the old classifier would have said. It must not need the old answer to
decide anything: a fallback that overrides the contract when the two disagree
would keep the natural-language path authoritative forever, which is the thing
being removed. So the envelope decides, and the comparison is recorded as
counts and enum labels with no request text in it.
"""

from __future__ import annotations

from typing import Any

from workflow_common import QUESTION_ROUTE_COMMANDS
from workflow_effect_policy import effect_decision, effective_effect
from workflow_intent_envelope import validate_envelope


AUTHORITY_ENVELOPE = "envelope"
AUTHORITY_LEGACY = "legacy_classifier"
WORK_ROUTE_ENVELOPE_REQUIRED = (
    "Work routes require a current, session-bound intent envelope. Without one, "
    "use `triage` or `ambiguity`; natural-language text and continuation scope "
    "cannot authorize work."
)

# The legacy classifier answers in response modes; the envelope answers in
# modes. This is the only mapping between the two vocabularies, and it exists
# for the comparison alone -- nothing decides anything through it.
_LEGACY_MODE_EQUIVALENT = {
    "work": "work",
    "answer_first": "answer",
    "clarify_first": "",
}


def dual_run_decision(
    command: str,
    envelope: dict[str, Any] | None,
    legacy_classification: dict[str, Any] | None,
    *,
    tool_effect: str = "read",
    approval: dict[str, Any] | None = None,
    request_fingerprint: str = "",
    runtime_session_id: str = "",
) -> dict[str, Any]:
    """Return the authoritative decision plus a content-free comparison.

    The caller's current request fingerprint and runtime session are passed
    straight through to the policy. Adding the binding check without threading
    it here left it dead on the only path that runs, so an envelope kept from
    earlier work still authorised whatever came next.
    """

    # `None` means no envelope was supplied; an empty object means one was and
    # could not be read. Only the first may fall back to the classifier --
    # treating both as absent let a broken adapter silently reach the path the
    # envelope is replacing.
    if envelope is None:
        return {
            "authority": AUTHORITY_LEGACY,
            "envelope_present": False,
            "failures": [],
            "comparison": {"status": "no_envelope"},
        }

    schema_failures = validate_envelope(envelope)
    binding_failures: list[str] = []
    if not schema_failures:
        if not request_fingerprint:
            binding_failures.append(
                "the current request fingerprint is required to bind the intent envelope"
            )
        if not runtime_session_id:
            binding_failures.append(
                "the current runtime session id is required to bind the intent envelope"
            )
    failures = schema_failures or binding_failures or effect_decision(
        command,
        envelope,
        tool_effect=tool_effect,
        approval=approval,
        request_fingerprint=request_fingerprint,
        runtime_session_id=runtime_session_id,
    )
    return {
        "authority": AUTHORITY_ENVELOPE,
        "envelope_present": True,
        "schema_valid": not schema_failures,
        "effective_effect": (
            None if schema_failures else effective_effect(
                command, envelope, tool_effect=tool_effect
            )
        ),
        "failures": failures,
        "comparison": _comparison(envelope, legacy_classification, bool(failures)),
    }


def route_intake_decision(
    command: str,
    envelope: dict[str, Any] | None,
    *,
    request_fingerprint: str,
    runtime_session_id: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return envelope-backed work classification or a fail-closed reason."""

    if envelope is None:
        if command in QUESTION_ROUTE_COMMANDS:
            return None, []
        return None, [WORK_ROUTE_ENVELOPE_REQUIRED]
    decision = dual_run_decision(
        command,
        envelope,
        None,
        request_fingerprint=request_fingerprint,
        runtime_session_id=runtime_session_id,
    )
    if decision["failures"]:
        return None, list(decision["failures"])
    return classification_from_envelope(envelope, decision), []


def classification_from_envelope(
    envelope: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any]:
    """Translate an accepted envelope into the shape route consumers read."""

    return {
        "clarity": "clear-scoped",
        "effort": "standard",
        "grill_me": False,
        "question_drill": False,
        "response_mode": envelope["mode"],
        "recommended_route": "",
        "continuation_scope_used": False,
        "reason": (
            "The runtime supplied an intent envelope; Tao verified its effects "
            f"against the route floor and reached `{decision['effective_effect']}`."
        ),
        "intent_envelope": decision,
    }


def _comparison(
    envelope: dict[str, Any],
    legacy: dict[str, Any] | None,
    envelope_refused: bool,
) -> dict[str, Any]:
    """Compare the two answers at enum level only.

    Nothing here reads request text, a target summary, or any free-form field:
    a diagnostic that carried content would put the prompt back into the state
    this contract keeps it out of.
    """

    if not legacy:
        return {"status": "no_legacy_result"}
    legacy_mode = str(legacy.get("response_mode") or "")
    envelope_mode = str(envelope.get("mode") or "")
    equivalent = _LEGACY_MODE_EQUIVALENT.get(legacy_mode, "")
    if envelope_refused:
        # A refusal is an outcome, not a missing answer. Blanking the mode made
        # a refused envelope and a clarify_first classifier read as `agree`
        # through two empty strings, hiding the cases worth looking at.
        status = "envelope_refused"
    elif not equivalent:
        status = "legacy_withheld"
    elif equivalent == envelope_mode:
        status = "agree"
    else:
        status = "disagree"
    return {
        "status": status,
        "legacy_response_mode": legacy_mode,
        "envelope_mode": envelope_mode,
        "envelope_refused": envelope_refused,
    }
