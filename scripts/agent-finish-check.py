#!/usr/bin/env python3
"""Verify Tao Agent OS gate evidence before final report, commit, or handoff."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_delegation_plan import read_delegation_plan
from agent_execution_capsule_state import contained_doc_path, doc_hash_record
from agent_global_lessons import state_home, write_retrospective_candidate
from agent_runtime_session import runtime_session
from agent_skill_catalog import canonical_skill_ids
from agent_finish_check_steps import (
    check_preflight_vibeguard,
    check_read_only_execution,
    check_request_intake,
    check_required_gates,
    enforce_review_hook_attestation,
    read_preflight,
    resolve_paths,
    route_gate_capsule_binding_failures,
)
from agent_finish_common import (
    add_gate_signal,
    display_signal,
    requires_retrospective,
    write_json,
)
from agent_finish_final_checks import run_final_checks
from agent_gate_evidence import (
    incomplete_gate_evidence_failures,
    merge_gate_evidence_from_ledger,
)
from agent_repair_ledger import failure_signature, record_failure_checkpoints
from agent_review_attestation import REVIEW_HOOK_GATE
from agent_skill_followup import skill_followup_failures


def build_parser(tao_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check route gate evidence, validation, diff hygiene, and VibeGuard."
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--rules", type=Path, default=tao_root)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-vibeguard-review",
        help="required reason when final VibeGuard is not Ready",
    )
    return parser


def build_result(
    *,
    tao_root: Path,
    project: Path,
    rules: Path,
    evidence_path: Path,
    args: argparse.Namespace,
    preflight: dict[str, Any],
    required_gates: list[str],
    gate_evidence: dict[str, str],
    gate_signals: list[dict[str, str]],
    missed_gates: list[str],
    gate_evidence_ledger: dict[str, Any],
    delegation_plan: dict[str, Any],
    grill_me_required: bool,
    retrospective_required: bool,
    validate: dict[str, Any],
    diff_check: dict[str, Any],
    vibeguard: dict[str, Any],
    retrospective_lesson: dict[str, Any],
    skill_followup: list[str],
    failures: list[str],
) -> dict[str, Any]:
    route = preflight.get("route") or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tao_root": str(tao_root),
        "project": str(project),
        "rules": str(rules),
        "preflight_evidence": str(evidence_path),
        "request_intake": preflight.get("request_intake") or {},
        "execution_mode": preflight.get("execution_mode") or {},
        "request_classification": route.get("request_classification") or {},
        "required_gates": required_gates,
        "gate_evidence": gate_evidence,
        "gate_evidence_ledger": gate_evidence_ledger,
        "gate_signals": gate_signals,
        "missed_gates": missed_gates,
        "agent_delegation_plan": delegation_plan,
        "grill_me_required": grill_me_required,
        "question_drill_required": grill_me_required,
        "retrospective_required": retrospective_required,
        "allow_vibeguard_review": args.allow_vibeguard_review,
        "validate": validate,
        "diff_check": diff_check,
        "vibeguard": vibeguard,
        "retrospective_lesson": retrospective_lesson,
        "skill_followup": {
            "pending": bool(skill_followup),
            "failures": skill_followup,
        },
        "failures": failures,
    }


def print_result(output_path: Path, required_gates: list[str], overall: str, result: dict[str, Any]) -> None:
    print(f"Finish evidence: {output_path}")
    print(f"Required gates: {required_gates}")
    print(f"VibeGuard overall: {overall}")
    # "Retrospective required: false" named the failure-repair loop, and every
    # clean closeout printed it directly after the route had required a
    # `retrospective check` gate -- all 27 routes require one. It read as "no
    # retrospective was needed", which is the opposite of what just happened,
    # and it misled the agent maintaining this file into reporting the closeout
    # retrospective as missing. The loop is named, and the check that did run
    # says so on its own line.
    print(
        "Retrospective repair required: "
        f"{str(result['retrospective_required']).lower()}"
    )
    if not result["retrospective_required"]:
        print(
            "Closeout retrospective: recorded by the required `retrospective "
            "check` gate"
        )
    lesson = result.get("retrospective_lesson") or {}
    if lesson.get("created"):
        print(f"Retrospective lesson candidate: {lesson.get('relative_path')}")
    elif result["retrospective_required"]:
        print(f"Retrospective lesson candidate: {lesson.get('reason', 'not_created')}")
    print("Gate signals:")
    for gate_signal in result["gate_signals"]:
        print(
            f"- {display_signal(gate_signal['signal'])} | gate: {gate_signal['gate']} | "
            f"status: {gate_signal['status']}"
        )


def process_failure_learning(
    *,
    preflight: dict[str, Any],
    missed_gates: list[str],
    gate_policy_failures: list[str],
    gate_signals: list[dict[str, str]],
    failures: list[str],
    rules: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    repair_required_failures = [
        failure
        for failure in failures
        if not _is_intrinsic_analysis_workspace_drift(failure)
    ]
    retrospective_required = requires_retrospective(
        missed_gates,
        gate_policy_failures,
        repair_required_failures,
    )
    if retrospective_required:
        if any(
            failure.startswith(
                (
                    "execution capsule required doc size changed: ",
                    "execution capsule required doc hash changed: ",
                )
            )
            for failure in failures
        ):
            failures.append(
                _required_doc_drift_recovery(rules or Path('.'), failures)
            )
        failures.append(
            "retrospective repair is required before final report, commit, release, or handoff; "
            "record the correction plan, improve the owning Tao Agent OS doc, hook, validator, or "
            "test, verify that repair, then resume the first failed checkpoint. Stop if the same "
            "failure remains or the repair is unsafe or ambiguous"
        )
    lesson = write_retrospective_candidate(
        {
            "missed_gates": missed_gates,
            "gate_signals": gate_signals,
            "retrospective_required": retrospective_required,
            "occurrence_id": str(preflight.get("agent_run_id") or ""),
        }
    )
    return retrospective_required, lesson


def _is_intrinsic_analysis_workspace_drift(failure: str) -> bool:
    """Separate stale analysis evidence from a runtime defect or write bypass."""

    return (
        failure.startswith("read-only execution was declared but the ")
        and " root changed after start; " in failure
        and "the analysis route is intrinsically read-only; wait for concurrent writers "
        "to settle, then rerun start and finish with refreshed workspace fingerprints"
        in failure
    )


def _report_finish_failures(
    *,
    failures: list[str],
    gate_policy_failures: list[str],
    required_gates: list[str],
    missed_gates: list[str],
    gate_evidence: dict[str, str],
    evidence_path: Path,
    preflight: dict[str, Any],
    pending_closeout: bool = False,
) -> int:
    if not failures:
        return 0
    try:
        policy_failed_gates = [
            gate
            for gate in required_gates
            if gate_evidence.get(gate, "").strip()
            and any(gate.lower() in failure.lower() for failure in gate_policy_failures)
        ]
        checkpoint_signatures = {
            gate: failure_signature([f"missing required gate evidence: {gate}"])
            for gate in missed_gates
        }
        for gate in policy_failed_gates:
            gate_failures = [
                failure
                for failure in gate_policy_failures
                if gate.lower() in failure.lower()
            ]
            checkpoint_signatures[gate] = failure_signature(
                gate_failures or [f"gate policy failure: {gate}"]
            )
        checkpoint_signatures["finish"] = failure_signature(failures)
        record_failure_checkpoints(
            evidence_path=evidence_path,
            preflight=preflight,
            checkpoints=[*missed_gates, *policy_failed_gates, "finish"],
            signature=failure_signature(failures),
            checkpoint_signatures=checkpoint_signatures,
        )
    except (OSError, ValueError):
        pass
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 3 if pending_closeout else 1


def process_skill_followup(
    *,
    preflight: dict[str, Any],
    gate_signals: list[dict[str, str]],
    failures: list[str],
    gate_evidence_ledger: dict[str, Any] | None = None,
) -> list[str]:
    """Block only a clean finish whose current occurrence needs follow-up."""

    if failures:
        return []
    try:
        pending = skill_followup_failures(
            state_root=state_home(),
            preflight=preflight,
            gate_evidence_ledger=gate_evidence_ledger,
        )
    except (OSError, ValueError):
        pending = ["skill follow-up state unavailable"]
    for failure in pending:
        add_gate_signal(
            gate_signals,
            "FAIL",
            "skill learning follow-up",
            "failed",
            failure,
        )
        failures.append(failure)
    return pending


def process_closeout_learning(
    *,
    preflight: dict[str, Any],
    missed_gates: list[str],
    gate_policy_failures: list[str],
    gate_signals: list[dict[str, str]],
    failures: list[str],
    rules: Path | None = None,
    gate_evidence_ledger: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], list[str]]:
    """Keep failure learning and successful closeout follow-up in one boundary."""

    retrospective_required, retrospective_lesson = process_failure_learning(
        preflight=preflight,
        missed_gates=missed_gates,
        gate_policy_failures=gate_policy_failures,
        gate_signals=gate_signals,
        failures=failures,
        rules=rules,
    )
    skill_followup = process_skill_followup(
        preflight=preflight,
        gate_signals=gate_signals,
        failures=failures,
        gate_evidence_ledger=gate_evidence_ledger,
    )
    return retrospective_required, retrospective_lesson, skill_followup


def record_session_finished(project: Path, session: dict[str, Any]) -> None:
    """Leave a per-session record that this session finished cleanly.

    `finish.json` is one shared file. A later finish -- another runtime, another
    session, a re-verification run -- overwrites it, which erases the proof that
    *this* session completed and leaves the Claude Stop gate blocking work that
    was properly finished. Stamping the session was not enough on its own; the
    record has to be one that a later run cannot clobber.
    """
    session_id = session.get("session_id") if isinstance(session, dict) else None
    if not session_id:
        return
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")
    if not safe:
        return
    marker = project / ".tao" / "claude-pretool-gate" / f"{safe}.finished"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
    except OSError:
        pass


def effective_read_only(
    preflight: dict[str, Any],
    route: dict[str, Any],
) -> bool:
    return bool(
        (preflight.get("execution_mode") or {}).get("read_only")
        or route.get("command") == "analysis"
    )


_DRIFT_PREFIXES = (
    "execution capsule required doc size changed: ",
    "execution capsule required doc hash changed: ",
)


def _required_doc_drift_recovery(rules: Path, failures: list[str]) -> str:
    """Name the receipt fields the validator actually requires, with their values.

    The previous text asked for `repair_evidence` and `resume_checkpoint`, which
    the receipt validator never reads, so an agent that followed it exactly could
    never clear the drift and reasonably concluded the check was unsatisfiable.
    The four fields below are the ones that are read, and the final bytes are
    computed here so recovery does not depend on reading the validator source.
    """

    drifted = sorted(
        {
            failure.split(": ", 1)[1]
            for failure in failures
            if failure.startswith(_DRIFT_PREFIXES) and ": " in failure
        }
    )
    lines = [
        "required-doc drift recovery: record one documentation SUCCESS entry per required "
        "doc with the exact route-relative required doc target. Use decision=updated when "
        "this run intentionally changed the document. Use decision=unchanged when another "
        "session changed it while this run was working: re-read the document at its current "
        "bytes first, and say why the work still conforms. Do not claim decision=updated for "
        "a change this run did not make. A document this route already lists as required "
        "needs the receipt fields artifact_receipt_version=1, baseline_sha256 (the snapshot "
        "hash this failure compared against), final_sha256 and final_size_bytes (the current "
        "bytes reported below). A document outside this route's required_docs instead needs "
        "repair_evidence and resume_checkpoint: run repair-verify for the actual failed "
        "checkpoint first. Either way this binds the verified final document without "
        "bypassing the snapshot check"
    ]
    for relative in drifted:
        current = _current_doc_record(rules, relative)
        if current:
            lines.append(
                f"required-doc drift recovery for {relative}: "
                f"final_sha256={current['sha256']} "
                f"final_size_bytes={current['size_bytes']}"
            )
        else:
            # Naming the document still matters when its bytes cannot be read:
            # the agent needs to know which receipt to record even if it has to
            # compute the values itself.
            lines.append(
                f"required-doc drift recovery for {relative}: current bytes are "
                "unreadable from the rules root, so compute final_sha256 and "
                "final_size_bytes from the document itself"
            )
    return "; ".join(lines)


def _current_doc_record(rules: Path, relative: str) -> dict[str, Any] | None:
    # The containment check compares resolved paths, so a caller that passed a
    # relative rules root would see every doc "escape" it and lose the byte
    # values this guidance exists to hand over.
    try:
        return doc_hash_record(relative, contained_doc_path(rules.resolve(), relative))
    except (OSError, ValueError):
        return None


def _validated_gate_evidence(
    *,
    route: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    failures: list[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    gate_evidence, ledger = merge_gate_evidence_from_ledger(
        route=route,
        evidence_path=evidence_path,
    )
    failures.extend(incomplete_gate_evidence_failures(ledger))
    enforce_review_hook_attestation(
        route=route,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        gate_evidence=gate_evidence,
        gate_evidence_ledger=ledger,
        failures=failures,
    )
    return gate_evidence, ledger


def _revalidate_review_attestation_after_final_checks(
    route: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    gate_evidence: dict[str, str],
    gate_evidence_ledger: dict[str, Any],
    missed_gates: list[str],
    gate_signals: list[dict[str, str]],
    failures: list[str],
) -> None:
    """Close drift between the initial gate merge and the final checks."""

    if REVIEW_HOOK_GATE not in gate_evidence:
        return
    enforce_review_hook_attestation(
        route=route,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        gate_evidence=gate_evidence,
        gate_evidence_ledger=gate_evidence_ledger,
        failures=failures,
    )
    if REVIEW_HOOK_GATE in gate_evidence:
        return
    missed_gates.append(REVIEW_HOOK_GATE)
    # The SUCCESS recorded before the final checks describes an attestation
    # that has just been rejected, and it was left in the reported signals: the
    # run failed while still advertising the review gate as passed. Drop the
    # stale row and state the outcome the revalidation reached.
    gate_signals[:] = [
        signal for signal in gate_signals if signal.get("gate") != REVIEW_HOOK_GATE
    ]
    add_gate_signal(
        gate_signals,
        "FAIL",
        REVIEW_HOOK_GATE,
        "failed",
        "review attestation no longer matched after the final checks",
    )


def main() -> int:
    tao_root = Path(__file__).resolve().parents[1]
    args = build_parser(tao_root).parse_args()
    worker_error = _apply_worker_evidence_boundary(args)
    if worker_error:
        print(f"FAIL: {worker_error}", file=sys.stderr)
        return 2
    project, rules, evidence_path, output_path = resolve_paths(args)
    failures: list[str] = []
    preflight = read_preflight(evidence_path, failures)
    route = preflight.get("route") or {}
    delegation_plan = read_delegation_plan(project)
    (
        gate_evidence,
        gate_evidence_ledger,
        gate_signals,
        required_gates,
        missed_gates,
        gate_policy_failures,
        grill_me_required,
    ) = _evaluate_route_gates(
        route=route,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        preflight=preflight,
        delegation_plan=delegation_plan,
        failures=failures,
    )
    read_only = effective_read_only(preflight, route)
    check_preflight_vibeguard(preflight, failures, read_only=read_only)
    check_read_only_execution(
        preflight,
        project,
        failures,
        read_only=read_only,
        intrinsically_read_only=route.get("command") == "analysis",
    )
    validate, diff_check, vibeguard, overall = run_final_checks(
        tao_root,
        project,
        rules,
        args.allow_vibeguard_review,
        gate_signals,
        failures,
        read_only=read_only,
        intrinsically_read_only=route.get("command") == "analysis",
    )
    _revalidate_review_attestation_after_final_checks(
        route, project, rules, evidence_path, gate_evidence,
        gate_evidence_ledger, missed_gates, gate_signals, failures,
    )
    retrospective_required, retrospective_lesson, skill_followup = process_closeout_learning(
        preflight=preflight,
        missed_gates=missed_gates,
        gate_policy_failures=gate_policy_failures,
        gate_signals=gate_signals,
        failures=failures,
        rules=rules,
        gate_evidence_ledger=gate_evidence_ledger,
    )

    result = build_result(
        tao_root=tao_root,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        args=args,
        preflight=preflight,
        required_gates=required_gates,
        gate_evidence=gate_evidence,
        gate_signals=gate_signals,
        missed_gates=missed_gates,
        gate_evidence_ledger=gate_evidence_ledger,
        delegation_plan=delegation_plan,
        grill_me_required=grill_me_required,
        retrospective_required=retrospective_required,
        validate=validate,
        diff_check=diff_check,
        vibeguard=vibeguard,
        retrospective_lesson=retrospective_lesson,
        skill_followup=skill_followup,
        failures=failures,
    )
    # Stamp the producing session so the Stop gate can tell a finish from this
    # session apart from one this project happens to have on disk. Only a clean
    # finish counts; recording a failed run would let it satisfy the gate.
    if not failures:
        result["runtime_session"] = runtime_session()
    write_json(output_path, result)
    if not failures:
        record_session_finished(project, result["runtime_session"])
    print_result(output_path, required_gates, overall, result)

    return _report_finish_failures(
        failures=failures,
        gate_policy_failures=gate_policy_failures,
        required_gates=required_gates,
        missed_gates=missed_gates,
        gate_evidence=gate_evidence,
        evidence_path=evidence_path,
        preflight=preflight,
        pending_closeout=bool(skill_followup),
    )


def _evaluate_route_gates(
    *,
    route: dict,
    project: Path,
    rules: Path,
    evidence_path: Path,
    preflight: dict,
    delegation_plan: dict | None,
    failures: list[str],
) -> tuple:
    """Run the route's gate-evidence checks and return their combined state."""

    gate_evidence, gate_evidence_ledger = _validated_gate_evidence(
        route=route,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        failures=failures,
    )
    gate_signals: list[dict[str, str]] = []
    required_gates, missed_gates, gate_policy_failures = check_required_gates(
        route,
        gate_evidence,
        gate_signals,
        failures,
        delegation_plan,
        allowed_skill_ids=canonical_skill_ids(project, rules),
    )
    capsule_binding_failures = route_gate_capsule_binding_failures(
        route,
        project,
        rules,
        evidence_path,
        gate_evidence,
        gate_evidence_ledger,
    )
    for failure in capsule_binding_failures:
        add_gate_signal(gate_signals, "FAIL", "execution capsule", "failed", failure)
        failures.append(failure)
    gate_policy_failures.extend(capsule_binding_failures)
    grill_me_required = check_request_intake(
        route,
        preflight.get("request_intake") or {},
        route.get("request_classification") or {},
        gate_evidence,
        gate_signals,
        missed_gates,
        failures,
    )
    return (
        gate_evidence,
        gate_evidence_ledger,
        gate_signals,
        required_gates,
        missed_gates,
        gate_policy_failures,
        grill_me_required,
    )


def _apply_worker_evidence_boundary(args: argparse.Namespace) -> str:
    if os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        return "reusable worker capsule cannot run a finish check against parent evidence"
    expected = os.environ.get("TAO_WORKER_EVIDENCE")
    if not expected:
        return ""
    expected_path = Path(expected).expanduser().resolve()
    if args.evidence and args.evidence.resolve() != expected_path:
        return "worker finish check must use the launcher-issued isolated evidence path"
    args.evidence = expected_path
    return ""


if __name__ == "__main__":
    sys.exit(main())
