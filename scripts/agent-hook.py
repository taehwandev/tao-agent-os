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
from agent_continuation_fields import MAX_TEXT
from support.runtime_bridge import CODEX_PERMISSION_EVIDENCE_BRIDGE_PHRASE
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
from agent_review_reuse import ReviewReuse
from agent_required_doc_reuse import required_doc_reuse
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
from agent_task_affinity import task_affinity_denial
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
from agent_route_state import request_fingerprint, request_intake_from_args
from agent_runtime_session import recorded_session_id, runtime_session, settle_superseded_session_runs
from agent_transfer_cancel import (
    cancel_no_change_run,
    cancel_transferred_run,
    cancellation_receipt_failure,
    cancellation_worktree_drift,
)
from workflow_effect_policy import (
    APPROVAL_REQUIRED_FROM,
    canonical_route_command,
    route_minimum_effect,
)
from workflow_intent_envelope import (
    EFFECT_RANK,
    EFFECTS,
    SAFE_SLUG_EXAMPLE,
    SAFE_SLUG_PATTERN,
    SCHEMA_VERSION as ENVELOPE_SCHEMA_VERSION,
    intent_slug_failure,
    normalize_intent_slug,
    read_approval_record,
    read_intent_envelope,
)
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
    for path in getattr(args, "surface_path", []):
        command.extend(["--surface-path", path])
    if args.read_only:
        command.append("--read-only")
    if args.evidence:
        command.extend(["--evidence", str(args.evidence)])
    if args.worker_reservation_token:
        command.extend(["--worker-reservation-token", args.worker_reservation_token])
    return command


