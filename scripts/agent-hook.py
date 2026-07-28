#!/usr/bin/env python3
"""Run the essential Tao Agent OS hooks.

Hooks intentionally expose only two outcomes: SUCCESS or FAIL. Details explain
why, but callers should treat any non-zero exit as blocking.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_gate_evidence import resync_gate_evidence_ledger
from agent_execution_capsule_state import git_states_for_paths
from agent_handoff_hook import handoff_hook
from agent_hook_continuation import (
    checkpoint_after_hook,
    gate_checkpoint_name,
    record_lifecycle_checkpoint,
    start_objective,
)
from agent_hook_gate_records import (
    gate_batch_hook,
    gate_hook,
    preflight_evidence_path,
)
from agent_hook_resume import add_resume_arguments, resume_hook
from agent_hook_runtime import (
    REVIEW_CHANGED_PATH_LIMIT,
    existing_directory,
    existing_path,
    finish_with_result,
    git_status,
    non_negative_int,
    parse_overall,
    print_status,
    repair_cycle,
    repair_context_failures,
    run_command,
    vibeguard_command,
    write_json,
)
from agent_inprocess import run_script_main
from agent_review_hook import review_hook
from agent_repair_verification import create_repair_receipt
from agent_skill_hooks import (
    skill_curate_hook,
    skill_feedback_hook,
    skill_maintenance_hook,
    skill_review_hook,
)
from agent_review_structure import (
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
)
from agent_run_registry import (
    claim_run,
    register_run,
    touch_run,
    transition_run,
)
from agent_context_store import (
    context_snapshot_failures_are_replaceable,
    context_snapshot_path,
    refresh_and_validate_context_snapshot,
    validate_context_snapshot,
)
from workflow_catalog import CONCERNS, PLATFORM_CONCERNS
ROOT = Path(__file__).resolve().parents[1]


def start_hook(args: argparse.Namespace) -> int:
    evidence_path = preflight_evidence_path(args)
    request_intake = {
        "request": args.request,
        "request_classified": bool(args.request_classified),
        "classification_evidence": args.classification_evidence,
    }
    # A run that was interrupted stays `running` forever unless the separate
    # maintenance entrypoint is invoked, and nothing in the lifecycle invokes
    # it. Without the sweep inside this claim one abandoned run permanently
    # holds the shared evidence path: start refuses it and directs the agent to
    # an isolated --evidence path, while the Claude pre-tool gate only ever
    # reads the default one, so every edit is denied with no in-band way out.
    # Sweeping, deciding and registering happen in one registry transaction, so
    # two concurrent starts cannot both conclude the path is free.
    claim = claim_run(
        args.project,
        evidence_path,
        {"command": args.command},
        request_intake,
    )
    if claim["conflict"]:
        return finish_with_result(
            "start",
            False,
            [_claim_refusal_detail(claim)],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    command = [
        "--project",
        str(args.project),
        "--rules",
        str(args.rules),
        "--command",
        args.command,
    ]
    if args.request_classified:
        command.append("--request-classified")
        command.extend(["--classification-evidence", args.classification_evidence])
        if args.request:
            command.extend(["--request", args.request])
    else:
        command.extend(["--request", args.request])
    for platform in args.platform:
        command.extend(["--platform", platform])
    for concern in args.concern:
        command.extend(["--concern", concern])
    if args.read_only:
        command.append("--read-only")
    if args.evidence:
        command.extend(["--evidence", str(args.evidence)])
    if args.worker_reservation_token:
        command.extend(["--worker-reservation-token", args.worker_reservation_token])

    result = run_script_main(ROOT / "scripts" / "agent-preflight.py", command, args.project)
    success = result["returncode"] == 0
    details = ["preflight completed" if success else "preflight failed"]
    details.extend(_summary_lines(result))
    if success:
        details.extend(_hook_summary_from_preflight(preflight_evidence_path(args)))
        capsule_detail = _start_capsule_detail(args)
        if capsule_detail:
            details.append(capsule_detail)
        # Validate and refresh context before registering the run. If context
        # validation fails, start must not leave an orphaned running record.
        success = _refresh_started_context(args, details) and success
        if success:
            success = _bind_read_only_execution_state(args, details)
        if success:
            _register_started_run(args, details, claim["run"])
            # The route and objective are known and nothing has been mutated
            # yet, which is the only moment an initial packet can describe.
            details.append(
                record_lifecycle_checkpoint(
                    args, "initial", work={"objective": start_objective(args)}
                )
            )
    if not success:
        _release_claimed_run(args, claim["run"])
    return finish_with_result(
        "start",
        success,
        details,
        args.output,
        {"preflight": result},
        args.repair_cycle,
        invocation_error=_is_invocation_error(result) or (
            not success and result.get("returncode") == 0
        ),
    )


def _is_invocation_error(result: dict[str, Any]) -> bool:
    """True when preflight rejected the call itself rather than failing a gate.

    argparse exits 2 on a usage error, which happens before any gate runs, so
    nothing is written to the ledger. Treating that as a gate failure sends the
    caller into a repair cycle that can never complete, because repair-verify
    builds its receipt from a recorded failed checkpoint and there is none.
    """
    output = f"{result.get('stderr', '')}{result.get('stdout', '')}"
    if result.get("returncode") == 2:
        return "error: argument" in output or "invalid choice" in output
    if result.get("returncode") != 1 or "workflow route failed:" not in output:
        return False
    # Request intake can reject a work route before a route manifest or gate
    # ledger exists.  That is an invocation to correct, not a failed checkpoint
    # that repair-verify could bind to.  Sending it into the repair cycle creates
    # an impossible receipt deadlock.
    return any(
        marker in output.lower()
        for marker in (
            "needs clarification before route",
            "current request is a direct question",
            "classification evidence does not prove work can start",
            "route requires request intake evidence",
            "broad app/product/feature work",
        )
    )


def _hook_summary_from_preflight(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    hooks = (payload.get("route") or {}).get("hooks") or []
    required = [hook.get("hook") for hook in hooks if hook.get("required")]
    conditional = [hook.get("hook") for hook in hooks if not hook.get("required")]
    lines: list[str] = []
    if required:
        lines.append(f"Required hooks: {required}")
    if conditional:
        lines.append(f"Conditional hooks: {conditional}")
    return lines


def _start_capsule_detail(args: argparse.Namespace) -> str:
    """Describe the lazy parent-to-worker capsule boundary."""

    _ = args
    return "execution capsule creation deferred until a worker handoff"


def finish_hook(args: argparse.Namespace) -> int:
    command = [
        "--project",
        str(args.project),
        "--rules",
        str(args.rules),
    ]
    if args.evidence:
        command.extend(["--evidence", str(args.evidence)])
    if args.allow_vibeguard_review:
        command.extend(["--allow-vibeguard-review", args.allow_vibeguard_review])

    result = run_script_main(ROOT / "scripts" / "agent-finish-check.py", command, args.project)
    success = result["returncode"] == 0
    details = ["finish check completed" if success else "finish check failed"]
    details.extend(_summary_lines(result))
    # Must precede the transition: the writer refuses a run that is no longer
    # active, and a completed or failed run is exactly that.
    details.append(
        record_lifecycle_checkpoint(args, "lifecycle", phase="done" if success else None)
    )
    _transition_finished_run(args, success)
    return finish_with_result(
        "finish",
        success,
        details,
        args.output,
        {"finish_check": result},
        args.repair_cycle,
    )


def _claim_refusal_detail(claim: dict[str, Any]) -> str:
    """Explain a refusal the agent cannot otherwise see in the registry.

    A run held past the staleness window by a still-living process keeps the
    path until its grace ceiling, so without naming it the agent only sees a
    path that stays blocked for no visible reason.
    """

    detail = (
        "preflight evidence is already bound to another active request; "
        "use one isolated --evidence .tao/runs/<opaque>/preflight.json path "
        "for the full start/gate/review/finish lifecycle"
    )
    if claim.get("held"):
        detail += (
            "; the holding run reported no progress recently but its owning "
            "process is still alive, so it keeps the path until it finishes or "
            "its grace ceiling expires"
        )
    return detail


def _release_claimed_run(args: argparse.Namespace, run: dict[str, Any] | None) -> None:
    """Give back the evidence path when the start that claimed it never began.

    The claim is taken before preflight so two starts cannot both win the path.
    A start that then fails produced no run to protect, and leaving the claim
    standing would block the next attempt for a whole staleness window.
    """

    if not run:
        return
    try:
        transition_run(
            args.project,
            preflight_evidence_path(args),
            "cancelled",
            run_id=str(run.get("run_id") or "") or None,
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        return


def _register_started_run(
    args: argparse.Namespace,
    details: list[str],
    claimed: dict[str, Any] | None,
) -> None:
    """Persist lifecycle state without making registry health a startup blocker."""

    try:
        evidence_path = preflight_evidence_path(args)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        run = register_run(
            args.project,
            evidence_path,
            payload.get("route") or {},
            payload.get("request_intake") or {},
            reuse_run_id=str((claimed or {}).get("run_id") or "") or None,
        )
        payload["agent_run_id"] = run["run_id"]
        write_json(evidence_path, payload)
        # This rewrite changes preflight.json's hash after "request intake"
        # was already recorded in the gate-evidence ledger against the
        # pre-mutation content. Without resyncing, the next gate write's
        # self-heal check sees a stale hash and silently wipes the ledger,
        # including that "request intake" entry -- reproduced end-to-end:
        # right after start the entries are ["request intake"], and after
        # exactly one more `gate` call they become just the new gate, with
        # "request intake" gone.
        try:
            resync_gate_evidence_ledger(evidence_path, payload)
        except (OSError, ValueError):
            pass
        details.append("agent run registry: running")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        details.append("agent run registry: unavailable; lifecycle continues")


def _bind_read_only_execution_state(
    args: argparse.Namespace,
    details: list[str],
) -> bool:
    """Bind a VibeGuard-skipping run to strong start-time workspace bytes."""

    evidence_path = preflight_evidence_path(args)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not (payload.get("execution_mode") or {}).get("read_only"):
            return True
        # Both roots matter. A read-only run against a separate rules checkout
        # can still edit that checkout, and fingerprinting the project twice
        # would let those edits through the finish check unseen.
        project_state, rules_state = git_states_for_paths(args.project, args.rules)
        payload["read_only_execution_state"] = {
            "project": project_state,
            "rules": rules_state,
        }
        write_json(evidence_path, payload)
        resync_gate_evidence_ledger(evidence_path, payload)
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as error:
        details.append(f"read-only execution state: capture failed ({error})")
        return False
    details.append("read-only execution state: bound")
    return True


def _refresh_run_heartbeat(args: argparse.Namespace) -> None:
    """Mark the run alive on every post-start lifecycle hook.

    Any hook reaching this point is an agent actively working the run, which is
    the proof of life the staleness sweep needs. Registry problems must never
    block the hook itself, so failures here stay silent.
    """

    try:
        touch_run(args.project, preflight_evidence_path(args))
    except (OSError, RuntimeError, ValueError, TypeError):
        return


def _transition_finished_run(args: argparse.Namespace, success: bool) -> None:
    try:
        evidence_path = args.evidence or args.project / ".tao" / "preflight.json"
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        transition_run(
            args.project,
            evidence_path,
            "completed" if success else "failed",
            run_id=payload.get("agent_run_id"),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return


def _refresh_started_context(args: argparse.Namespace, details: list[str]) -> bool:
    try:
        evidence_path = preflight_evidence_path(args)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        snapshot_path = context_snapshot_path(args.project)
        if snapshot_path.exists():
            prior_failures = validate_context_snapshot(
                args.project,
                args.rules,
                payload.get("route") or {},
                payload.get("request_intake") or {},
            )
            if prior_failures and not context_snapshot_failures_are_replaceable(
                prior_failures
            ):
                raise ValueError("context snapshot validation failed: " + "; ".join(prior_failures))
            if prior_failures:
                details.append("context snapshot: stale request replaced")
        _, post_failures = refresh_and_validate_context_snapshot(
            args.project,
            args.rules,
            payload.get("route") or {},
            payload.get("request_intake") or {},
        )
        if post_failures:
            raise ValueError("context snapshot validation failed after refresh: " + "; ".join(post_failures))
        details.append("context snapshot: refreshed")
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        details.append("context snapshot: validation failed")
        return False


def _summary_lines(result: dict[str, Any]) -> list[str]:
    # FAIL lines must never be dropped: hiding some failures makes fixed
    # reruns surface "new" complaints that were failing all along.
    info_lines: list[str] = []
    fail_lines: list[str] = []
    for stream in ("stdout", "stderr"):
        for line in result.get(stream, "").splitlines():
            stripped = line.strip()
            if stripped.startswith("FAIL:"):
                fail_lines.append(stripped)
            elif stripped.startswith((
                "Route:",
                "Required hooks:",
                "Conditional hooks:",
                "VibeGuard overall:",
                "Required gates:",
                "Retrospective required:",
                "Retrospective lesson candidate:",
                "Global lessons:",
                "- routed doc candidates:",
                "- on-demand reference docs:",
            )):
                info_lines.append(stripped)
    if not fail_lines and result.get("returncode") not in (0, None):
        fail_lines = _fallback_failure_lines(result)
    return info_lines[:8] + fail_lines


def _fallback_failure_lines(result: dict[str, Any]) -> list[str]:
    """Surface a raw error when the failure has no line in the FAIL: format.

    Argument-parsing errors, uncaught exceptions, and other non-`FAIL:`
    failures were silently dropped here, leaving callers with only
    "preflight failed" and no way to tell an invalid --command typo apart
    from an actual classification block.
    """

    for stream in ("stderr", "stdout"):
        lines = [line.strip() for line in result.get(stream, "").splitlines() if line.strip()]
        if lines:
            return [f"FAIL: {line}" for line in lines[-3:]]
    return [f"FAIL: process exited with code {result.get('returncode')}"]


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "hook",
        choices=(
            "start",
            "handoff",
            "resume",
            "gate",
            "gate-batch",
            "review",
            "finish",
            "skill-feedback",
            "skill-curate",
            "skill-review",
            "skill-maintenance",
            "repair-verify",
        ),
    )
    parser.add_argument("--project", type=existing_directory, default=Path.cwd())
    parser.add_argument("--rules", type=existing_directory, default=ROOT)
    parser.add_argument(
        "--output",
        type=existing_path,
        help=(
            "hook result output for start, handoff, review, or finish; this is not "
            "the preflight evidence consumed by later lifecycle hooks"
        ),
    )
    parser.add_argument(
        "--evidence",
        type=existing_path,
        help="preflight evidence path; start writes it and finish reads it",
    )
    parser.add_argument(
        "--repair-cycle",
        type=repair_cycle,
        default=0,
        help="0 for normal execution, 1 only after a verified Tao Agent OS repair",
    )
    parser.add_argument("--repair-target", default="")
    parser.add_argument("--repair-evidence", default="")
    parser.add_argument("--resume-checkpoint", default="")
    parser.add_argument(
        "--repair-verification-kind",
        choices=("py_compile", "unittest", "vibeguard", "workflow_validate"),
        default="workflow_validate",
    )
    parser.add_argument("--repair-test-selector", default="")
    parser.add_argument(
        "--repair-receipt-output",
        type=existing_path,
        help="optional project-local output path for repair-verify",
    )


def _add_start_arguments(parser: argparse.ArgumentParser) -> None:
    start = parser.add_argument_group("start hook")
    start.add_argument("--command", default="task", help="workflow route command for start")
    start.add_argument("--request", help="current user request")
    start.add_argument(
        "--request-classified",
        action="store_true",
        help=(
            "delegated-worker only: reuse request intake from a ready, valid, "
            "matching parent capsule; also pass the exact bound --request"
        ),
    )
    start.add_argument("--classification-evidence", default="")
    start.add_argument(
        "--read-only",
        action="store_true",
        help="declare a non-mutating analysis run and skip VibeGuard audits",
    )
    start.add_argument("--platform", action="append", default=[])
    start.add_argument(
        "--concern",
        action="append",
        choices=sorted(set(CONCERNS) | {key[1] for key in PLATFORM_CONCERNS}),
        default=[],
    )
    start.add_argument(
        "--worker-reservation-token",
        default="",
        help="opaque token issued by the parent handoff for a fallback worker start",
    )


def _add_review_arguments(parser: argparse.ArgumentParser) -> None:
    review = parser.add_argument_group("review hook")
    review.add_argument(
        "--review-outcome",
        choices=("pass", "findings"),
        default="",
        help="structural review decision; findings keeps the review checkpoint failed",
    )
    review.add_argument(
        "--code-review-evidence",
        help="short evidence that the exact diff was reviewed against request and rules",
    )
    review.add_argument(
        "--docs-freshness-evidence",
        help="short evidence that affected docs were updated or intentionally unchanged",
    )
    review.add_argument(
        "--structure-review-evidence",
        help=(
            "short evidence that runtime file/function size, top-level owner count, and "
            "responsibility splits were reviewed; new runtime package boundaries must "
            "use explicit labels: owner: ..., allowed imports: ..., forbidden imports: ..., "
            "callers/tests: ..., verification: ..."
        ),
    )
    review.add_argument(
        "--boundary-plan-evidence",
        help="short evidence of the owned boundary/scope and nearest verification chosen before implementation",
    )
    review.add_argument(
        "--side-effect-audit-evidence",
        help="short evidence that the final diff and side-effect surfaces were checked",
    )
    review.add_argument(
        "--review-scope",
        choices=("working-tree", "pathspec"),
        default="working-tree",
        help="declare whether review covers the whole working tree or explicit --review-path pathspecs",
    )
    review.add_argument(
        "--review-path",
        action="append",
        default=[],
        help="limit review hook changed-path, diff, and structure checks to this pathspec; repeat as needed",
    )
    review.add_argument(
        "--max-changed-paths",
        type=non_negative_int,
        default=REVIEW_CHANGED_PATH_LIMIT,
        help="fail review when the changed path count is above this limit",
    )
    review.add_argument(
        "--max-source-file-lines",
        type=non_negative_int,
        default=REVIEW_SOURCE_FILE_LINE_LIMIT,
        help="fail review when a changed development source/style file is above this line count",
    )
    review.add_argument(
        "--max-function-lines",
        type=non_negative_int,
        default=REVIEW_FUNCTION_LINE_LIMIT,
        help="fail review when a changed function, class, component, or style block is above this line count",
    )


def _add_finish_arguments(parser: argparse.ArgumentParser) -> None:
    finish = parser.add_argument_group("finish hook")
    finish.add_argument("--allow-vibeguard-review")


def _add_skill_feedback_arguments(parser: argparse.ArgumentParser) -> None:
    feedback = parser.add_argument_group("successful-task skill feedback")
    feedback.add_argument(
        "--skill-feedback-outcome",
        choices=("no_change", "observed"),
        default="no_change",
    )
    feedback.add_argument("--skill-id", default="")
    feedback.add_argument("--feedback-signal", default="")
    feedback.add_argument("--feedback-candidate-id", default="")
    feedback.add_argument(
        "--skill-review-outcome",
        choices=("no_change", "stage_patch"),
        default="no_change",
    )
    feedback.add_argument("--feedback-gap", default="")
    feedback.add_argument("--change-type", default="")
    feedback.add_argument("--promotion-target", default="")
    feedback.add_argument(
        "--skill-maintenance-outcome",
        choices=("applied", "rejected"),
        default="rejected",
    )
    feedback.add_argument("--verification-kind", default="")
    feedback.add_argument("--maintenance-target", default="")
    feedback.add_argument("--maintenance-test-selector", default="")


def _add_gate_arguments(parser: argparse.ArgumentParser) -> None:
    gate = parser.add_argument_group("gate evidence hook")
    gate.add_argument("--gate-name", help="route gate name to record in the structured ledger")
    gate.add_argument("--status", choices=("SUCCESS", "FAIL"), default="SUCCESS")
    gate.add_argument("--source", default="manual")
    gate.add_argument("--gate-evidence", default="")
    gate.add_argument("--field", action="append", default=[], help="structured evidence field as key=value")
    gate.add_argument(
        "--gate-record",
        action="append",
        default=[],
        help="JSON object or array of objects with gate, evidence, fields, source, and status",
    )
    gate.add_argument(
        "--gate-json",
        type=existing_path,
        help="JSON file containing a gate evidence object or array of objects",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run essential Tao Agent OS hooks.",
        allow_abbrev=False,
    )
    _add_common_arguments(parser)
    _add_start_arguments(parser)
    add_resume_arguments(parser)
    _add_review_arguments(parser)
    _add_finish_arguments(parser)
    _add_skill_feedback_arguments(parser)
    _add_gate_arguments(parser)
    return parser


def _parse_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    argv = sys.argv[1:]
    if argv and argv[0] == "finish" and any(
        argument == "--gate" or argument.startswith("--gate=")
        for argument in argv
    ):
        parser.error(
            "finish no longer accepts --gate; record gate evidence first with "
            "the gate or gate-batch hook, then run finish"
        )
    return parser.parse_args(argv)


def _lifecycle_evidence_error(args: argparse.Namespace) -> str:
    if not args.evidence:
        return ""
    if args.hook == "start":
        try:
            args.evidence.resolve().relative_to((args.project / ".tao").resolve())
        except (OSError, RuntimeError, ValueError):
            return (
                "start --evidence must be under the current project's .tao "
                "evidence root so later lifecycle hooks can validate the same capsule"
            )
        return ""
    try:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if (
        isinstance(payload, dict)
        and payload.get("hook") == "start"
        and "preflight" in payload
        and "route" not in payload
    ):
        return (
            "--evidence must name the preflight evidence written by start --evidence, "
            "not the start hook result written by --output"
        )
    return ""


def main() -> int:
    parser = build_parser()
    args = _parse_args(parser)
    if (
        args.hook == "start"
        and args.output
        and not args.evidence
        and args.output.name == "preflight.json"
    ):
        parser.error(
            "start --output stores the hook result, not preflight evidence; "
            "pass the preflight path with --evidence and use a distinct "
            "--output path such as start.json"
        )
    lifecycle_evidence_error = _lifecycle_evidence_error(args)
    if lifecycle_evidence_error:
        parser.error(lifecycle_evidence_error)
    worker_error = _apply_worker_evidence_boundary(args)
    if worker_error:
        print_status(args.hook, False, [worker_error])
        return 2
    # Must follow _apply_worker_evidence_boundary so a worker refreshes its own
    # run, and must skip `start`: start refreshes nothing it is about to sweep,
    # or it would revive the very record whose evidence path it needs to claim.
    # `resume` is skipped for the opposite reason: a heartbeat is a registry
    # write, and `resume --list` promises to leave the registry byte-identical.
    if args.hook not in ("start", "resume"):
        _refresh_run_heartbeat(args)
    if args.hook == "resume":
        if args.list_mode == args.last_mode:
            parser.error("resume requires exactly one of --list or --last")
        return resume_hook(args)
    if args.hook == "repair-verify":
        repair_evidence_path = preflight_evidence_path(args)
        try:
            repair_preflight = json.loads(repair_evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            repair_preflight = {}
        result = create_repair_receipt(
            project=args.project,
            rules=args.rules,
            evidence_path=repair_evidence_path,
            preflight=repair_preflight,
            target=args.repair_target,
            checkpoint=args.resume_checkpoint,
            verification_kind=args.repair_verification_kind,
            test_selector=args.repair_test_selector,
            output_path=args.repair_receipt_output,
        )
        success = bool(result.get("created")) and result.get("status") == "SUCCESS"
        details = [
            f"repair receipt: {result.get('receipt_path', 'not_created')}",
            f"verification status: {result.get('status', result.get('reason', 'unknown'))}",
        ]
        return finish_with_result(
            "repair-verify",
            success,
            details,
            args.output,
            {"repair_verification": result},
            0,
        )
    if args.repair_cycle:
        # Must run after _apply_worker_evidence_boundary: that call is what
        # points args.evidence at a worker's launcher-issued isolated
        # evidence path. Resolving preflight_evidence_path(args) any earlier
        # would silently read/write the parent's preflight.json instead of
        # the worker's, so checkpoint_has_recorded_failure would always miss
        # and every worker repair-cycle claim would be rejected.
        repair_evidence_path = preflight_evidence_path(args)
        try:
            repair_preflight = json.loads(repair_evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            repair_preflight = {}
        repair_failures = repair_context_failures(
            args.repair_target,
            args.repair_evidence,
            args.resume_checkpoint,
            route=repair_preflight.get("route") or {},
            evidence_path=repair_evidence_path,
            preflight=repair_preflight,
            project=args.project,
            rules=args.rules,
        )
        if repair_failures:
            parser.error(
                "--repair-cycle 1 requires verified repair context: "
                + "; ".join(repair_failures)
            )
    if args.hook == "start":
        if args.request_classified and not args.classification_evidence:
            parser.error("start --request-classified requires --classification-evidence")
        if not args.request:
            parser.error(
                "start requires --request with the real current request; only a delegated "
                "worker with a matching parent capsule may additionally use "
                "--request-classified"
            )
        return start_hook(args)
    checkpointed = _checkpointed_hook(args, parser)
    if checkpointed is not None:
        return checkpointed
    if args.hook == "handoff":
        return handoff_hook(args)
    if args.hook == "skill-feedback":
        return skill_feedback_hook(args)
    if args.hook == "skill-curate":
        return skill_curate_hook(args)
    if args.hook == "skill-review":
        return skill_review_hook(args)
    if args.hook == "skill-maintenance":
        return skill_maintenance_hook(args)
    return finish_hook(args)


def _checkpointed_hook(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int | None:
    """Run a hook whose completion is a continuation lifecycle transition.

    A gate record, a batch of them and a review are the during-work points the
    packet must be refreshed at, so they dispatch together rather than each
    growing its own copy of the same side effect. ``None`` means this was not
    one of them.
    """

    if args.hook == "review":
        args.review_path = [path.strip() for path in args.review_path if path.strip()]
        if args.review_path and args.review_scope == "working-tree":
            args.review_scope = "pathspec"
        if args.review_scope == "pathspec" and not args.review_path:
            parser.error("review --review-scope pathspec requires at least one --review-path")
        return checkpoint_after_hook(
            args,
            review_hook(
                args, run_command, git_status, vibeguard_command, parse_overall, finish_with_result
            ),
            "lifecycle",
            phase="reviewing",
        )
    if args.hook == "gate":
        if not args.gate_name:
            parser.error("gate requires --gate-name")
        return checkpoint_after_hook(
            args, gate_hook(args), "lifecycle", last_completed=gate_checkpoint_name(args)
        )
    if args.hook == "gate-batch":
        return checkpoint_after_hook(args, gate_batch_hook(args), "lifecycle")
    return None


def _apply_worker_evidence_boundary(args: argparse.Namespace) -> str:
    if os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        return "reusable worker capsule cannot run lifecycle hooks that write parent evidence"
    expected = os.environ.get("TAO_WORKER_EVIDENCE")
    if not expected:
        return ""
    expected_path = Path(expected).expanduser().resolve()
    if args.evidence and args.evidence.resolve() != expected_path:
        return "worker lifecycle must use the launcher-issued isolated evidence path"
    args.evidence = expected_path
    return ""


if __name__ == "__main__":
    sys.exit(main())
