"""Runtime helpers shared by the Tao Agent OS hook CLI."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_outbound import assert_no_continuation_outbound
from agent_repair_ledger import (
    checkpoint_failure_signature,
    checkpoint_has_recorded_failure,
    register_repair_attempt,
)
from agent_repair_receipt_validation import validate_repair_receipt
from workflow_common import (
    REPAIR_CYCLE_LIMIT,
    REPAIR_POLICY,
    REPAIR_STOP_CONDITION,
    RESUME_SCOPE,
)
from support.stage_timing import recorded_stages

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
REVIEW_CHANGED_PATH_LIMIT = 25


def clean_output(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "stdout": clean_output(result.stdout),
        "stderr": clean_output(result.stderr),
    }


def vibeguard_command(project: Path, rules: Path) -> list[str]:
    binary = shutil.which("vibeguard")
    if binary:
        return [binary, "audit", str(project), "--rules", str(rules)]
    return [
        "npx",
        "--yes",
        "@taehwandev/vibeguard",
        "audit",
        str(project),
        "--rules",
        str(rules),
    ]


def parse_overall(output: str) -> str:
    for raw_line in clean_output(output).splitlines():
        line = raw_line.strip()
        if line.startswith("Overall:"):
            value = line.split("Overall:", 1)[1].strip()
            if "Ready" in value:
                return "Ready"
            if "Needs review" in value:
                return "Needs review"
            if "Blocked" in value:
                return "Blocked"
            return value or "unknown"
    return "unknown"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    assert_no_continuation_outbound(
        {"path": path, "payload": payload},
        boundary="diagnostic",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_status(name: str, success: bool, details: list[str]) -> None:
    print(f"{'SUCCESS' if success else 'FAIL'} {name}")
    for detail in details:
        print(f"- {detail}")


def git_status(project: Path) -> tuple[dict[str, Any], list[str]]:
    result = run_command(["git", "status", "--short", "--untracked-files=all"], project)
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return result, lines


def finish_with_result(
    name: str,
    success: bool,
    details: list[str],
    output: Path | None,
    payload: dict[str, Any],
    repair_cycle: int,
    invocation_error: bool = False,
    pending_closeout: bool = False,
    refreshable_failure: bool = False,
    fresh_start_required: bool = False,
) -> int:
    policy, policy_details = hook_failure_policy(
        success,
        repair_cycle,
        invocation_error=invocation_error,
        pending_closeout=pending_closeout,
        refreshable_failure=refreshable_failure,
        fresh_start_required=fresh_start_required,
    )
    details = [*details, *policy_details]
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hook": name,
        "status": "SUCCESS" if success else "FAIL",
        "policy": policy,
        "details": details,
        # Stage names and durations only, for the callers that ask for this
        # record. Most do not: `output` is optional, and the lifecycle's own
        # review and finish invocations omit it, which is why the hook entry
        # also appends them to a run-local file once per invocation.
        **({"timings": recorded_stages()} if recorded_stages() else {}),
        **payload,
    }
    if output:
        try:
            write_json(output, evidence)
        except OSError as error:
            # A requested result file is diagnostic output, not permission to
            # turn an otherwise useful hook result into a Python traceback.
            # The CLI probes the parent before costly hooks, but the fallback
            # still owns races such as a workspace becoming read-only while a
            # hook is running.
            output_failure = (
                f"result output was not written ({type(error).__name__}); "
                "omit --output or use a writable path under the current "
                "project's .tao root"
            )
            if success:
                policy, output_policy_details = hook_failure_policy(
                    False,
                    repair_cycle,
                    invocation_error=True,
                )
                details = [*details, output_failure, *output_policy_details]
            else:
                details = [*details, output_failure]
            print_status(name, False, details)
            return 1
    print_status(name, success, details)
    return 0 if success else 1


def hook_failure_policy(
    success: bool,
    repair_cycle: int,
    *,
    invocation_error: bool = False,
    pending_closeout: bool = False,
    refreshable_failure: bool = False,
    fresh_start_required: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    if success:
        next_action = "resume_failed_checkpoint" if repair_cycle else "continue"
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "next_action": next_action,
        }, []
    if fresh_start_required:
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "next_action": "fresh_start_and_rerun_review",
            "recovery_required": "fresh_lifecycle",
            "resume_scope": "review hook",
        }, [
            "fresh-start request: the bound run is already settled and must remain immutable. "
            "Carry the same bounded objective and approvals into a new start/preflight, then "
            "rerun review against the current worktree. This is lifecycle rollover, not a Tao "
            "Agent Runtime repair; do not run repair-verify",
        ]
    if invocation_error:
        # The call was rejected before the lifecycle started, so no checkpoint
        # failed and none can be repaired. Demanding a repair receipt here is a
        # deadlock: repair-verify can only build one from a recorded failure,
        # and this failure never reached the ledger. Fix the call and rerun.
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "next_action": "fix_invocation_and_rerun",
        }, [
            "invocation request: this call was rejected before any gate ran, so no checkpoint "
            "failed and there is nothing to repair. Do not run repair-verify; correct the "
            "reported argument and rerun the same hook",
        ]
    if pending_closeout:
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "next_action": "complete_skill_followup_then_retry_finish",
            "recovery_required": "bounded_skill_review_or_verified_maintenance",
            "resume_scope": "finish",
        }, [
            "closeout request: the current task recorded a reusable skill gap. Run the "
            "same-closeout skill-draft, skill-review, and verified skill-maintenance "
            "steps, then retry finish. This is expected closeout work, not a Tao Agent OS repair cycle; "
            "do not run repair-verify",
        ]
    if refreshable_failure:
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "next_action": "refresh_lifecycle_and_retry_finish",
            "recovery_required": "fresh_lifecycle",
            "resume_scope": "failed hook",
        }, [
            "refresh request: the worktree or rules changed after start or a successful review. "
            "Wait for concurrent writers to settle, reconcile the intended change, start a fresh "
            "lifecycle, and rerun the affected analysis or review before finish. This is stale "
            "workspace evidence, not a Tao Agent OS repair; do not run repair-verify",
        ]
    if repair_cycle < REPAIR_CYCLE_LIMIT:
        return {
            "repair_cycle": repair_cycle,
            "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
            "repair_policy": REPAIR_POLICY,
            "next_action": "retrospective_then_repair_verify_resume",
            "recovery_required": "verified_tao_improvement",
            "resume_scope": RESUME_SCOPE,
        }, [
            "recovery request: diagnose every failure, run an actionable retrospective for this "
            "failed scope, improve the owning Tao Agent OS doc, hook, validator, or test, and "
            "verify that repair outside the hook. Create a structural receipt with the "
            "repair-verify hook, then pass its path with --repair-cycle 1, --repair-target, "
            "--repair-evidence, and --resume-checkpoint before resuming the original task",
        ]
    return {
        "repair_cycle": repair_cycle,
        "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
        "next_action": "stop_after_repair_verification_failed",
        "recovery_required": "promote_or_handoff_lesson",
        "stop_condition": REPAIR_STOP_CONDITION,
    }, [
        "stop request: the same checkpoint failed after one repair cycle; promote the lesson "
        "or hand off the blocker and do not resume the original task",
    ]


def existing_path(value: str) -> Path:
    return Path(value).resolve()


def existing_directory(value: str) -> Path:
    path = existing_path(value)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"expected a directory: {value}")
    return path


def repair_cycle(value: str) -> int:
    cycle = int(value)
    if cycle < 0 or cycle > REPAIR_CYCLE_LIMIT:
        raise argparse.ArgumentTypeError(
            f"repair cycle must be 0 or {REPAIR_CYCLE_LIMIT}"
        )
    return cycle


def repair_context_failures(
    target: str,
    evidence: str,
    checkpoint: str,
    *,
    route: dict[str, Any] | None = None,
    evidence_path: Path | None = None,
    preflight: dict[str, Any] | None = None,
    project: Path | None = None,
    rules: Path | None = None,
) -> list[str]:
    failures: list[str] = []
    checkpoint_text = checkpoint.strip()
    if not target.strip():
        failures.append("--repair-target must name the changed repair file")
    if not evidence.strip():
        failures.append("--repair-evidence must name a structural repair receipt")
    if not checkpoint_text:
        failures.append("--resume-checkpoint must name the failed checkpoint to resume")
    if failures:
        return failures
    if evidence_path is None or preflight is None or project is None or rules is None:
        return [
            "repair verification requires current project, rules, preflight, and failure ledger state"
        ]
    try:
        checkpoint_failed = checkpoint_has_recorded_failure(
            route=route or preflight.get("route") or {},
            evidence_path=evidence_path,
            checkpoint=checkpoint_text,
        )
    except OSError:
        checkpoint_failed = False
    if not checkpoint_failed:
        failures.append(
            f"--resume-checkpoint {checkpoint_text!r} has no recorded finish-check failure "
            "for the current preflight/route; repair only the checkpoint that actually failed"
        )
        return failures
    failures.extend(
        validate_repair_receipt(
            project=project,
            rules=rules,
            evidence_path=evidence_path,
            preflight=preflight,
            target=target,
            checkpoint=checkpoint_text,
            receipt_path=Path(evidence).expanduser(),
        )
    )
    if failures:
        return failures
    try:
        failure_signature = checkpoint_failure_signature(
            route=route or preflight.get("route") or {},
            evidence_path=evidence_path,
            checkpoint=checkpoint_text,
        )
    except OSError:
        failure_signature = ""
    try:
        allowed, _count = register_repair_attempt(
            evidence_path=evidence_path,
            preflight=preflight,
            checkpoint=checkpoint_text,
            limit=REPAIR_CYCLE_LIMIT,
            failure_signature=failure_signature,
        )
    except PermissionError as error:
        failures.append(str(error))
        return failures
    if not allowed:
        failures.append(
            f"repair cycle limit ({REPAIR_CYCLE_LIMIT}) already used for checkpoint "
            f"{checkpoint_text!r}; promote the lesson or hand off instead of repairing again"
        )
    return failures


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed
