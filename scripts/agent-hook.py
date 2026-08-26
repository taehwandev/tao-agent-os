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
import tempfile
from pathlib import Path
from typing import Any

from agent_gate_evidence import (
    FIELD_REQUIREMENTS,
    gate_evidence_path_for_preflight,
    gate_field_enums,
    resync_gate_evidence_ledger,
)
from agent_execution_capsule_state import git_states_for_paths
from agent_finish_gate_validators import gate_wording_hints
from agent_handoff_hook import handoff_hook
from agent_hook_continuation import (
    checkpoint_after_hook,
    unbindable_run_directory_error,
    gate_checkpoint_name,
    record_lifecycle_checkpoint,
    start_checkpoint,
    work_checkpoint_advice,
)
from agent_hook_checkpoint import add_checkpoint_arguments, checkpoint_hook
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
from agent_global_lessons import promote_lessons_for_repair
from agent_review_hook import required_review_evidence_flags, review_hook
from agent_repair_verification import create_repair_receipt
from agent_repair_ledger import (
    CONFLICT as REPAIR_REBIND_CONFLICT,
    REBOUND as REPAIR_REBOUND,
    capture_failure_checkpoint_binding,
    checkpoint_failure_signature,
    repair_checkpoint_path_for_preflight,
    rebind_failure_checkpoints_after_required_doc_refresh,
    release_repair_attempt,
)
from agent_skill_hooks import (
    skill_curate_hook,
    skill_feedback_hook,
    skill_maintenance_hook,
    skill_draft_hook,
    skill_review_hook,
)
from agent_skill_catalog import FEEDBACK_SIGNALS
from agent_review_structure import (
    REVIEW_ADDED_LINE_LIMIT,
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
)
from agent_run_registry import (
    claim_run,
    registered_run,
    release_run_claim,
    register_run,
    resume_run_for_closeout,
    touch_run,
    transition_run,
)
from agent_route_state import request_fingerprint
from agent_runtime_session import recorded_session_id, runtime_session, settle_superseded_session_runs
from agent_transfer_cancel import (
    cancel_transferred_run,
    cancellation_receipt_failure,
    cancellation_worktree_drift,
)
from workflow_intent_envelope import SCHEMA_VERSION as ENVELOPE_SCHEMA_VERSION
from agent_context_store import (
    context_snapshot_failures_are_required_doc_drift,
    context_snapshot_failures_are_replaceable,
    context_snapshot_path,
    refresh_and_validate_context_snapshot,
    validate_context_snapshot,
)
from support.global_state import ensure_local_only_state_dir
from workflow_catalog import CONCERNS, PLATFORM_CONCERNS
from support.stage_timing import append_recorded_stages, set_timing_sink, stage
ROOT = Path(__file__).resolve().parents[1]


def _preflight_arguments(args: argparse.Namespace) -> list[str]:
    command = [
        "--project", str(args.project),
        "--rules", str(args.rules),
        "--command", args.command,
    ]
    if args.request_classified:
        command.append("--request-classified")
        command.extend(["--classification-evidence", args.classification_evidence])
        if args.request:
            command.extend(["--request", args.request])
    else:
        command.extend(["--request", args.request])
    for option, value in (
        ("--continuation-scope", getattr(args, "continuation_scope", "")),
        ("--intent-envelope", getattr(args, "intent_envelope", "")),
        ("--approval-record", getattr(args, "approval_record", "")),
        ("--runtime-session-id", getattr(args, "runtime_session_id", "")),
    ):
        if value:
            command.extend([option, value])
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
    return command


def start_hook(args: argparse.Namespace) -> int:
    # Establish the local-only state root before anything writes into it. The
    # continuation store proves local-only status by asking Git, so a checkout
    # that has never been ignored refuses every packet write -- and the Claude
    # pre-tool gate turned that refusal into a denial of every edit.
    ensure_local_only_state_dir(args.project)
    evidence_path = preflight_evidence_path(args)
    prior_repair_binding = capture_failure_checkpoint_binding(evidence_path)
    request_intake = {
        "request": args.request,
        "continuation_scope": getattr(args, "continuation_scope", ""),
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
    details: list[str] = []
    success = False
    committed = False
    refresh_snapshot: dict[Path, bytes | None] = {}
    try:
        refresh_snapshot = _capture_preflight_refresh_state(
            args,
            evidence_path,
            claim.get("run") or {},
        )
        command = _preflight_arguments(args)
        with stage("preflight"):
            result = run_script_main(ROOT / "scripts" / "agent-preflight.py", command, args.project)
        success = result["returncode"] == 0
        details.append("preflight completed" if success else "preflight failed")
        details.extend(_summary_lines(result))
        if success:
            details.extend(_hook_summary_from_preflight(preflight_evidence_path(args)))
            capsule_detail = _start_capsule_detail(args)
            if capsule_detail:
                details.append(capsule_detail)
            # Validate and refresh context before registering the run. If context
            # validation fails, start must not leave an orphaned running record.
            success = _refresh_started_context(
                args,
                details,
                prior_repair_binding=prior_repair_binding,
            ) and success
            if success:
                success = _bind_read_only_execution_state(args, details)
            if success:
                success = _register_started_run(args, details, claim["run"])
                committed = success
            if success:
                # The route and objective are known and nothing has been mutated
                # yet, which is the only moment an initial packet can describe.
                kind, work = start_checkpoint(args)
                details.append(record_lifecycle_checkpoint(args, kind, work=work))
                details.extend(work_checkpoint_advice(args))
    finally:
        if not committed:
            restore_errors = _restore_preflight_refresh_state(refresh_snapshot)
            details.extend(restore_errors)
            release_error = _release_claimed_run(
                args,
                claim["run"],
                restore_refresh=not restore_errors,
            )
            if release_error:
                details.append(release_error)
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
    # Every workflow-route refusal happens before a route manifest or gate
    # ledger exists. That is an invocation to correct (or a router defect to
    # repair directly), not a failed checkpoint that repair-verify could bind
    # to. Trying to classify individual messages here leaves each new refusal
    # spelling able to create an impossible receipt deadlock.
    return True


def _hook_summary_from_preflight(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    route = payload.get("route") or {}
    hooks = route.get("hooks") or []
    required = [hook.get("hook") for hook in hooks if hook.get("required")]
    conditional = [hook.get("hook") for hook in hooks if not hook.get("required")]
    lines: list[str] = []
    if required:
        lines.append(f"Required hooks: {required}")
    if conditional:
        lines.append(f"Conditional hooks: {conditional}")
    gates = [gate for gate in (route.get("gates") or []) if isinstance(gate, str)]
    if any(hook.get("hook") == "review" for hook in hooks):
        flags = required_review_evidence_flags(gates)
        lines.append("Review hook requires evidence paths: " + " ".join(flags))
        lines.append(
            "Review hook conditionally requires --structure-review-evidence when changed "
            "development files exceed review-pressure or source-size limits."
        )
    lines.extend(_closeout_gate_lines(gates))
    lines.extend(_gate_batch_guidance_lines(gates))
    lines.extend(_structured_gate_field_lines(gates))
    return lines


def _closeout_gate_lines(gates: list[str]) -> list[str]:
    """Advertise closeout gates that otherwise look like post-finish work."""

    if "handoff" not in gates:
        return []
    return [
        "Closeout gate reminder: record the user-facing handoff gate with gate or "
        "gate-batch before finish; the worker handoff hook does not satisfy it."
    ]


def _gate_batch_guidance_lines(gates: list[str]) -> list[str]:
    """Keep strong checkpointing while avoiding one process per ready gate."""

    agent_owned = [
        gate for gate in gates if gate not in {"request intake", "review hook"}
    ]
    if len(agent_owned) < 2:
        return []
    return [
        "Performance: record two or more simultaneously-ready agent-owned gates in one "
        "gate-batch; one invocation writes one strong continuation checkpoint. Keep "
        "gates separate when they become ready in different phases or after a repeated "
        "batch validation failure."
    ]


def _structured_gate_field_lines(gates: list[str]) -> list[str]:
    """State which gates need named fields, and which fields.

    Recording a gate looked like writing a sentence, but several gates reject
    prose and demand an exact field set. That was only discoverable by failing
    finish, so `retrospective check` alone accounts for the largest recurring
    lesson class in the store. The route already knows the answer, so `start`
    states it.
    """

    required = [
        (gate, FIELD_REQUIREMENTS[gate])
        for gate in gates
        if FIELD_REQUIREMENTS.get(gate)
    ]
    if not required:
        return []
    lines = ["Gates requiring named fields (--field name=value):"]
    for gate, fields in required:
        lines.append(f"  {gate}: {_rendered_fields(gate, fields)}")
        # Several of these gates then decide by substring match, so a truthful
        # sentence the matcher does not recognise is refused after the work is
        # done -- the largest recurring failure class in the lesson store. The
        # phrases are the contract; stating them here costs one line each and
        # saves the refusal that teaches them.
        lines.extend(f"    wording -- {hint}" for hint in gate_wording_hints(gate))
    return lines


def _rendered_fields(gate: str, fields: tuple[str, ...]) -> str:
    """Name each field, and its accepted values when the set is closed."""

    enums = gate_field_enums(gate)
    return ", ".join(
        f"{field} ({'|'.join(enums[field])})" if field in enums else field
        for field in fields
    )


def _start_capsule_detail(args: argparse.Namespace) -> str:
    """Describe the lazy parent-to-worker capsule boundary."""

    _ = args
    return "execution capsule creation deferred until a worker handoff"


def finish_hook(args: argparse.Namespace) -> int:
    transferred_cancellation, cancellation_failure = _transferred_cancellation(args)
    if cancellation_failure is not None:
        return finish_with_result(
            "finish",
            False,
            [
                "bound source run carries transferred-cancellation evidence",
                cancellation_failure,
                "source finish gates were not evaluated and cancellation evidence was preserved",
            ],
            args.output,
            {"cancellation": transferred_cancellation or {}},
            args.repair_cycle,
            invocation_error=True,
        )
    if transferred_cancellation is not None:
        return finish_with_result(
            "finish",
            True,
            [
                "bound source run is already settled as cancelled",
                "completed linked-worktree replacement owns the finished lifecycle",
                "source gate evidence remains immutable and was not re-evaluated",
            ],
            args.output,
            {"cancellation": transferred_cancellation},
            args.repair_cycle,
        )

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

    with stage("finish_check"):
        result = run_script_main(ROOT / "scripts" / "agent-finish-check.py", command, args.project)
    success = result["returncode"] == 0
    details = ["finish check completed" if success else "finish check failed"]
    details.extend(_summary_lines(result))
    if success:
        # Complete the registry first. If the process dies between these two
        # writes, the run is already terminal and cannot be resumed from a
        # packet that still displays the pre-finish checkpoint.
        _transition_finished_run(args, True)
        details.append(
            record_lifecycle_checkpoint(
                args,
                "lifecycle",
                phase="done",
                finalize_completed=True,
            )
        )
    elif result["returncode"] == 3:
        # Pending closeout is owed work, not a failed run. Retiring it here
        # dropped the run out of ACTIVE_RUN_STATES, so runtime evidence no
        # longer resolved and the edit gate refused the very skill-document
        # writes the closeout asks for. Leaving the state alone was not enough:
        # the usual sequence is a finish that fails on a missing gate, the gate
        # being recorded, and the retry returning pending closeout, so the run
        # is already failed by then. Exit code 3 is only reachable once every
        # other check passed, so reviving the claim here cannot smuggle an
        # unfinished failure back into an active run.
        details.append(record_lifecycle_checkpoint(args, "lifecycle"))
        _resume_run_for_closeout(args)
    else:
        # A failed finish remains a resumable checkpoint, so record it while
        # the run is still active and only then move the registry to failed.
        details.append(record_lifecycle_checkpoint(args, "lifecycle"))
        _transition_finished_run(args, False)
    return finish_with_result(
        "finish",
        success,
        details,
        args.output,
        {"finish_check": result},
        args.repair_cycle,
        pending_closeout=result["returncode"] == 3,
        refreshable_failure=_is_refreshable_finish_drift(result),
    )


def _transferred_cancellation(
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the validated terminal record for a transferred source run.

    Cancellation already proves the completed replacement before it atomically
    settles the source run. Replaying finish against that immutable run must not
    ask the source checkout to reproduce gates owned by the replacement.
    """

    try:
        evidence_path = preflight_evidence_path(args)
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        run_id = str(preflight.get("agent_run_id") or "").strip()
        run = registered_run(args.project, evidence_path, run_id=run_id)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(run, dict):
        return None, None
    cancellation = run.get("cancellation")
    if not isinstance(cancellation, dict):
        return None, None
    receipt_failure = cancellation_receipt_failure(
        cancellation,
        source_run_id=run_id,
        request_fingerprint=str(run.get("request_fingerprint") or ""),
    )
    if receipt_failure is not None:
        return cancellation, receipt_failure
    if run.get("state") != "cancelled":
        return (
            cancellation,
            "transferred cancellation is not in the settled cancelled state",
        )
    drift = cancellation_worktree_drift(args.project, cancellation)
    if drift is not None:
        return cancellation, drift
    return cancellation, None


def _is_refreshable_finish_drift(result: dict[str, Any]) -> bool:
    """Recognize finish failures that only require a fresh start/review."""

    output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    failure_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("FAIL:")
    ]
    refreshable_failures = {
        "FAIL: review hook attestation project worktree binding is stale",
        "FAIL: review hook attestation rules worktree binding is stale",
        "FAIL: missing required gate evidence: review hook",
    }
    stale_review = any(
        line in refreshable_failures and "binding is stale" in line
        for line in failure_lines
    )
    stale_required_docs = any(
        line.startswith(
            (
                "FAIL: execution capsule required doc size changed: ",
                "FAIL: execution capsule required doc hash changed: ",
                "FAIL: execution capsule required doc changed after documentation evidence: ",
            )
        )
        for line in failure_lines
    )
    required_doc_refresh_lines = (
        "FAIL: execution capsule required doc size changed: ",
        "FAIL: execution capsule required doc hash changed: ",
        "FAIL: execution capsule required doc changed after documentation evidence: ",
        "FAIL: required-doc drift recovery: ",
        "FAIL: retrospective repair is required before final report, commit, release, or handoff; ",
    )
    only_refreshable_drift = all(
        line in refreshable_failures or line.startswith(required_doc_refresh_lines)
        for line in failure_lines
    )
    return (
        result.get("returncode") == 1
        and bool(failure_lines)
        and (stale_review or stale_required_docs)
        and only_refreshable_drift
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


def _release_claimed_run(
    args: argparse.Namespace,
    run: dict[str, Any] | None,
    *,
    restore_refresh: bool = True,
) -> str:
    """Give back the evidence path when the start that claimed it never began.

    The claim is taken before preflight so two starts cannot both win the path.
    A start that then fails produced no run to protect, and leaving the claim
    standing would block the next attempt for a whole staleness window.
    """

    if not run:
        return ""
    try:
        released = release_run_claim(
            args.project,
            preflight_evidence_path(args),
            str(run.get("run_id") or ""),
            restore_refresh=restore_refresh,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        return f"agent run claim cleanup failed: {type(error).__name__}"
    return "" if released is not None else "agent run claim cleanup failed: claim not found"


def _capture_preflight_refresh_state(
    args: argparse.Namespace,
    evidence_path: Path,
    claimed: dict[str, Any],
) -> dict[Path, bytes | None]:
    if not str(claimed.get("refresh_previous_state") or ""):
        return {}
    paths = (
        evidence_path,
        gate_evidence_path_for_preflight(evidence_path),
        context_snapshot_path(args.project),
        repair_checkpoint_path_for_preflight(evidence_path),
    )
    snapshot: dict[Path, bytes | None] = {}
    for path in paths:
        try:
            snapshot[path] = path.read_bytes() if path.exists() else None
        except OSError as error:
            raise RuntimeError(
                f"cannot preserve preflight refresh state: {path.name}"
            ) from error
    return snapshot


def _restore_preflight_refresh_state(
    snapshot: dict[Path, bytes | None],
) -> list[str]:
    failures: list[str] = []
    for path, content in snapshot.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write_bytes(path, content)
        except OSError:
            failures.append(f"preflight refresh rollback failed: {path.name}")
    return failures


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _register_started_run(
    args: argparse.Namespace,
    details: list[str],
    claimed: dict[str, Any] | None,
) -> bool:
    """Commit preflight identity, then atomically promote its transient claim."""

    try:
        evidence_path = preflight_evidence_path(args)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        claimed_run_id = str((claimed or {}).get("run_id") or "")
        if not claimed_run_id:
            raise ValueError("start claim has no opaque run id")
        # Persist every byte needed by later hooks before publishing this run as
        # active. A kill before the promotion leaves only a hook-owned transient
        # claim; a kill after it leaves complete runtime evidence.
        payload["agent_run_id"] = claimed_run_id
        write_json(evidence_path, payload)
        resync_gate_evidence_ledger(evidence_path, payload)
        run = register_run(
            args.project,
            evidence_path,
            payload.get("route") or {},
            payload.get("request_intake") or {},
            reuse_run_id=claimed_run_id,
        )
        if run.get("run_id") != claimed_run_id or run.get("state") != "running":
            raise ValueError("start claim was not promoted atomically")
        details.append("agent run registry: running")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        details.append("agent run registry: unavailable; start refused")
        return False
    # After promotion, never before: settling the earlier claims is only correct
    # once this run is the one that supersedes them. A failure here leaves extra
    # active claims, which costs this session its edit gate but not the start
    # itself, so it reports rather than refuses.
    try:
        superseded = settle_superseded_session_runs(
            args.project, keep_run_id=claimed_run_id
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        details.append(
            "agent run registry: superseded-run settle failed; "
            "earlier runs in this session may still deny edits"
        )
        return True
    if superseded:
        details.append(
            f"agent run registry: settled {len(superseded)} superseded run(s) "
            "from this runtime session"
        )
    return True


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
        _resume_run_for_closeout(args)
        touch_run(args.project, preflight_evidence_path(args))
    except (OSError, RuntimeError, ValueError, TypeError):
        return


def _resume_run_for_closeout(args: argparse.Namespace) -> None:
    """Return a pending-closeout run to an active state so it can finish its work.

    The closeout may stage or apply a skill-document change, and the edit gate
    only resolves session evidence for an active run. Pending closeout also
    tells the agent not to run repair-verify, so without this the run has no
    route back to an active state at all.

    The registry owns the decision: a general transition accepted any prior
    state, so replaying this on a run that had already completed resurrected it
    and put an extra active run back on the shared evidence path.
    """
    try:
        evidence_path = args.evidence or args.project / ".tao" / "preflight.json"
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        current_session = runtime_session()
        recorded_session = payload.get("runtime_session") or {}
        same_runtime_session = bool(
            current_session.get("runtime")
            and current_session.get("runtime") == recorded_session.get("runtime")
            and recorded_session_id(payload) == current_session.get("session_id")
        )
        resume_run_for_closeout(
            args.project,
            evidence_path,
            run_id=payload.get("agent_run_id"),
            same_runtime_session=same_runtime_session,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
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


def _refresh_started_context(
    args: argparse.Namespace,
    details: list[str],
    *,
    prior_repair_binding: dict[str, str] | None = None,
) -> bool:
    try:
        evidence_path = preflight_evidence_path(args)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        snapshot_path = context_snapshot_path(args.project)
        prior_failures: list[str] = []
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
        rebind_status = rebind_failure_checkpoints_after_required_doc_refresh(
            evidence_path=evidence_path,
            preflight=payload,
            prior_binding=prior_repair_binding or {},
            required_doc_drift=context_snapshot_failures_are_required_doc_drift(
                prior_failures
            ),
        )
        if rebind_status == REPAIR_REBIND_CONFLICT:
            raise ValueError("repair checkpoint ledger changed during context refresh")
        if rebind_status == REPAIR_REBOUND:
            details.append("repair checkpoints: rebound after required-doc drift")
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
            "cancel",
            "fingerprint",
            "handoff",
            "resume",
            "checkpoint",
            "gate",
            "gate-batch",
            "review",
            "finish",
            "skill-feedback",
            "skill-draft",
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
        "--intent-envelope",
        default="",
        help=(
            "runtime intent envelope as JSON or a path to it; when supplied it "
            "is the authority for intent, target and effect"
        ),
    )
    start.add_argument(
        "--approval-record",
        "--user-approval",
        dest="approval_record",
        default="",
        help=(
            "separate bound user approval record as JSON or a path; "
            "--user-approval is a compatibility alias; required when the "
            "effective route reaches git_write or above"
        ),
    )
    parser.add_argument(
        "--continuation-scope",
        default="",
        help=(
            "bounded prior scope for a terse follow-up; target context only, "
            "never current-request intent"
        ),
    )
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
        choices=("working-tree", "pathspec", "repo-hygiene", "local-config", "commit-range"),
        default="working-tree",
        help=(
            "declare whether review covers the whole working tree, explicit --review-path "
            "pathspecs, a destructive no-diff branch/worktree cleanup, allowlisted "
            "Git-ignored local agent config, or one exact --review-base..--review-head "
            "commit range"
        ),
    )
    review.add_argument(
        "--review-path",
        action="append",
        default=[],
        help="limit review hook changed-path, diff, and structure checks to this pathspec; repeat as needed",
    )
    review.add_argument(
        "--review-base",
        default="",
        help="base commit ref for --review-scope commit-range; resolved to an immutable commit SHA",
    )
    review.add_argument(
        "--review-head",
        default="",
        help="head commit ref for --review-scope commit-range; resolved to an immutable commit SHA",
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
    review.add_argument(
        "--max-added-lines",
        type=non_negative_int,
        default=REVIEW_ADDED_LINE_LIMIT,
        help=(
            "fail review when a changed development source/style file adds more than this many lines; "
            "raise it only for a file that cannot be split, such as one distributed as a single "
            "standalone artifact, and state the reason in the structure review evidence"
        ),
    )


def _add_finish_arguments(parser: argparse.ArgumentParser) -> None:
    finish = parser.add_argument_group("finish hook")
    finish.add_argument("--allow-vibeguard-review")


def _add_cancel_arguments(parser: argparse.ArgumentParser) -> None:
    cancel = parser.add_argument_group("transferred-run cancellation")
    cancel.add_argument(
        "--replacement-evidence",
        type=existing_path,
        help="completed linked-worktree preflight that replaced this clean source run",
    )


def _add_skill_feedback_arguments(parser: argparse.ArgumentParser) -> None:
    feedback = parser.add_argument_group("successful-task skill feedback")
    feedback.add_argument(
        "--skill-feedback-outcome",
        choices=("no_change", "observed"),
        default="no_change",
    )
    feedback.add_argument("--skill-id", default="")
    feedback.add_argument(
        "--feedback-signal",
        choices=tuple(sorted(FEEDBACK_SIGNALS)),
        default="",
        help="schema-owned content-free recurrence signal",
    )
    feedback.add_argument(
        "--draft-proposal",
        default="",
        help="bounded rationale for the proposed skill change",
    )
    feedback.add_argument(
        "--draft-proposal-file",
        default="",
        help="path holding the bounded rationale; preferred over --draft-proposal",
    )
    feedback.add_argument("--feedback-candidate-id", default="")
    feedback.add_argument(
        "--skill-review-outcome",
        choices=("no_change", "stage_patch"),
        default="no_change",
    )
    feedback.add_argument(
        "--feedback-gap",
        default="",
        help=(
            "safe slug naming which gap this is; pass it to skill-feedback so a "
            "later closeout can still review the candidate, and to skill-review "
            "when staging a patch"
        ),
    )
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
    add_checkpoint_arguments(parser)
    _add_review_arguments(parser)
    _add_finish_arguments(parser)
    _add_cancel_arguments(parser)
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
        # Only start is refused: a run already begun under an unbindable name
        # must still be able to review and finish.
        return unbindable_run_directory_error(args)
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


def _run_checkpoint_hook(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> int:
    if not args.checkpoint_kind:
        parser.error("checkpoint requires --checkpoint-kind")
    if args.mutation_kind and args.checkpoint_kind != "pre_mutation":
        parser.error("--mutation-kind is only valid for pre_mutation")
    return checkpoint_hook(args)


def _run_repair_verify_hook(args: argparse.Namespace) -> int:
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
    if success:
        # A verified repair is the only thing that retires a lesson. Without
        # this the inbox was write-only, so a signature kept counting up
        # (89 at the worst) with no way to ever record that it was fixed.
        promotion = promote_lessons_for_repair(
            str(repair_preflight.get("agent_run_id") or ""),
            str(result.get("receipt_id") or ""),
        )
        result["lesson_promotion"] = promotion
        promoted = promotion.get("promoted") or []
        if promoted:
            details.append(f"lessons promoted by this repair: {', '.join(promoted)}")
    return finish_with_result(
        "repair-verify",
        success,
        details,
        args.output,
        {"repair_verification": result},
        0,
    )


def _apply_repair_cycle_context(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
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
    repair_signature = checkpoint_failure_signature(
        route=repair_preflight.get("route") or {},
        evidence_path=repair_evidence_path,
        checkpoint=args.resume_checkpoint,
    )

    def release_failed_repair_invocation() -> None:
        release_repair_attempt(
            evidence_path=repair_evidence_path,
            preflight=repair_preflight,
            checkpoint=args.resume_checkpoint,
            failure_signature=repair_signature,
        )

    # Hook-specific CLI validation runs before the repair context is claimed.
    # Downstream pre-write validation can still reject an invocation after the
    # claim, so every such hook needs the same rollback that review already
    # used; otherwise the only repair cycle becomes unavailable.
    args.repair_invocation_rollback = release_failed_repair_invocation


def _fingerprint_hook(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Print the current request's fingerprint and an envelope skeleton.

    A work route needs an intent envelope carrying the exact request
    fingerprint, but before the first start the Claude gate only allows this
    runtime's own hooks -- generic interpreters that could compute the hash are
    denied. This helper is that sanctioned bootstrap: it reads nothing and
    writes no state, so it stays callable before any lifecycle exists.
    """

    if not args.request:
        parser.error("fingerprint requires --request with the exact current user request")
    fingerprint = request_fingerprint(
        {
            "request": args.request,
            "continuation_scope": getattr(args, "continuation_scope", ""),
            "request_classified": bool(args.request_classified),
            "classification_evidence": args.classification_evidence,
        }
    )
    skeleton = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "request_fingerprint": fingerprint,
        "runtime_session_id": runtime_session().get("session_id", ""),
        "mode": "work",
        "intent": "<safe_lowercase_slug>",
        "target_summary": "<one bounded line naming the work target>",
        "requested_effects": ["local_write"],
        "prohibited_effects": ["external_write"],
        "ambiguity": "resolved",
    }
    return finish_with_result(
        "fingerprint",
        True,
        [
            f"request fingerprint: {fingerprint}",
            "binding covers --request, --continuation-scope, --request-classified, "
            "and --classification-evidence exactly as passed here; pass identical "
            "values to start or the envelope will describe a different request",
            "envelope skeleton (fill intent, target_summary, effects, and the "
            "session id before use): " + json.dumps(skeleton, ensure_ascii=False),
        ],
        args.output,
        {"request_fingerprint": fingerprint, "envelope_skeleton": skeleton},
        args.repair_cycle,
    )


def _validate_hook_arguments_before_repair(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Reject hook-specific CLI errors before a repair attempt is claimed."""

    if args.hook == "start":
        if args.request_classified and not args.classification_evidence:
            parser.error("start --request-classified requires --classification-evidence")
        if not args.request:
            parser.error(
                "start requires --request with the real current request; only a delegated "
                "worker with a matching parent capsule may additionally use "
                "--request-classified"
            )
        return
    if args.hook == "review":
        args.review_path = [path.strip() for path in args.review_path if path.strip()]
        if args.review_path and args.review_scope == "working-tree":
            args.review_scope = "pathspec"
        if args.review_scope in {"pathspec", "local-config"} and not args.review_path:
            parser.error(
                f"review --review-scope {args.review_scope} requires at least one --review-path"
            )
        if args.review_scope == "commit-range":
            if args.review_path:
                parser.error("review --review-scope commit-range does not accept --review-path")
            if not str(getattr(args, "review_base", "") or "").strip() or not str(
                getattr(args, "review_head", "") or ""
            ).strip():
                parser.error(
                    "review --review-scope commit-range requires --review-base and --review-head"
                )
        elif str(getattr(args, "review_base", "") or "").strip() or str(
            getattr(args, "review_head", "") or ""
        ).strip():
            parser.error(
                "review --review-base and --review-head require --review-scope commit-range"
            )
        return
    if args.hook == "gate" and not args.gate_name:
        parser.error("gate requires --gate-name")



def _name_timing_sink(args: argparse.Namespace) -> None:
    """Point this process's stage durations at the run it is working in.

    Only the hook CLI names a sink, and only after the worker boundary has
    redirected the evidence path, so a worker's numbers land in the worker's
    run. `resume` is excluded because it promises to leave the registry
    byte-identical and resolving evidence would adopt a path it only reads.
    """

    if args.hook in ("resume", "fingerprint"):
        return
    try:
        set_timing_sink(preflight_evidence_path(args).parent / "timings.jsonl")
    except (OSError, RuntimeError, TypeError, ValueError):
        return

def main() -> int:
    parser = build_parser()
    args = _parse_args(parser)
    if args.hook == "fingerprint":
        # Answered entirely from the arguments: no evidence path, no worker
        # boundary, and no heartbeat -- a registry write here would turn the
        # pre-lifecycle helper into the mutation it exists to precede.
        return _fingerprint_hook(parser, args)
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
    _name_timing_sink(args)
    try:
        code = _dispatch_hook(parser, args)
    except SystemExit:
        # An argparse refusal is not a hook result, and recording one would
        # put a usage error in the run's durations.
        raise
    append_recorded_stages(args.hook, "SUCCESS" if code == 0 else "FAIL")
    return code


def _dispatch_hook(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the selected hook. Split from `main` so one invocation records once.

    The durations used to be appended by the shared result writer, which any
    caller of a hook function reached -- including a test process that had
    already resolved a live run. One invocation now names the sink, runs, and
    writes the line, so nothing else in the process can.
    """

    _validate_hook_arguments_before_repair(parser, args)
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
        if args.list_mode and args.resume_run_id:
            # Listing reports every unfinished run, so a silently ignored
            # --run-id would read as a filter that had been applied.
            parser.error("resume --run-id selects what --last claims; it does not filter --list")
        return resume_hook(args)
    if args.hook == "cancel":
        if not args.replacement_evidence:
            parser.error("cancel requires --replacement-evidence")
        return cancel_transferred_run(args)
    if args.hook == "checkpoint":
        return _run_checkpoint_hook(parser, args)
    if args.hook == "repair-verify":
        return _run_repair_verify_hook(args)
    if args.repair_cycle:
        _apply_repair_cycle_context(parser, args)
    if args.hook == "start":
        return start_hook(args)
    checkpointed = _checkpointed_hook(args)
    if checkpointed is not None:
        return checkpointed
    if args.hook == "handoff":
        return handoff_hook(args)
    if args.hook == "skill-feedback":
        return skill_feedback_hook(args)
    if args.hook == "skill-draft":
        return skill_draft_hook(args)
    if args.hook == "skill-curate":
        return skill_curate_hook(args)
    if args.hook == "skill-review":
        return skill_review_hook(args)
    if args.hook == "skill-maintenance":
        return skill_maintenance_hook(args)
    return finish_hook(args)


def _checkpointed_hook(
    args: argparse.Namespace,
) -> int | None:
    """Run a hook whose completion is a continuation lifecycle transition.

    A gate record, a batch of them and a review are the during-work points the
    packet must be refreshed at, so they dispatch together rather than each
    growing its own copy of the same side effect. ``None`` means this was not
    one of them.
    """

    if args.hook == "review":
        return checkpoint_after_hook(
            args,
            review_hook(
                args,
                run_command,
                git_status,
                vibeguard_command,
                parse_overall,
                finish_with_result,
                getattr(args, "repair_invocation_rollback", None),
            ),
            "lifecycle",
            phase="reviewing",
        )
    if args.hook == "gate":
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
