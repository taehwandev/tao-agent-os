"""Step functions for Tao Agent OS finish checks."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from agent_delegation_plan import validate_delegation_plan_evidence
from agent_execution_capsule import capsule_path_for_evidence, read_execution_capsule
from agent_execution_capsule_state import (
    execution_capsule_binding_fingerprint,
    git_states_for_paths,
    is_sha256,
    preflight_snapshot_binding_fingerprint,
)
from agent_execution_capsule_validation import (
    validate_preflight_snapshot,
    validate_source_docs_binding,
)
from agent_finish_common import add_gate_signal, append_unique
from agent_finish_gate_policy import SOURCE_DOCS_GATE, validate_gate_evidence
from agent_finish_documentation import documented_required_doc_updates
from agent_review_attestation import REVIEW_HOOK_GATE, ReviewAttestation
from agent_route_state import preflight_evidence_sha256, request_fingerprint, route_fingerprint
from workflow_common import QUESTION_ROUTE_COMMANDS
from workflow_request import (
    classified_route_block_reason,
    classification_evidence_allows_command_work,
    classification_evidence_requires_clarification,
)
from workflow_request_patterns import GRILL_ME_REQUEST_PATTERNS


LEGACY_GRILL_ME_FLAGS = (
    "grill_me: true",
    "grill_me true",
    "question_drill: true",
    "question_drill true",
)
GRILL_ME_EVIDENCE_GATES = (
    "grill-me if needed",
    "grill-me",
    "question drill if needed",
    "ask blockers",
    "question drill",
    "clarification drill",
)


def enforce_review_hook_attestation(
    *,
    route: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    gate_evidence: dict[str, str],
    gate_evidence_ledger: dict[str, Any],
    failures: list[str],
) -> None:
    """Remove a ledger-only review success unless the real hook attested it."""

    if REVIEW_HOOK_GATE not in (route.get("gates") or []):
        return
    if REVIEW_HOOK_GATE not in gate_evidence:
        return
    entry_fields = (gate_evidence_ledger.get("entry_fields") or {}).get(
        REVIEW_HOOK_GATE, {}
    )
    source = (gate_evidence_ledger.get("sources") or {}).get(REVIEW_HOOK_GATE, "")
    attestation_failures = ReviewAttestation.failures(
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        route=route,
        ledger_fields=entry_fields,
        ledger_source=source,
    )
    gate_evidence_ledger["review_attestation"] = {
        "valid": not attestation_failures,
        "failures": attestation_failures,
    }
    if not attestation_failures:
        return
    gate_evidence.pop(REVIEW_HOOK_GATE, None)
    failures.extend(attestation_failures)


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    project = args.project.resolve()
    rules = args.rules.resolve()
    evidence_path = (
        args.evidence.resolve()
        if args.evidence
        else project / ".tao" / "preflight.json"
    )
    output_path = (
        args.output.resolve()
        if args.output
        else project / ".tao" / "finish.json"
    )
    return project, rules, evidence_path, output_path


def read_preflight(evidence_path: Path, failures: list[str]) -> dict[str, Any]:
    if not evidence_path.exists():
        failures.append(f"missing preflight evidence at {evidence_path}")
        return {}
    try:
        return json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"preflight evidence is not valid JSON: {error}")
        return {}


def check_required_gates(
    route: dict[str, Any],
    gate_evidence: dict[str, str],
    gate_signals: list[dict[str, str]],
    failures: list[str],
    delegation_plan: dict[str, Any] | None = None,
    *,
    allowed_skill_ids: set[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    required_gates = route.get("gates") or []
    if not required_gates:
        failures.append("preflight evidence is missing route gates")
    missed_gates: list[str] = []
    for gate in required_gates:
        evidence = gate_evidence.get(gate, "")
        if evidence:
            add_gate_signal(gate_signals, "SUCCESS", gate, "executed", evidence)
        else:
            append_unique(missed_gates, gate)
            add_gate_signal(gate_signals, "FAIL", gate, "missed", "missing evidence")

    if missed_gates:
        failures.append("missing required gate evidence: " + ", ".join(missed_gates))

    gate_policy_failures = validate_gate_evidence(
        gate_evidence,
        required_gates,
        route=route,
        allowed_skill_ids=allowed_skill_ids,
    )
    gate_policy_failures.extend(
        validate_delegation_plan_evidence(required_gates, gate_evidence, delegation_plan or {})
    )
    for failure in gate_policy_failures:
        add_gate_signal(gate_signals, "FAIL", "gate evidence policy", "failed", failure)
        failures.append(failure)
    return required_gates, missed_gates, gate_policy_failures


def route_gate_capsule_binding_failures(
    route: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    gate_evidence: dict[str, str],
    gate_evidence_ledger: dict[str, Any],
) -> list[str]:
    """Bind every completed gate to one capsule and validate source docs when required."""

    required_gates = [str(gate) for gate in (route.get("gates") or [])]
    if not required_gates:
        return []
    capsule = read_execution_capsule(capsule_path_for_evidence(evidence_path))
    preflight = read_preflight(evidence_path, failures=[])
    snapshot = preflight.get("execution_snapshot") if isinstance(preflight, dict) else None
    capsule_binding = _current_execution_capsule_binding(
        capsule,
        route=route,
        preflight=preflight,
        evidence_path=evidence_path,
    )
    snapshot_binding = _current_preflight_snapshot_binding(
        snapshot,
        route=route,
        preflight=preflight,
    )
    failures: list[str] = []
    expected_binding: str | None = None
    if SOURCE_DOCS_GATE in required_gates:
        documented_updates = documented_required_doc_updates(
            evidence_path=evidence_path,
            route=route,
        )
        if capsule_binding:
            capsule_failures = validate_source_docs_binding(
                capsule,
                project=project,
                rules=rules,
                evidence_path=evidence_path,
                route=route,
                documented_updates=documented_updates,
            )
            if not capsule_failures:
                expected_binding = capsule_binding
            elif snapshot_binding:
                failures = validate_preflight_snapshot(
                    snapshot if isinstance(snapshot, dict) else {},
                    project=project,
                    evidence_path=evidence_path,
                    rules=rules,
                    route=route,
                    documented_updates=documented_updates,
                )
                if not failures:
                    expected_binding = snapshot_binding
            else:
                failures = capsule_failures
        else:
            failures = validate_preflight_snapshot(
                snapshot if isinstance(snapshot, dict) else {},
                project=project,
                evidence_path=evidence_path,
                rules=rules,
                route=route,
                documented_updates=documented_updates,
            )
            if not failures:
                expected_binding = snapshot_binding
        if failures:
            return list(dict.fromkeys(failures))
    expected_binding = expected_binding or capsule_binding or snapshot_binding
    if not expected_binding:
        return ["execution capsule or preflight snapshot is not ready for route gate evidence"]

    bindings = gate_evidence_ledger.get("capsule_bindings") or {}
    for gate in required_gates:
        if not gate_evidence.get(gate):
            continue
        if bindings.get(gate) != expected_binding:
            failures.append(
                f"gate evidence for {gate} is not bound to the current execution capsule"
            )
    return list(dict.fromkeys(failures))


def _current_execution_capsule_binding(
    capsule: dict[str, Any],
    *,
    route: dict[str, Any],
    preflight: dict[str, Any],
    evidence_path: Path,
) -> str | None:
    """Return a capsule binding only when it belongs to this parent start.

    The finish check deliberately avoids full capsule validation here: that
    validation streams mutable worktree state and is only needed for worker
    reuse.  Gate binding needs the immutable parent-start identity instead.
    A capsule written for a prior serial request can otherwise be structurally
    valid yet select the wrong binding for routes without ``source docs``.
    """

    binding = execution_capsule_binding_fingerprint(capsule)
    if not binding:
        return None
    if capsule.get("route_fingerprint") != route_fingerprint(route):
        return None
    request_intake = preflight.get("request_intake")
    if not isinstance(request_intake, dict):
        request_intake = {}
    if capsule.get("request_fingerprint") != request_fingerprint(request_intake):
        return None
    preflight_record = capsule.get("preflight_evidence")
    if not isinstance(preflight_record, dict):
        return None
    if preflight_record.get("filename") != evidence_path.name:
        return None
    try:
        current_hash = preflight_evidence_sha256(evidence_path)
    except OSError:
        return None
    if preflight_record.get("sha256") != current_hash:
        return None
    return binding


def _current_preflight_snapshot_binding(
    snapshot: Any,
    *,
    route: dict[str, Any],
    preflight: dict[str, Any],
) -> str | None:
    """Return the current serial binding without revalidating mutable docs."""

    if not isinstance(snapshot, dict):
        return None
    binding = preflight_snapshot_binding_fingerprint(snapshot)
    if not binding:
        return None
    if snapshot.get("route_fingerprint") != route_fingerprint(route):
        return None
    request_intake = preflight.get("request_intake")
    if not isinstance(request_intake, dict):
        request_intake = {}
    if snapshot.get("request_fingerprint") != request_fingerprint(request_intake):
        return None
    return binding


def check_request_intake(
    route: dict[str, Any],
    request_intake: dict[str, Any],
    request_classification: dict[str, Any],
    gate_evidence: dict[str, str],
    gate_signals: list[dict[str, str]],
    missed_gates: list[str],
    failures: list[str],
) -> bool:
    request_classified = bool(route.get("request_classified") or request_intake.get("request_classified"))
    question_resolution_route = route.get("command") in QUESTION_ROUTE_COMMANDS
    command = str(route.get("command") or "")
    classification_evidence = request_intake.get("classification_evidence", "")

    if request_classified and not request_intake.get("classification_evidence"):
        append_unique(missed_gates, "request intake")
        add_gate_signal(
            gate_signals,
            "FAIL",
            "request intake",
            "missed",
            "--request-classified used without classification evidence",
        )
        failures.append("--request-classified used without classification evidence")

    if (
        request_classified
        and not question_resolution_route
    ):
        block_reason = classified_route_block_reason(
            command,
            classification_evidence,
        )
    else:
        block_reason = ""
    if block_reason:
        append_unique(missed_gates, "request intake")
        add_gate_signal(
            gate_signals,
            "FAIL",
            "request intake",
            "failed",
            block_reason,
        )
        failures.append(block_reason)

    grill_me_required = grill_me_is_required(
        route,
        request_intake,
        request_classification,
    )
    grill_me_gate = next((gate for gate in GRILL_ME_EVIDENCE_GATES if gate_evidence.get(gate)), "")
    if grill_me_required and grill_me_gate:
        evidence = gate_evidence[grill_me_gate]
        evidence_failures = validate_grill_me_skill_evidence(evidence)
        if evidence_failures:
            append_unique(missed_gates, "grill-me")
            for failure in evidence_failures:
                add_gate_signal(gate_signals, "FAIL", "grill-me", "failed", failure)
                failures.append(failure)
        else:
            add_gate_signal(
                gate_signals,
                "SUCCESS",
                "grill-me",
                "executed",
                f"{grill_me_gate}: {evidence}",
            )
    elif grill_me_required:
        append_unique(missed_gates, "grill-me")
        add_gate_signal(
            gate_signals,
            "FAIL",
            "grill-me",
            "missed",
            "request classification required the Grill-Me protocol but no Grill-Me evidence was provided",
        )
        failures.append(
            "Grill-Me protocol was required by request classification but no Grill-Me gate evidence was provided"
        )
    return grill_me_required


def grill_me_is_required(
    route: dict[str, Any],
    request_intake: dict[str, Any],
    request_classification: dict[str, Any],
) -> bool:
    command = str(route.get("command") or "")
    classification_evidence = request_intake.get("classification_evidence", "")
    return (
        _classification_requires_grill_me(request_classification)
        or (
            classification_evidence_requires_clarification(classification_evidence)
            and not classification_evidence_allows_command_work(
                command,
                classification_evidence,
            )
        )
        or grill_me_requested(_request_text(request_intake, request_classification))
    )


def check_read_only_execution(
    preflight: dict[str, Any],
    project: Path,
    failures: list[str],
    *,
    read_only: bool,
    state_reader: Any = git_states_for_paths,
) -> None:
    """Hold a read-only run to the claim that bought it the VibeGuard skip.

    Declaring ``--read-only`` disables the safety audit for the whole
    lifecycle, and the declaration is made at start -- before any edit has
    happened. Without this check the flag is an unverified promise: an agent can
    declare a non-mutating run on any route, edit freely, and finish with no
    audit. Compare the worktree against the state start recorded and fail closed
    when it moved.
    """

    if not read_only:
        return
    recorded = preflight.get("read_only_execution_state")
    if not (
        isinstance(recorded, dict)
        and set(recorded) == {"project", "rules"}
        and all(_is_workspace_state(recorded[root]) for root in ("project", "rules"))
    ):
        failures.append(
            "read-only execution is missing its strong start-time workspace fingerprint "
            "for the project and rules roots; rerun start before finishing"
        )
        return
    rules_value = preflight.get("rules")
    if not isinstance(rules_value, str) or not rules_value.strip():
        failures.append(
            "read-only execution cannot be verified without the rules root recorded at start"
        )
        return
    try:
        current_project, current_rules = state_reader(project, Path(rules_value))
    except (OSError, RuntimeError, ValueError):
        failures.append(
            "read-only execution workspace state could not be verified; "
            "Git and directory inspection errors fail closed"
        )
        return
    checked = [("project", current_project), ("rules", current_rules)]
    try:
        if Path(rules_value).resolve() == project.resolve():
            # One checkout serving as both roots produces one state, so keep
            # the report to a single drift rather than the same one twice.
            checked = checked[:1]
    except OSError:
        pass
    for root, current in checked:
        recorded_root = recorded[root]
        if (
            current["head"] != recorded_root["head"]
            or current["worktree_fingerprint"]
            != recorded_root["worktree_fingerprint"]
        ):
            failures.append(
                f"read-only execution was declared but the {root} root changed after start; "
                "read-only skips VibeGuard, so rerun the lifecycle without --read-only"
            )


def _is_workspace_state(state: Any) -> bool:
    return (
        isinstance(state, dict)
        and set(state) == {"head", "worktree_fingerprint", "worktree_signature"}
        and isinstance(state.get("head"), str)
        and bool(state["head"])
        and is_sha256(state.get("worktree_fingerprint"))
        and is_sha256(state.get("worktree_signature"))
    )


def check_preflight_vibeguard(
    preflight: dict[str, Any],
    failures: list[str],
    *,
    read_only: bool = False,
) -> None:
    preflight_vibeguard_command = preflight.get("vibeguard") or {}
    preflight_vibeguard = preflight_vibeguard_command.get("overall") or {}
    if not preflight_vibeguard:
        failures.append("preflight evidence is missing VibeGuard result")
    elif preflight_vibeguard_command.get("skipped") and not read_only:
        failures.append("preflight VibeGuard was skipped without read-only execution mode")
    elif preflight_vibeguard_command.get("returncode") != 0:
        failures.append("preflight VibeGuard audit failed")
    elif preflight_vibeguard.get("status") == "unknown":
        failures.append("preflight VibeGuard overall status could not be parsed")


def grill_me_requested(text: str) -> bool:
    lowered = text.lower()
    return any(flag in lowered for flag in LEGACY_GRILL_ME_FLAGS) or any(
        re.search(pattern, lowered) for pattern in GRILL_ME_REQUEST_PATTERNS
    )


def _classification_requires_grill_me(request_classification: dict[str, Any]) -> bool:
    return _truthy(request_classification.get("grill_me")) or _truthy(
        request_classification.get("question_drill")
    )


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def validate_grill_me_skill_evidence(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    names_skill = any(
        phrase in text
        for phrase in ("grill-me", "grill me", "grillme", "/grilling", "grilling", "\uadf8\ub9b4\ubbf8")
    )
    names_session = any(
        phrase in text
        for phrase in (
            "skill",
            "/grilling",
            "grilling",
            "session",
            "started",
            "ran",
            "used",
            "invocation",
            "invoked",
            "output",
            "result",
        )
    )
    names_outcome = any(
        phrase in text
        for phrase in (
            "completed",
            "asked",
            "answered",
            "blocker",
            "questions",
            "one question",
            "recommended answer",
            "feedback",
            "decisions",
            "resolved",
            "no blockers",
            "clarified",
        )
    )
    if names_skill and names_session and names_outcome:
        return []
    return [
        "Grill-Me evidence must name the Grill-Me protocol, skill, or /grilling session and its output; "
        "unstructured manual blocker questions alone are not enough"
    ]


def validate_recorded_grill_me_evidence(
    route: dict[str, Any],
    gate_evidence: dict[str, str],
) -> list[str]:
    """Reject malformed Grill-Me evidence before it enters the gate ledger.

    Missing evidence remains a finish-check concern because agents record gates
    incrementally. Once a Grill-Me gate is submitted for a route whose request
    classification requires the protocol, however, it must already satisfy the
    same evidence contract enforced at finish.
    """

    request_classification = route.get("request_classification") or {}
    if not _classification_requires_grill_me(request_classification):
        return []
    for gate in GRILL_ME_EVIDENCE_GATES:
        evidence = gate_evidence.get(gate, "")
        if evidence:
            return validate_grill_me_skill_evidence(evidence)
    return []


question_drill_requested = grill_me_requested
validate_grill_me_service_evidence = validate_grill_me_skill_evidence


def _request_text(request_intake: dict[str, Any], request_classification: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            request_intake.get("request"),
            request_intake.get("classification_evidence"),
            request_classification.get("request"),
        )
        if value
    )