def start_hook(args: argparse.Namespace) -> int:
    from agent_work_continuity import WorkContinuity
    try:
        continuity = WorkContinuity(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return finish_with_result("start", False, [str(error)], args.output, {},
                                  args.repair_cycle, invocation_error=True)
    request_intake = {
        "request": args.request,
        "continuation_scope": getattr(args, "continuation_scope", ""),
        "request_classified": bool(args.request_classified),
        "classification_evidence": args.classification_evidence,
    }
    writable_route = (
        not args.read_only
        and EFFECT_RANK[route_minimum_effect(args.command)] > EFFECT_RANK["read"]
    )
    affinity_denial = (
        task_affinity_denial(args.project, request_intake)
        if writable_route
        else None
    )
    if affinity_denial:
        return finish_with_result(
            "start",
            False,
            [affinity_denial],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    return _start_admitted_action(args, continuity, request_intake)


def _start_admitted_action(args: argparse.Namespace, continuity: Any, request_intake: dict[str, Any]) -> int:
    # Establish the local-only state root before anything writes into it. The
    # continuation store proves local-only status by asking Git, so a checkout
    # that has never been ignored refuses every packet write -- and the Claude
    # pre-tool gate turned that refusal into a denial of every edit.
    ensure_local_only_state_dir(args.project)
    evidence_path = preflight_evidence_path(args)
    prior_repair_binding = capture_failure_checkpoint_binding(evidence_path)
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
            try:
                retained = json.loads(refresh_snapshot.get(evidence_path) or b"{}")
                details.extend(continuity.apply(evidence_path, retained_work=retained.get("work")))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                details.append(f"work continuation failed: {error}")
                success = False
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


def _isolated_run_preflight(path: Path, payload: dict[str, Any]) -> bool:
    try:
        project = Path(payload["project"]).resolve()
        resolved = path.resolve()
        run_id = resolved.parent.name
        return (
            resolved.name == "preflight.json"
            and resolved.parent.parent == project / ".tao" / "runs"
            and len(run_id) == 32
            and all(character in "0123456789abcdef" for character in run_id)
        )
    except (OSError, TypeError, KeyError):
        return False


def _release_reuse_lines(command: str) -> list[str]:
    if command not in {"release", "ship"}:
        return []
    lines: list[str] = []
    lines.append(
        "Release authority: continue explicitly approved same-target/version repairs and retries. "
        "A new SHA requires affected verification, not automatically another user confirmation. "
        "Stop for changed scope/risk, revoked or limited authority, or unapproved tag overwrite."
    )
    lines.append(
        "Release reuse: a follow-up request is not verification invalidation. "
        "Reuse observed passing tests, reviews and retained artifacts for matching "
        "covered inputs; compare source, build flags, version, toolchain and relevant "
        "environment, including embedded revision/signing/provenance metadata. "
        "Rebuild only for changed or unverified inputs, missing/changed artifacts, "
        "or an explicit rebuild request. Refresh mutable remote/target facts and "
        "applicable approval; verify this deployment's result and required live smoke. "
        "Prior local success cannot prove current CI signing, notarization or publication."
    )
    lines.append(
        "Deployment monitoring: once the exact deployment is identified, use one "
        "authoritative status source at bounded intervals. Pending is not failure. "
        "Read bounded relevant logs on failure, stalled progress or explicit request; "
        "do not dump complete build logs or re-review unchanged source while waiting."
    )
    return lines


def _publication_continuity_guidance() -> str:
    return (
        "Publication continuity: declare authority for the full currently authorized "
        "outcome at entry. After finish, continue only its authorized commit/push/PR "
        "steps without another start, review or finish while scope and evidence "
        "remain valid. A program change is not a scope change. Report completion "
        "once the requested external results are confirmed. Do not infer authority "
        "from request keywords or from finish itself."
    )


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
    reading_scope = route.get("reading_scope") or {}
    if reading_scope.get("mode") == "lookup" and reading_scope.get("guidance"):
        lines.append(str(reading_scope["guidance"]))
    if (payload.get("runtime_session") or {}).get("runtime") == "codex":
        lines.append(CODEX_PERMISSION_EVIDENCE_BRIDGE_PHRASE)
    scope_change_policy = route.get("scope_change_policy") or {}
    if scope_change_policy.get("mode") == "on_material_change":
        lines.append(
            "Scope-change lifecycle: No intermediate gate or checkpoint while the "
            "start scope A is unchanged. If A expands to A+B, record one semantic "
            "checkpoint. Start a new route only when the project, authority, effect "
            "ceiling, or external target changes. Finish with the route's final tests "
            "and review."
        )
    docs = route.get("required_docs") or []
    if docs:
        reuse = {"reused": [], "unread": list(docs)}
        if _isolated_run_preflight(path, payload):
            candidate = required_doc_reuse(path)
            if candidate["reused"] or candidate["unread"]:
                reuse = candidate
        if reuse["reused"]:
            lines.append(
                "Matching completed same-session evidence "
                f"({len(reuse['reused'])} unchanged required docs; reuse retained readings):"
            )
            lines.extend(f"  {doc}" for doc in reuse["reused"])
        if reuse["unread"]:
            lines.append(f"Required knowledge ({len(reuse['unread'])} required docs; "
                         "no matching history proof, not proof of unread context):")
            lines.extend(f"  {doc}" for doc in reuse["unread"])
        lines.append(
            "Reading boundary: reference docs are on demand, not a recursive reading "
            "queue. Reuse a complete reading only while unchanged and available in "
            "current context; otherwise read it. Missing history proof does not require "
            "another read or a separate reuse check when guidance is retained. Expand only for an unresolved "
            "in-scope question. Keep read results within both per-call and batch "
            "output limits; recover only missing ranges after truncation, never "
            "repeat a whole truncated batch. Discover uncertain paths with rg --files or quoted "
            "rg -g filters, not speculative shell globs; no-match is not a retry cue."
        )
        lines.append(f"Checkpoint input: objective is limited to {MAX_TEXT} Unicode characters; "
                     "checkpoint --work-template prints minimal JSON; --work-shape describes optional fields.")
    if route.get("command") == "analysis":
        lines.append(
            "Analysis transition: finish this read-only run before starting a writing route "
            "when the user expands the task. A later finish does not close this run. "
            "A failed gate still requires the bound failure-repair lifecycle; do not silently cancel it."
        )
    if route.get("command") in {"commit", "git_commit"}:
        candidate = (
            ReviewReuse.publication_candidate(path)
            if _isolated_run_preflight(path, payload)
            else None
        )
        if candidate:
            lines.append(
                "Publication review reuse: exact prior attestation covers "
                f"{len(candidate['changed_paths'])} unchanged paths:"
            )
            lines.extend(f"  {changed}" for changed in candidate["changed_paths"])
            lines.append(
                "Do not search, reopen, or manually review these files again. "
                "Stage exactly these paths, then call review once; it will validate "
                "current staged scope and drift. Any mismatch falls back to full review."
            )
        lines.append(
            "Commit reuse: distinguish already-known context from fresh checks in "
            "the existing checkpoint; no separate inventory call. Reuse unchanged "
            "rules and verification for the exact covered diff. Fresh checks: staged "
            "scope, review binding, branch/remote and PR state. Changed bytes or "
            "missing context require the relevant read/check; prior approval does "
            "not authorize new external writes."
        )
        lines.append(
            "Publication scope: a failed check is not source-change authority; "
            "do not switch to implementation or waive a guard without matching scope. "
            "Continue an approved identical pending action without reconfirming "
            "unless scope, target, risk or required approval freshness changed. "
            "Do not retry an unchanged known failure."
        )
    lines.extend(_continuation_summary_lines(route.get("command", "")))
    if required:
        lines.append(f"Required hooks: {required}")
    if conditional:
        lines.append(f"Conditional hooks: {conditional}")
    gates = [gate for gate in (route.get("gates") or []) if isinstance(gate, str)]
    if "review" in required or "review hook" in gates:
        flags = required_review_evidence_flags(gates)
        lines.extend(_review_prerequisite_lines(gates))
        lines.append("Review hook requires --review-outcome pass or findings, matching the actual review result.")
        lines.append(
            "Review hook requires the evidence itself, not a file path holding it: "
            + " ".join(flags)
        )
        lines.append(
            "Review hook conditionally requires --structure-review-evidence when changed "
            "development files exceed review-pressure or source-size limits."
        )
        lines.extend(_closeout_reuse_lines())
    elif "review" in conditional:
        lines.append(
            "Conditional review: review only if a diff is created or a commit is requested; "
            "then use review --help for evidence fields. No review for no-diff cleanup."
        )
    lines.extend(_closeout_gate_lines(gates) + _gate_batch_guidance_lines(gates))
    lines.extend(_structured_gate_field_lines(gates))
    return lines


def _continuation_summary_lines(command: str) -> list[str]:
    publication = [_publication_continuity_guidance()] if command in {"commit", "git_commit"} else []
    return _release_reuse_lines(command) + publication + [
        "Work continuity: a goal iteration is not a new intake. Within approved scope, "
        "keep the active action; retain guidance, decisions and verification plan. Read "
        "only changed, newly applicable or lost context; a new run does not erase retained "
        "readings. Keep changed-unit tests and required pre-commit review/finish. A "
        "completed run is not writable: when another action needs admission, use "
        "start --continue-from <previous run id>; add --reuse-inputs "
        "with observed matching scope, toolchain, artifacts and external inputs to carry valid "
        "local gates automatically. Use the returned remaining gates, not a rewritten checklist. "
        "Work identity does not grant authority or carry remote results/review. Unrelated work "
        "omits --continue-from; paused goals require explicit resume. Request wording "
        "never establishes this relationship."
    ]


def _review_prerequisite_lines(gates: list[str]) -> list[str]:
    if "review hook" not in gates:
        return []
    prerequisites = gates[:gates.index("review hook")]
    return [
        f"Before review, record successful evidence for: {prerequisites}. "
        "Passing a test command alone does not record its gate. Use the "
        "gate-batch remaining list; do not call review to discover missing records."
    ]


def _closeout_reuse_lines() -> list[str]:
    """Keep final review monotonic instead of reopening implementation loops."""

    return [
        "Closeout reuse: unchanged HEAD, worktree bytes, target, and external freshness reuse "
        "completed reads and test/build/device evidence; review the final diff once. Edit a "
        "review finding only when reproducer, impact, current-diff causality, owner, and the "
        "nearest falsifying check prove a blocking regression. Otherwise record a follow-up. "
        "Allow one repair, then rerun only the affected check and incremental review. Use the "
        "advertised review shape, its VibeGuard result, and gate-batch remaining gates; do not "
        "repeat an audit, use --help, dump the ledger, or retry another design during closeout."
    ]


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
        "gate-batch; its remaining-gates snapshot avoids a separate ledger query. "
        "One invocation writes one strong continuation checkpoint. Keep "
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
    lines = [
        "Gates requiring named fields (--field name=value). "
        'gate-batch --gate-record shape: [{"gate":"<active gate>",'
        '"status":"<SUCCESS or FAIL>","fields":{"<listed field>":"<observed evidence>"}}]. '
        "Replace placeholders using the fields and enum values below; reuse observed "
        "results rather than rerunning checks to fill a record.",
    ]
    from agent_gate_reuse import GateEvidenceReuse
    if any(GateEvidenceReuse.supports(gate) for gate in gates):
        lines[0] += ' Local evidence: record input_paths: [] in gate-batch for revision-independent checks (all project files), or a complete dependency list. Omit for revision-sensitive/uncertain inputs. Never copy old records as fresh evidence.'
    for gate, fields in required:
        lines.append(f"  {gate}: {_rendered_fields(gate, fields)}")
        if gate in {"documentation", "documentation impact"}:
            lines.append("    unchanged: use inspected=<exact source read> and coverage=<why it still applies>; retained valid readings need no reread.")
        # Several of these gates then decide by substring match, so a truthful
        # sentence the matcher does not recognise is refused after the work is
        # done -- the largest recurring failure class in the lesson store. The
        # phrases are the contract; stating them here costs one line each and
        # saves the refusal that teaches them.
        lines.extend(f"    wording -- {hint}" for hint in gate_wording_hints(gate))
        if gate == "work surface resolution":
            lines.append("    evidence chain: include the literal -> separator from anchor to verified owner.")
        if gate == "retrospective check":
            lines.append(
                "    skills_checked: use canonical skill slugs such as agent_operating_skill, "
                "not file paths; include a skill actually loaded by this run."
            )
            lines.append(
                "    efficiency: no_waste|unmeasured|improvement_needed; include efficiency_evidence. "
                "For improvement_needed include efficiency_cause, efficiency_reduction, "
                "efficiency_verification and use reusable_gap with existing same-closeout maintenance. "
                "Reuse current evidence; do not add discovery or weaken required checks."
            )
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
        from agent_publication_admission import PublicationAdmission

        captured = PublicationAdmission.record_finish(args.project, preflight_evidence_path(args))
        details.append("publication inputs: captured" if captured else
                       "publication inputs: unavailable; this finish does not admit post-finish publication")
        # Complete the registry first. If the process dies between these two
        # writes, the run is already terminal and cannot be resumed from a
        # packet that still displays the pre-finish checkpoint.
        _transition_finished_run(args, True)
        details.append(
            "This run is closed; finish attests verification, not execution of pending "
            "actions. Continue already-authorized steps within the same verified scope "
            "without reopening this lifecycle. Once the requested outcome is confirmed, "
            "report it; do not repeat review or finish merely to close publication. "
            "New effects, targets or changed evidence still require matching admission. "
            "A fast-forward of this worktree's HEAD into the same repository's main "
            "checkout (git -C <main> merge --ff-only <HEAD>) is admitted by this finish "
            "while the worktree stays clean and unchanged; do not open a commit route "
            "for it."
        )
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
    intrinsic_analysis_drift = any(
        _is_intrinsic_analysis_drift(line) for line in failure_lines
    )
    required_doc_refresh_lines = (
        "FAIL: execution capsule required doc size changed: ",
        "FAIL: execution capsule required doc hash changed: ",
        "FAIL: execution capsule required doc changed after documentation evidence: ",
        "FAIL: required-doc drift recovery: ",
        "FAIL: retrospective repair is required before final report, commit, release, or handoff; ",
    )
    only_refreshable_drift = all(
        line in refreshable_failures
        or line.startswith(required_doc_refresh_lines)
        or _is_intrinsic_analysis_drift(line)
        for line in failure_lines
    )
    return (
        result.get("returncode") == 1
        and bool(failure_lines)
        and (stale_review or stale_required_docs or intrinsic_analysis_drift)
        and only_refreshable_drift
    )


def _is_intrinsic_analysis_drift(line: str) -> bool:
    """Whether this failure is an analysis run an upstream write overtook.

    Two callers ask the same question of the same line -- whether any failure
    is this one, and whether every failure is refreshable -- and the three-part
    match was written out twice. A wording change to one copy and not the other
    would leave the wrapper offering a refresh it then refuses to apply.
    """

    return (
        line.startswith("FAIL: read-only execution was declared but the ")
        and " root changed after start; " in line
        and "the analysis route is intrinsically read-only; wait for concurrent writers "
        "to settle, then rerun start and finish with refreshed workspace fingerprints"
        in line
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
        # Neither of these was printed anywhere, and a run now lives in a
        # directory named by an opaque id, so the only way to reach it was to
        # guess: one session spent eight of its thirteen hook calls on that,
        # recorded gates against a stray ledger it had named as `--evidence`,
        # and was told at `review` that the run id was not bound. The path is
        # stated once, and so is the fact that naming it is usually needless.
        details.append(f"run id: {claimed_run_id}")
        details.append(f"evidence: {evidence_path}")
        details.append(
            "later hooks in this runtime session find this run on their own; "
            "pass --evidence only for a worker's issued evidence path or from "
            "another session, and only ever this exact preflight.json"
        )
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
                "Retrospective repair required:",
                "Closeout retrospective:",
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
    parser.add_argument(
        "--resume-checkpoint", default="",
        type=lambda value: "review" if value.strip() == "review hook" else value.strip(),
        help="failed checkpoint name; 'review hook' is an alias for 'review'",
    )
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
    start.add_argument("--continue-from", default="", help="prior registered action of the same work; never inherits authority")
    start.add_argument("--reuse-inputs", default="", help="runtime attestation of unchanged verification scope, toolchain, artifacts and external inputs, independent of commit metadata")
    start.add_argument("--commit-ready", action="store_true", help="prepare exact staged, completed same-session review for commit; never commits")
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
    start.add_argument(
        "--intent",
        default="",
        help=(
            "safe intent slug for compact authority input, matching "
            f"{SAFE_SLUG_PATTERN} (for example {SAFE_SLUG_EXAMPLE}; hyphens are "
            "folded to underscores): a short reusable category name, never the "
            "request text. start binds it to the current request and runtime "
            "session without a separate fingerprint call"
        ),
    )
    start.add_argument(
        "--target-summary",
        default="",
        help="one bounded target line for compact authority input",
    )
    start.add_argument(
        "--requested-effect",
        choices=EFFECTS,
        default="",
        help="optional effect claim; defaults to the selected route's minimum effect",
    )
    start.add_argument(
        "--approved-effect",
        choices=EFFECTS,
        default="",
        help=(
            "effect ceiling explicitly authorized by the current request; required "
            "for compact git_write, external_write, and destructive starts"
        ),
    )
    start.add_argument(
        "--prohibited-effect",
        action="append",
        choices=EFFECTS,
        default=[],
        help="effect prohibited by the current request; repeat when needed",
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
    start.add_argument("--surface-path", action="append", default=[],
                       help="repository-verified owner path for guidance routing")
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
    cancel = parser.add_argument_group("run cancellation")
    cancel.add_argument(
        "--replacement-evidence",
        type=existing_path,
        help=(
            "completed preflight from another checkout of this repository that "
            "replaced this clean source run"
        ),
    )
    cancel.add_argument(
        "--no-change-evidence",
        help=(
            "why this run correctly produced no diff; settles it as cancelled "
            "once the checkout is clean and its packet records no changed scope"
        ),
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
    return _not_preflight_evidence_error(args.evidence, payload)


def _not_preflight_evidence_error(evidence: Path, payload: object) -> str:
    """Refuse a run side-file that was named where the preflight belongs.

    A run directory holds the gate ledger and the continuation packet beside
    the preflight, and the ledger is the one that looks usable. Named as
    `--evidence` it made `gate-batch` report SUCCESS while writing a *second*
    ledger beside the first (`gate-evidence-gate-evidence.json`), so those
    gates went where no finish would read them. `review` was the first call to
    object, several hooks later, and its message named an unbound run id
    rather than the file that caused it.

    Each side-file is identified by fields only it carries, never by the
    absence of the preflight's own: evidence written before a field existed,
    including an empty object, is a run that started and must still be able to
    review and finish. The ledger records which preflight it belongs to, so
    the refusal names the exact file to pass rather than describing one.
    """

    if not isinstance(payload, dict):
        return ""
    recorded = payload.get("preflight_evidence")
    is_ledger = isinstance(recorded, str) and isinstance(payload.get("entries"), list)
    is_packet = all(
        isinstance(payload.get(field), dict) for field in ("binding", "work", "drift")
    )
    if not is_ledger and not is_packet:
        return ""
    named = recorded if is_ledger and recorded else str(evidence.parent / "preflight.json")
    return (
        f"--evidence must name this run's preflight evidence; {evidence.name} is the "
        f"{'gate ledger' if is_ledger else 'continuation packet'} beside it. Pass "
        f"{named}, or omit --evidence and let the hook resolve the run bound to this "
        "runtime session"
    )


def _lifecycle_output_error(args: argparse.Namespace) -> str:
    """Reject a diagnostic result path before a costly lifecycle hook runs."""

    if not args.output:
        return ""
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=args.output.parent,
            prefix=".tao-output-probe-",
        ):
            pass
    except OSError as error:
        return (
            f"--output parent is not writable ({type(error).__name__}); "
            "omit --output, choose a writable result location, or relaunch with "
            "the current project as the writable primary workspace"
        )
    return ""


def _run_cancel_hook(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> int:
    """Route the two ways a run can be settled without finishing it.

    They are mutually exclusive on purpose. A transfer says another run did the
    work; a no-change close says the work was correctly not done. Accepting both
    at once would let a caller claim a replacement finished a run that also
    changed nothing, which is two different stories about one run.
    """

    if bool(args.replacement_evidence) == bool(args.no_change_evidence):
        parser.error(
            "cancel requires exactly one of --replacement-evidence, when a "
            "completed run in another checkout of this repository replaced this "
            "one, or --no-change-evidence, when this run correctly produced no diff"
        )
    unresolved = _bind_cancelled_run_evidence(args)
    if unresolved:
        return finish_with_result(
            "cancel", False, [unresolved], args.output, {}, args.repair_cycle,
            invocation_error=True,
        )
    if args.replacement_evidence:
        return cancel_transferred_run(args)
    return cancel_no_change_run(args)


def _bind_cancelled_run_evidence(args: argparse.Namespace) -> str:
    """Name the run this cancellation settles, or say why it cannot be found.

    A cancellation is most often needed exactly when the run is no longer
    active -- parked at `reconcile_required` by a refused resume, or left
    `interrupted` by a turn boundary -- and those states are outside the active
    binding every other hook resolves through. `args.evidence` was then `None`
    all the way into the registry, where the first thing done to it is
    `.resolve()`: the hook that exists to settle a stranded run crashed with a
    traceback on the stranded run. Resolving the settleable states here keeps
    the omission an ordinary message, and keeps the path the registry receives
    a real one.
    """

    if args.evidence:
        return ""
    session = runtime_session()
    if not session:
        return (
            "cancel needs the run's evidence path: no runtime session is set, so "
            "the run cannot be resolved. Pass --evidence <run>/preflight.json"
        )
    from agent_run_registry import TRANSFER_CANCELLABLE_RUN_STATES
    from agent_runtime_session import resolve_runtime_evidence

    resolved = resolve_runtime_evidence(
        args.project, session, TRANSFER_CANCELLABLE_RUN_STATES
    )
    if resolved is None:
        return (
            "cancel found no single settleable run bound to this runtime session "
            "in this project. Pass --evidence <run>/preflight.json for the exact "
            "run to settle"
        )
    args.evidence = resolved
    return ""


def _run_checkpoint_hook(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> int:
    # `--work-shape` writes no checkpoint; it answers what one must contain, so
    # the start hook can name it instead of reprinting it every session.
    if getattr(args, "work_template", False) and any((
        args.checkpoint_kind, args.work_stdin, args.work_shape, args.mutation_kind,
        args.mutation_path, args.phase, args.last_completed,
    )):
        parser.error("--work-template cannot be combined with checkpoint inputs")
    if not args.checkpoint_kind and not (
        getattr(args, "work_shape", False) or getattr(args, "work_template", False)
    ):
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
    if result.get("diagnostic"):
        details.append(str(result["diagnostic"]))
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

    if args.output is not None:
        parser.error("fingerprint is stdout-only; --output is not supported")
    if not args.request:
        parser.error("fingerprint requires --request with the exact current user request")
    fingerprint = request_fingerprint(request_intake_from_args(args))
    effect = route_minimum_effect(args.command)
    skeleton = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "request_fingerprint": fingerprint,
        "runtime_session_id": runtime_session().get("session_id", ""),
        "mode": "work",
        "intent": "<safe_lowercase_slug>",
        "target_summary": "<one bounded line naming the work target>",
        "requested_effects": [effect],
        "ambiguity": "resolved",
    }
    approval_skeleton = None
    if EFFECT_RANK[effect] >= EFFECT_RANK[APPROVAL_REQUIRED_FROM]:
        approval_skeleton = {
            "request_fingerprint": fingerprint,
            "target_summary": "<same bounded target line as the envelope>",
            "effect": effect,
            "command": args.command,
        }
    details = [
        f"request fingerprint: {fingerprint}",
        "binding covers --request, --continuation-scope, --request-classified, "
        "and --classification-evidence exactly as passed here; pass identical "
        "values to start or the envelope will describe a different request",
        "envelope skeleton (fill intent, target_summary, and the session id before use): "
        + json.dumps(skeleton, ensure_ascii=False),
    ]
    if approval_skeleton is not None:
        details.append(
            "approval skeleton (use only when the current request authorizes this effect): "
            + json.dumps(approval_skeleton, ensure_ascii=False)
        )
    return finish_with_result(
        "fingerprint",
        True,
        details,
        args.output,
        {
            "request_fingerprint": fingerprint,
            "envelope_skeleton": skeleton,
            "approval_skeleton": approval_skeleton,
        },
        args.repair_cycle,
    )


def _materialize_compact_start_authority(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Bind typed start metadata without a fingerprint/JSON round trip.

    The runtime still chooses the route, intent, target, and any approval
    ceiling from the conversation. Tao derives only deterministic values it
    already owns: the request fingerprint, current session id, route effect
    floor, envelope shape, and approval binding. Natural-language text never
    selects a route or grants an effect here.

    Every input problem is reported at once. Each of these refusals ends a
    `start` call, and answering them one at a time is how a single task spent
    four calls in forty-five seconds: a missing effect flag, then a malformed
    slug, then the next thing.
    """

    intent = normalize_intent_slug(getattr(args, "intent", ""))
    target = str(getattr(args, "target_summary", "") or "").strip()
    requested = str(getattr(args, "requested_effect", "") or "").strip()
    approved = str(getattr(args, "approved_effect", "") or "").strip()
    prohibited = list(getattr(args, "prohibited_effect", []) or [])
    compact = bool(intent or target or requested or approved or prohibited)
    if not compact:
        _canonicalize_publication_start(parser, args)
        return
    if args.intent_envelope or args.approval_record:
        parser.error(
            "compact start authority cannot be combined with --intent-envelope or "
            "--approval-record"
        )
    problems: list[str] = []
    if not intent or not target:
        problems.append("compact start authority requires --intent and --target-summary")
    elif intent_slug_failure(intent):
        problems.append(f"--intent `{intent}` {intent_slug_failure(intent)}")
    args.intent = intent

    active_session_id = str(runtime_session().get("session_id") or "")
    supplied_session_id = str(getattr(args, "runtime_session_id", "") or "")
    if active_session_id and supplied_session_id and active_session_id != supplied_session_id:
        problems.append("--runtime-session-id does not match the current runtime session")
    session_id = active_session_id or supplied_session_id
    if not session_id:
        problems.append(
            "compact start authority requires a runtime session binding; the active "
            "runtime did not expose one"
        )

    route_effect = route_minimum_effect(args.command)
    requested_effect = requested or route_effect
    # Approving an effect for this request is also asking for it. Read any
    # other way, `--approved-effect git_write` on a `local_write` route was a
    # contradiction the caller had to resolve by repeating itself in
    # `--requested-effect`, and the refusal it got said the approval was
    # unnecessary -- the opposite of what was missing. Nothing widens here that
    # the caller did not already declare: the approval is the ceiling the
    # runtime states the current request authorizes, and the envelope still
    # records requested and approved as the same effect.
    if not requested and approved and EFFECT_RANK[approved] > EFFECT_RANK[requested_effect]:
        requested_effect = approved
    effective_effect = max(
        (requested_effect, route_effect),
        key=EFFECT_RANK.__getitem__,
    )
    if EFFECT_RANK[effective_effect] >= EFFECT_RANK[APPROVAL_REQUIRED_FROM]:
        if not approved:
            problems.append(
                f"compact `{args.command}` start reaches `{effective_effect}`; pass "
                "--approved-effect only when the current request authorizes that ceiling"
            )
        elif EFFECT_RANK[approved] < EFFECT_RANK[effective_effect]:
            problems.append(
                f"--approved-effect {approved} is below the effective "
                f"{effective_effect} ceiling"
            )
    elif approved:
        # Only reachable below the approval threshold now, which is what the
        # sentence has always claimed: an approval record is what `git_write`
        # and above require, and nothing below it consults one.
        problems.append(
            f"--approved-effect {approved} is unnecessary: an approval record is "
            f"required only from `{APPROVAL_REQUIRED_FROM}` up"
        )
    if problems:
        parser.error("; ".join(problems))

    fingerprint = request_fingerprint(request_intake_from_args(args))
    envelope: dict[str, Any] = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "request_fingerprint": fingerprint,
        "runtime_session_id": session_id,
        "mode": "work",
        "intent": intent,
        "target_summary": target,
        "requested_effects": [requested_effect],
        "ambiguity": "resolved",
    }
    if prohibited:
        envelope["prohibited_effects"] = prohibited
    args.intent_envelope = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    args.runtime_session_id = session_id
    if approved:
        args.approval_record = json.dumps(
            {
                "request_fingerprint": fingerprint,
                "target_summary": target,
                "effect": approved,
                "command": args.command,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    _canonicalize_publication_start(parser, args)


def _canonicalize_publication_start(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Fold PR shorthand into commit after preserving its external-write floor.

    The approval is rebound only from the exact alias being normalized. Other
    route bindings stay untouched and fail normally, so this cannot repair or
    widen an unrelated approval record.
    """

    original = str(args.command)
    canonical = canonical_route_command(original)
    if canonical == original:
        return
    envelope = read_intent_envelope(getattr(args, "intent_envelope", ""))
    effects = envelope.get("requested_effects", []) if isinstance(envelope, dict) else []
    if not any(
        isinstance(effect, str)
        and effect in EFFECT_RANK
        and EFFECT_RANK[effect] >= EFFECT_RANK["external_write"]
        for effect in effects
    ):
        parser.error(
            f"publication alias `{original}` requires an `external_write` request; "
            "use compact start with --approved-effect external_write or bind an "
            "equivalent compatibility envelope"
        )
    approval = read_approval_record(getattr(args, "approval_record", ""))
    if isinstance(approval, dict) and approval.get("command") == original:
        approval = dict(approval)
        approval["command"] = canonical
        args.approval_record = json.dumps(
            approval,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    args.command = canonical


def _validate_hook_arguments_before_repair(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Reject hook-specific CLI errors before a repair attempt is claimed."""

    if getattr(args, "commit_ready", False) and args.hook != "start":
        parser.error("--commit-ready is supported only by start --command commit")
    if args.hook != "start" and (getattr(args, "continue_from", "") or getattr(args, "reuse_inputs", "")):
        parser.error("work continuation arguments are supported only by start")
    if args.hook == "start":
        if args.request_classified and not args.classification_evidence:
            parser.error("start --request-classified requires --classification-evidence")
        if not args.request:
            parser.error(
                "start requires --request with the real current request; only a delegated "
                "worker with a matching parent capsule may additionally use "
                "--request-classified"
            )
        _materialize_compact_start_authority(parser, args)
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
    from agent_lookup_start import lookup_start

    lookup_result = lookup_start(args)
    if lookup_result is not None:
        return lookup_result
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
    lifecycle_output_error = _lifecycle_output_error(args)
    if lifecycle_output_error:
        parser.error(lifecycle_output_error)
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
        return _run_cancel_hook(parser, args)
    if args.hook == "checkpoint":
        return _run_checkpoint_hook(parser, args)
    if args.hook == "repair-verify":
        return _run_repair_verify_hook(args)
    if args.repair_cycle:
        _apply_repair_cycle_context(parser, args)
    if args.hook == "start":
        if getattr(args, "commit_ready", False):
            from agent_commit_ready import prepare_commit
            return prepare_commit(args, start_hook, lambda step: _dispatch_hook(parser, step))
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
