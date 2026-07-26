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
from agent_global_lessons import write_retrospective_candidate
from agent_runtime_session import runtime_session
from agent_skill_catalog import canonical_skill_ids
from agent_finish_check_steps import (
    check_preflight_vibeguard,
    check_request_intake,
    check_required_gates,
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
        "failures": failures,
    }


def print_result(output_path: Path, required_gates: list[str], overall: str, result: dict[str, Any]) -> None:
    print(f"Finish evidence: {output_path}")
    print(f"Required gates: {required_gates}")
    print(f"VibeGuard overall: {overall}")
    print(f"Retrospective required: {str(result['retrospective_required']).lower()}")
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
) -> tuple[bool, dict[str, Any]]:
    retrospective_required = requires_retrospective(
        missed_gates,
        gate_policy_failures,
        failures,
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
                "required-doc drift recovery: when the repair intentionally changes that "
                "document, record documentation SUCCESS with decision=updated and the exact "
                "route-relative required doc target before repair-verify; this binds the final "
                "document bytes without bypassing the snapshot check"
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


def _report_finish_failures(
    *,
    failures: list[str],
    gate_policy_failures: list[str],
    required_gates: list[str],
    missed_gates: list[str],
    gate_evidence: dict[str, str],
    evidence_path: Path,
    preflight: dict[str, Any],
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
    return 1


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
    gate_evidence, gate_evidence_ledger = merge_gate_evidence_from_ledger(
        route=route,
        evidence_path=evidence_path,
    )
    failures.extend(incomplete_gate_evidence_failures(gate_evidence_ledger))
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
    read_only = effective_read_only(preflight, route)
    check_preflight_vibeguard(preflight, failures, read_only=read_only)
    validate, diff_check, vibeguard, overall = run_final_checks(
        tao_root,
        project,
        rules,
        args.allow_vibeguard_review,
        gate_signals,
        failures,
        read_only=read_only,
    )
    retrospective_required, retrospective_lesson = process_failure_learning(
        preflight=preflight,
        missed_gates=missed_gates,
        gate_policy_failures=gate_policy_failures,
        gate_signals=gate_signals,
        failures=failures,
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
