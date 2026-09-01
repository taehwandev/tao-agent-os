"""Review-hook execution for Tao Agent OS."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_finish_gate_policy import validate_gate_evidence
from agent_gate_evidence import (
    incomplete_gate_evidence_failures,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
)
from agent_finish_final_checks import record_successful_review_workflow_validation
from agent_inprocess import run_workflow_validate
from agent_review_boundary import format_boundary_note_requirements, missing_boundary_note_fields
from agent_review_attestation import ReviewAttestation
from agent_review_commit_range import create_commit_snapshot, resolve_commit_range_subject
from agent_review_structure import REVIEW_ADDED_LINE_LIMIT, structure_review
from agent_repair_ledger import failure_signature, record_failure_checkpoints
from agent_review_subjects import (  # noqa: F401
    REPO_HYGIENE_CONCERNS,
    SETTLED_RUN_STATES,
    clean_read_only_pathspec_review,
    clean_repo_hygiene_review,
    clean_restored_pathspec_review,
    clean_task_setup_pathspec_review,
    empty_review_scope_invocation_failure_details,
    explicit_existing_review_paths,
    invalid_review_subject_details,
    settled_review_run_invocation_failure_details,
    settled_review_run_state,
    unavailable_structure_review,
)
from agent_vibeguard_cache import cached_vibeguard
from agent_workspace_policy import is_git_status_review_only, is_writing_workspace, non_git_writing_workspace_note
from support.stage_timing import stage


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
FinishWithResult = Callable[..., int]


BASE_DRIFT_CANDIDATE_REFS = ("origin/develop", "origin/main", "origin/master")

# Which review evidence the hook will demand, stated once so `start` can
# advertise it up front. The requirement was only discoverable by failing the
# review hook, which made the same `review_hook` missed-gate lesson recur; the
# route already determines the answer, so the answer belongs in the route
# summary. `record_review_input_evidence` enforces these and
# `test_review_evidence_advertisement.py` pins the two together.
ALWAYS_REQUIRED_REVIEW_EVIDENCE = (
    "--code-review-evidence",
    "--docs-freshness-evidence",
)
GATE_REQUIRED_REVIEW_EVIDENCE = {
    "boundary plan": "--boundary-plan-evidence",
    "side-effect audit": "--side-effect-audit-evidence",
}


def required_review_evidence_flags(route_gates: list[str]) -> list[str]:
    """Return every review-hook evidence flag this route makes mandatory."""

    gates = set(route_gates)
    flags = list(ALWAYS_REQUIRED_REVIEW_EVIDENCE)
    flags.extend(
        flag for gate, flag in GATE_REQUIRED_REVIEW_EVIDENCE.items() if gate in gates
    )
    return flags


def review_hook(
    args: Any,
    run_command: CommandRunner,
    git_status: Callable[[Path], tuple[dict[str, Any], list[str]]],
    vibeguard_command: Callable[[Path, Path], list[str]],
    parse_overall: Callable[[str], str],
    finish_with_result: FinishWithResult,
    on_invocation_error: Callable[[], None] | None = None,
) -> int:
    checks: dict[str, Any] = {}
    prerequisite_failures: list[str] = []
    record_review_prerequisite_readiness(args, checks, prerequisite_failures)
    if prerequisite_failures:
        if on_invocation_error is not None:
            on_invocation_error()
        return finish_with_result(
            "review",
            False,
            review_prerequisite_failure_details(prerequisite_failures),
            args.output,
            checks,
            args.repair_cycle,
            invocation_error=True,
        )

    settled_state = settled_review_run_state(args)
    if settled_state:
        checks["review_lifecycle"] = {
            "state": settled_state,
            "next_action": "fresh_start",
        }
        if on_invocation_error is not None:
            on_invocation_error()
        return finish_with_result(
            "review",
            False,
            settled_review_run_invocation_failure_details(settled_state),
            args.output,
            checks,
            args.repair_cycle,
            fresh_start_required=True,
        )

    requested_review_paths = review_pathspec(args)
    try:
        review_subject = resolve_review_subject(
            args,
            run_command,
            requested_review_paths,
        )
    except ValueError as error:
        if on_invocation_error is not None:
            on_invocation_error()
        return finish_with_result(
            "review",
            False,
            invalid_review_subject_details(str(error)),
            args.output,
            checks,
            args.repair_cycle,
            invocation_error=True,
        )

    review_paths = (
        list(review_subject["changed_paths"])
        if review_subject["kind"] == "commit-range"
        else requested_review_paths
    )
    review_scope = review_scope_label(args, review_paths, review_subject)
    checks["review_scope"] = review_scope
    checks["review_paths"] = review_paths
    checks["review_subject"] = review_subject_record(review_subject)
    with stage("git_status"):
        full_status_before, full_status_before_lines = git_status(args.project)
    if is_git_status_review_only(args.project, full_status_before):
        full_status_before["review_only"] = True
        full_status_before["review_note"] = non_git_writing_workspace_note(args.project)
        full_status_before_lines = []
    checks["full_git_status_before"] = full_status_before
    if review_subject["kind"] == "commit-range":
        status_before = review_subject["path_discovery"]
        status_before_lines = list(review_subject["changed_paths"])
    else:
        status_before, status_before_lines = git_status_for_review(
            args.project,
            run_command,
            git_status,
            review_paths,
        )
    if is_git_status_review_only(args.project, status_before):
        status_before["review_only"] = True
        status_before["review_note"] = non_git_writing_workspace_note(args.project)
        status_before_lines = []
    checks["git_status_before"] = status_before
    local_config_scope = review_subject["kind"] == "local-config"
    checks["changed_path_count"] = (
        len(review_paths) if local_config_scope else len(status_before_lines)
    )
    checks["changed_path_limit"] = args.max_changed_paths
    clean_read_only_scope = clean_read_only_pathspec_review(args, review_subject, review_paths)
    clean_restored_scope = clean_restored_pathspec_review(args, review_subject, review_paths)
    clean_task_setup_scope = clean_task_setup_pathspec_review(args, review_subject, review_paths)
    clean_repo_hygiene_scope = clean_repo_hygiene_review(args, review_subject, review_paths)
    if status_before["returncode"] != 0 and not status_before.get("review_only"):
        failures = ["git status failed"]
    elif full_status_before["returncode"] != 0 and not full_status_before.get("review_only"):
        failures = ["git status failed"]
    elif (
        not status_before_lines
        and not status_before.get("review_only")
        and not clean_read_only_scope
        and not clean_restored_scope
        and not clean_task_setup_scope
        and not clean_repo_hygiene_scope
        and not local_config_scope
    ):
        scope_failure = (
            "review scope has no changed paths; the working-tree review hook cannot "
            "attest a clean checkout or a committed diff"
        )
        checks["review_scope_failure"] = scope_failure
        if on_invocation_error is not None:
            on_invocation_error()
        return finish_with_result(
            "review",
            False,
            empty_review_scope_invocation_failure_details(scope_failure, review_scope),
            args.output,
            checks,
            args.repair_cycle,
            invocation_error=True,
        )
    elif not status_before_lines and not status_before.get("review_only"):
        clean_scope_key = "local_config_scope" if local_config_scope else (
            "repo_hygiene_clean_scope" if clean_repo_hygiene_scope else (
                "clean_restoration_scope" if clean_restored_scope else (
                    "task_setup_clean_scope" if clean_task_setup_scope else "read_only_clean_scope"
                )
            )
        )
        checks[clean_scope_key] = {
            "accepted": True,
            "reason": (
                "explicit Git-ignored local agent configuration is bound by current file hashes"
                if local_config_scope
                else (
                    "destructive branch/worktree cleanup was reviewed from a clean checkout"
                    if clean_repo_hygiene_scope
                    else (
                        "explicit preflight-dirty paths were restored to committed bytes"
                        if clean_restored_scope
                        else (
                            "task setup inspected its explicit workflow policy on a clean protected checkout"
                            if clean_task_setup_scope
                            else "read-only run inspected explicit existing pathspecs on a clean checkout"
                        )
                    )
                )
            ),
        }
        failures = []
    elif len(status_before_lines) > args.max_changed_paths:
        scope_failure = (
            f"review scope has {len(status_before_lines)} changed paths; "
            f"limit is {args.max_changed_paths}; split the change or run a smaller review scope"
        )
        checks["review_scope_failure"] = scope_failure
        if on_invocation_error is not None:
            on_invocation_error()
        return finish_with_result(
            "review",
            False,
            review_scope_invocation_failure_details(
                scope_failure,
                review_scope,
                len(status_before_lines),
            ),
            args.output,
            checks,
            args.repair_cycle,
            invocation_error=True,
        )
    else:
        failures = []

    record_review_input_evidence(args, checks, failures)

    snapshot: Any | None = None
    source_project = args.project
    try:
        if review_subject["kind"] == "commit-range":
            snapshot, source_project, snapshot_check = create_commit_snapshot(
                args.project,
                review_subject["head_sha"],
                run_command,
            )
            checks["commit_snapshot"] = snapshot_check
        structure = structure_review(
            args.project,
            args.max_source_file_lines,
            args.max_function_lines,
            run_command,
            None if review_subject["kind"] == "commit-range" else review_paths,
            max_added_lines=getattr(args, "max_added_lines", REVIEW_ADDED_LINE_LIMIT),
            source_project=source_project,
            review_commits=(review_subject["base_sha"], review_subject["head_sha"])
            if review_subject["kind"] == "commit-range"
            else None,
        )
    except (OSError, RuntimeError, ValueError) as error:
        failures.append(f"commit snapshot materialization failed: {error}")
        structure = unavailable_structure_review(str(error))
    checks["structure_review"] = structure
    failures.extend(f"structure review: {failure}" for failure in structure["failures"])
    failures.extend(
        structure_evidence_failures(structure, (args.structure_review_evidence or "").strip())
    )
    failures.extend(
        net_deletion_failures(structure, (args.side_effect_audit_evidence or "").strip())
    )

    if local_config_scope:
        diff_check = local_config_diff_check(args.project, review_paths)
    elif status_before.get("review_only"):
        diff_check = {
            "command": ["git", "diff", "--check"],
            "cwd": str(args.project),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped": True,
            "review_note": non_git_writing_workspace_note(args.project),
        }
    else:
        diff_check = run_command(diff_check_command(review_paths, review_subject), args.project)
    checks["diff_check"] = diff_check
    if diff_check["returncode"] != 0:
        failures.append("git diff --check failed")

    record_review_base_drift(
        args,
        run_command,
        structure,
        checks,
        failures,
        review_subject=review_subject,
    )
    record_review_workflow_validation(args, checks, failures)
    record_review_vibeguard(
        args,
        run_command,
        vibeguard_command,
        parse_overall,
        [] if review_subject["kind"] in {"commit-range", "local-config"} else review_paths,
        checks,
        failures,
        audit_project=source_project,
    )
    if snapshot is not None:
        snapshot.cleanup()
    record_review_worktree_stability(
        args,
        run_command,
        git_status,
        review_paths,
        status_before_lines,
        full_status_before_lines,
        checks,
        failures,
        review_subject=review_subject,
    )

    # A correctable invocation (a stale base, a missing evidence field) is not a
    # review finding: recording it as one would leave a failure in the ledger
    # that the agent cannot clear by fixing the diff.
    invocation_failure = review_input_invocation_failure(failures)
    if invocation_failure and on_invocation_error is not None:
        on_invocation_error()
    if not failures:
        evidence_path = (
            args.evidence
            if args.evidence
            else args.project / ".tao" / "preflight.json"
        )
        try:
            record_successful_review_workflow_validation(
                args.project,
                args.rules,
                evidence_path,
                checks["workflow_validate"],
                checks["diff_check"],
                review_scope,
            )
            record_review_gate(args, checks)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            failures.append(f"review attestation failed: {error}")
            record_review_failure(args, failures)
    elif not invocation_failure:
        record_review_failure(args, failures)

    details = (
        review_input_invocation_failure_details(failures, structure, review_scope)
        if invocation_failure
        else review_failure_details(failures, structure, review_scope)
        if failures
        else review_success_details(
            structure,
            review_scope,
            str((checks.get("vibeguard") or {}).get("overall") or ""),
            str(getattr(args, "allow_vibeguard_review", "") or "").strip(),
        )
    )
    return finish_with_result(
        "review",
        not failures,
        details,
        args.output,
        checks,
        args.repair_cycle,
        invocation_error=invocation_failure,
    )


def record_review_input_evidence(
    args: Any,
    checks: dict[str, Any],
    failures: list[str],
) -> None:
    review_outcome = str(getattr(args, "review_outcome", "") or "").strip()
    review_evidence = (args.code_review_evidence or "").strip()
    docs_evidence = (args.docs_freshness_evidence or "").strip()
    structure_evidence = (args.structure_review_evidence or "").strip()
    boundary_evidence = (args.boundary_plan_evidence or "").strip()
    side_effect_evidence = (args.side_effect_audit_evidence or "").strip()
    route_gates = review_route_gates(args.project, args.evidence)
    checks.update(
        review_outcome=review_outcome,
        code_review_evidence=review_evidence,
        docs_freshness_evidence=docs_evidence,
        structure_review_evidence=structure_evidence,
        boundary_plan_evidence=boundary_evidence,
        side_effect_audit_evidence=side_effect_evidence,
        route_gates=route_gates,
    )
    failures.extend(review_outcome_failures(review_outcome))
    if not review_evidence:
        failures.append("code review evidence is required")
    if not docs_evidence:
        failures.append("docs freshness evidence is required")
    if "boundary plan" in route_gates and not boundary_evidence:
        failures.append("boundary plan evidence is required for this route")
    if "side-effect audit" in route_gates and not side_effect_evidence:
        failures.append("side-effect audit evidence is required for this route")


def record_review_prerequisite_readiness(
    args: Any,
    checks: dict[str, Any],
    failures: list[str],
) -> None:
    evidence_path = args.evidence if args.evidence else args.project / ".tao" / "preflight.json"
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        failures.append("review preflight evidence is missing or invalid")
        return

    expected_rules = str(preflight.get("rules") or "").strip()
    if expected_rules and Path(expected_rules).expanduser().resolve() != args.rules.resolve():
        checks["review_rules_root"] = {
            "expected": expected_rules,
            "actual": str(args.rules),
        }
        failures.append(
            "review --rules must match the rules root recorded by start; "
            "rerun review with the preflight rules root"
        )
        return

    route = preflight.get("route") or {}
    route_gates = [gate for gate in route.get("gates") or [] if isinstance(gate, str)]
    if "review hook" not in route_gates:
        checks["review_prerequisite_gates"] = []
        return

    prerequisite_gates = route_gates[:route_gates.index("review hook")]
    gate_evidence, diagnostics = merge_gate_evidence_from_ledger(
        route=route,
        evidence_path=evidence_path,
    )
    missing_gates = [gate for gate in prerequisite_gates if not gate_evidence.get(gate)]
    checks["review_prerequisite_gates"] = prerequisite_gates
    checks["review_prerequisite_missing"] = missing_gates
    checks["review_prerequisite_ledger"] = diagnostics

    if missing_gates:
        failures.append(
            "review prerequisites are incomplete before review hook: " + ", ".join(missing_gates)
        )
    failures.extend(
        f"review prerequisites: {failure}"
        for failure in incomplete_gate_evidence_failures(
            _gate_diagnostics_for(diagnostics, prerequisite_gates)
        )
    )
    if not missing_gates:
        failures.extend(
            f"review prerequisites: {failure}"
            for failure in validate_gate_evidence(
                gate_evidence,
                prerequisite_gates,
                route=route,
            )
        )


def _gate_diagnostics_for(
    diagnostics: dict[str, Any],
    gates: list[str],
) -> dict[str, Any]:
    """Restrict ledger diagnostics to the gates that precede review."""

    allowed = set(gates)
    scoped = dict(diagnostics)
    for field in ("invalid_statuses", "failed_gates", "missing_fields"):
        values = diagnostics.get(field)
        if isinstance(values, dict):
            scoped[field] = {
                gate: value
                for gate, value in values.items()
                if gate in allowed
            }
    return scoped


def record_review_workflow_validation(
    args: Any,
    checks: dict[str, Any],
    failures: list[str],
) -> None:
    validate_script = args.rules / "scripts" / "workflow.py"
    if not validate_script.exists():
        failures.append(f"workflow validate script missing at {validate_script}")
        return
    with stage("workflow_validate"):
        validate = run_workflow_validate(args.rules)
    checks["workflow_validate"] = validate
    if validate["returncode"] != 0:
        failures.append(workflow_validate_failure_detail(validate))


def record_review_vibeguard(
    args: Any,
    run_command: CommandRunner,
    vibeguard_command: Callable[[Path, Path], list[str]],
    parse_overall: Callable[[str], str],
    review_paths: list[str],
    checks: dict[str, Any],
    failures: list[str],
    audit_project: Path | None = None,
) -> None:
    selected_project = audit_project or args.project
    scoped_command = review_vibeguard_command(
        selected_project,
        args.rules,
        run_command,
        vibeguard_command,
        review_paths,
    )
    checks["vibeguard_pathspec"] = {
        "paths": review_paths,
        "path_option_supported": bool(getattr(scoped_command, "path_option_supported", False)),
    }
    with stage("vibeguard"):
        vibeguard = cached_vibeguard(
            project=selected_project,
            rules=args.rules,
            run_command=run_command,
            vibeguard_command=scoped_command,
            parse_overall=parse_overall,
        )
    checks["vibeguard"] = vibeguard
    if vibeguard["returncode"] != 0:
        failures.append("VibeGuard audit failed")
        return
    failure = vibeguard_review_failure(
        str(vibeguard["overall"]),
        selected_project,
        str(getattr(args, "allow_vibeguard_review", "") or ""),
    )
    if failure:
        failures.append(failure)


def vibeguard_review_failure(overall: str, project: Path, allow_reason: str) -> str:
    if overall == "Ready" or is_writing_workspace(project) or allow_reason.strip():
        return ""
    return f"VibeGuard overall is {overall}"


def record_review_worktree_stability(
    args: Any,
    run_command: CommandRunner,
    git_status: Callable[[Path], tuple[dict[str, Any], list[str]]],
    review_paths: list[str],
    status_before_lines: list[str],
    full_status_before_lines: list[str],
    checks: dict[str, Any],
    failures: list[str],
    review_subject: dict[str, Any] | None = None,
) -> None:
    if (review_subject or {}).get("kind") == "local-config":
        try:
            current = ReviewAttestation.local_config_subject(args.project, review_paths)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            failures.append(f"reviewed local config is no longer verifiable: {error}")
            current = {}
        checks["local_config_after"] = current
        full_status_after, full_status_after_lines = git_status(args.project)
        checks["git_status_after"] = full_status_after
        checks["full_git_status_after"] = full_status_after
        if full_status_after["returncode"] != 0:
            failures.append("git status failed")
        elif current != review_subject:
            failures.append("reviewed local config changed while the review hook was running")
        elif full_status_after_lines != full_status_before_lines:
            failures.append(
                "review hook changed files outside the local config scope; review hooks must stay read-only"
            )
        return

    if (review_subject or {}).get("kind") == "commit-range":
        current = resolve_commit_range_subject(
            args.project,
            str(review_subject["base_sha"]),
            str(review_subject["head_sha"]),
            run_command,
        )
        checks["commit_range_after"] = current["path_discovery"]
        checks["git_status_after"] = current["path_discovery"]
        full_status_after, full_status_after_lines = git_status(args.project)
        checks["full_git_status_after"] = full_status_after
        if full_status_after["returncode"] != 0:
            failures.append("git status failed")
        elif current["changed_paths"] != status_before_lines:
            failures.append("reviewed commit range changed while the review hook was running")
        elif full_status_after_lines != full_status_before_lines:
            failures.append("review hook changed the worktree; review hooks must stay read-only")
        return

    status_after, status_after_lines = git_status_for_review(
        args.project,
        run_command,
        git_status,
        review_paths,
    )
    full_status_after, full_status_after_lines = git_status(args.project)
    if is_git_status_review_only(args.project, full_status_after):
        full_status_after["review_only"] = True
        full_status_after["review_note"] = non_git_writing_workspace_note(args.project)
        full_status_after_lines = []
    if is_git_status_review_only(args.project, status_after):
        status_after["review_only"] = True
        status_after["review_note"] = non_git_writing_workspace_note(args.project)
        status_after_lines = []
    checks["git_status_after"] = status_after
    checks["full_git_status_after"] = full_status_after
    if status_after["returncode"] != 0 and not status_after.get("review_only"):
        failures.append("git status failed")
    elif full_status_after["returncode"] != 0 and not full_status_after.get("review_only"):
        failures.append("git status failed")
    elif status_after_lines != status_before_lines:
        failures.append("review hook changed the worktree; review hooks must stay read-only")
    elif full_status_after_lines != full_status_before_lines:
        failures.append("review hook changed files outside the review pathspec; review hooks must stay read-only")


def record_review_failure(args: Any, failures: list[str]) -> None:
    evidence_path = args.evidence if args.evidence else args.project / ".tao" / "preflight.json"
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        signature = failure_signature(failures)
        record_gate_evidence(
            evidence_path=evidence_path,
            preflight=preflight,
            gate="review hook",
            evidence="review hook failed; repair is required before review evidence can be reused",
            fields={"failure_signature": signature},
            status="FAIL",
            source="review",
        )
        record_failure_checkpoints(
            evidence_path=evidence_path,
            preflight=preflight,
            checkpoints=["review"],
            signature=signature,
            checkpoint_signatures={"review": signature},
        )
    except (OSError, ValueError):
        return


def workflow_validate_failure_detail(validate: dict[str, Any]) -> str:
    output = str(validate.get("stderr") or validate.get("stdout") or "").strip()
    if not output:
        return "workflow validate failed without diagnostic output"
    compact = "; ".join(line.strip() for line in output.splitlines() if line.strip())
    return f"workflow validate failed: {compact[:800]}"


def record_review_gate(args: Any, checks: dict[str, Any]) -> None:
    evidence_path = args.evidence if args.evidence else args.project / ".tao" / "preflight.json"
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            "review attestation requires readable preflight evidence"
        ) from error
    attestation = ReviewAttestation.record(
        project=args.project,
        rules=args.rules,
        evidence_path=evidence_path,
        preflight=preflight,
        review_scope=str(checks.get("review_scope") or ""),
        review_paths=[str(path) for path in (checks.get("review_paths") or [])],
        changed_path_count=int(checks.get("changed_path_count") or 0),
        checks=checks,
        review_subject=dict(checks.get("review_subject") or {}),
    )
    record_gate_evidence(
        evidence_path=evidence_path,
        preflight=preflight,
        gate="review hook",
        evidence="review hook completed successfully and left worktree unchanged",
        fields={
            **ReviewAttestation.ledger_fields(attestation),
            "workflow_validate": str((checks.get("workflow_validate") or {}).get("returncode", "")),
            "vibeguard": str((checks.get("vibeguard") or {}).get("overall", "")),
        },
        status="SUCCESS",
        source="review",
    )


def structure_evidence_failures(structure: dict[str, Any], structure_evidence: str) -> list[str]:
    failures: list[str] = []
    if structure["warnings"] and not structure_evidence:
        warning_summary = "; ".join(structure["warnings"][:5])
        if len(structure["warnings"]) > 5:
            warning_summary += "; ..."
        failures.append(f"structure review evidence is required: {warning_summary}")
    failures.extend(raised_addition_limit_failures(structure, structure_evidence))
    boundary_requirements = structure.get("boundary_note_requirements", [])
    missing_fields = missing_boundary_note_fields(structure_evidence) if boundary_requirements else []
    if missing_fields:
        failures.append(
            "structure boundary note evidence is required for "
            f"{format_boundary_note_requirements(boundary_requirements)}; "
            "this applies when an added runtime file enters an existing multi-role package, "
            "not only when the diff creates a new package boundary; "
            "structure-review-evidence must explicitly include owner, allowed imports, "
            f"forbidden imports, callers/tests, and verification. Missing: {', '.join(missing_fields)}. "
            "Example: owner=domain; allowed imports=contracts; forbidden imports=ui; "
            "callers/tests=app and domain tests; verification=focused tests"
        )
    return failures


def resolve_base_ref(project: Path, run_command: CommandRunner) -> str:
    """Resolve the ref this branch is supposed to be current with.

    An upstream that is the branch's own remote mirror answers "am I behind my
    own push", which is not the staleness this check is about. Measured on real
    work branches, that mirror reported 0 commits behind while the same branch
    was 26 commits behind the integration base and shared 7 changed paths with
    it -- the exact condition a stale read needs. So a self-tracking upstream is
    skipped and the conventional integration refs are used instead.
    """

    head = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], project)
    branch = head["stdout"].strip() if head["returncode"] == 0 else ""
    upstream = run_command(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        project,
    )
    tracked = upstream["stdout"].strip() if upstream["returncode"] == 0 else ""
    if tracked and branch and tracked != branch and not tracked.endswith(f"/{branch}"):
        return tracked
    for candidate in BASE_DRIFT_CANDIDATE_REFS:
        verified = run_command(["git", "rev-parse", "--verify", "--quiet", candidate], project)
        if verified["returncode"] == 0 and verified["stdout"].strip():
            return candidate
    return ""


def record_review_base_drift(
    args: Any,
    run_command: CommandRunner,
    structure: dict[str, Any],
    checks: dict[str, Any],
    failures: list[str],
    review_subject: dict[str, Any] | None = None,
) -> None:
    """Fail review when the change rewrites paths that already moved on the base.

    Working from a checkout that trails its base is how an agent reads a file at
    one revision and writes it at another: the content it reasoned about is not
    the content it overwrites. Git cannot see which revision was read, but it can
    see that the base already changed the same path since the merge base, which
    is the condition that makes a stale read possible.
    """

    drift: dict[str, Any] = {"base_ref": "", "behind": 0, "drifted_paths": []}
    checks["base_drift"] = drift
    if (review_subject or {}).get("kind") == "commit-range":
        drift["skipped"] = "immutable commit-range subject"
        return
    if (review_subject or {}).get("kind") == "local-config":
        drift["skipped"] = "Git-ignored local configuration has no integration-base diff"
        return
    base_ref = resolve_base_ref(args.project, run_command)
    if not base_ref:
        drift["skipped"] = "no upstream or conventional base ref is available"
        return
    drift["base_ref"] = base_ref
    merge_head = run_command(
        ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"], args.project
    )
    merge_head_sha = merge_head["stdout"].strip() if merge_head["returncode"] == 0 else ""
    if merge_head_sha:
        unresolved = run_command(
            ["git", "diff", "--name-only", "--diff-filter=U"], args.project
        )
        unresolved_paths = [
            line.strip() for line in unresolved["stdout"].splitlines() if line.strip()
        ] if unresolved["returncode"] == 0 else []
        base_is_merged = run_command(
            ["git", "merge-base", "--is-ancestor", base_ref, "MERGE_HEAD"], args.project
        )
        drift["merge_head"] = merge_head_sha
        drift["unresolved_merge_paths"] = unresolved_paths
        if base_is_merged["returncode"] == 0 and not unresolved_paths:
            drift["skipped"] = (
                "resolved in-progress merge already incorporates the current base ref"
            )
            return
    merge_base = run_command(["git", "merge-base", "HEAD", base_ref], args.project)
    if merge_base["returncode"] != 0:
        drift["skipped"] = "merge base with the base ref is unavailable"
        return
    base_point = merge_base["stdout"].strip()
    behind = run_command(
        ["git", "rev-list", "--count", f"HEAD..{base_ref}"], args.project
    )
    drift["behind"] = (
        int(behind["stdout"].strip() or 0) if behind["returncode"] == 0 and behind["stdout"].strip().isdigit() else 0
    )
    if drift["behind"] < 1:
        return
    moved = run_command(
        ["git", "diff", "--name-only", "-z", base_point, base_ref], args.project
    )
    if moved["returncode"] != 0:
        drift["skipped"] = "base-side change discovery failed"
        return
    moved_paths = {field for field in moved["stdout"].split("\0") if field} or {
        line.strip() for line in moved["stdout"].splitlines() if line.strip()
    }
    changed_paths = set(structure.get("discovery", {}).get("path_metadata") or {})
    drifted = sorted(moved_paths.intersection(changed_paths))
    drift["drifted_paths"] = drifted
    if not drifted:
        return
    listed = "; ".join(drifted[:5]) + ("" if len(drifted) <= 5 else f"; ... (+{len(drifted) - 5} more)")
    failures.append(
        f"this checkout is {drift['behind']} commits behind {base_ref} and the change "
        f"rewrites paths that already moved on {base_ref}: {listed}. Stop before review. "
        "Integrate the current base according to repository policy and user authority, "
        "resolve the overlapping paths, rerun the affected verification, and invoke "
        "review again from a checkout that is no longer behind that base. "
        "Boundary-plan evidence cannot waive this stale-base overlap."
    )


def review_input_invocation_failure(failures: list[str]) -> bool:
    invocation_failure_prefixes = (
        "structure review evidence is required: ",
        "structure boundary note evidence is required for ",
        "per-file addition limit was raised to ",
        "net deletion of ",
    )
    return bool(failures) and all(
        failure.startswith(invocation_failure_prefixes)
        or is_stale_base_invocation_failure(failure)
        or is_vibeguard_allow_reason_invocation_failure(failure)
        for failure in failures
    )


def is_stale_base_invocation_failure(failure: str) -> bool:
    return (
        failure.startswith("this checkout is ")
        and " commits behind " in failure
        and "rewrites paths that already moved on " in failure
        and "Stop before review." in failure
    )


def is_vibeguard_allow_reason_invocation_failure(failure: str) -> bool:
    return failure == "VibeGuard overall is Needs review"


def review_input_invocation_failure_details(
    failures: list[str],
    structure: dict[str, Any],
    review_scope: str,
) -> list[str]:
    details = [
        f"review scope: {review_scope}",
        f"structure scope: {structure['scope']}",
        f"checked development source/style files: {format_checked_paths(structure.get('checked_paths', []))}",
    ]
    details.extend(f"invocation detail: {failure}" for failure in failures)
    if any(is_stale_base_invocation_failure(failure) for failure in failures):
        details.append(
            "invocation request: integrate the current base according to repository policy and "
            "user authority, resolve overlapping paths, rerun affected verification, and rerun "
            "the same review hook; no lifecycle checkpoint failed"
        )
    if any(
        failure.startswith(
            (
                "structure review evidence is required: ",
                "structure boundary note evidence is required for ",
                "per-file addition limit was raised to ",
            )
        )
        for failure in failures
    ):
        details.append(
            "invocation request: correct --structure-review-evidence with every required boundary "
            "field and rerun the same review hook; no lifecycle checkpoint failed"
        )
    if any(failure.startswith("net deletion of ") for failure in failures):
        details.append(
            "invocation request: correct --side-effect-audit-evidence by naming every reported "
            "path, removed content, and reason, then rerun the same review hook; no lifecycle "
            "checkpoint failed"
        )
    if any(is_vibeguard_allow_reason_invocation_failure(failure) for failure in failures):
        details.append(
            "invocation request: when the reported VibeGuard Needs review advisory is acceptable, "
            "rerun the same review hook with --allow-vibeguard-review and a concrete reason; "
            "otherwise resolve the finding first; no lifecycle checkpoint failed"
        )
    return details

def net_deletion_failures(structure: dict[str, Any], side_effect_evidence: str) -> list[str]:
    """Require the side-effect audit to name every large net removal in the diff.

    A removal is the one diff outcome no other check in this hook can see:
    ``git diff --check`` reads whitespace, workflow validation reads the files
    that remain, VibeGuard reads what the change added, and structural review
    reads development sources only. The measured counts are put in the failure
    text so the agent learns what disappeared instead of being asked to assert
    that nothing did.
    """

    findings = structure.get("net_deletions") or []
    if not findings:
        return []
    normalized = side_effect_evidence.replace("\\", "/")
    unnamed = [item for item in findings if str(item["path"]) not in normalized]
    if not unnamed:
        return []
    measured = "; ".join(
        f"{item['path']} (-{item['deletions']} +{item['additions']}, net -{item['net']})"
        for item in unnamed[:5]
    )
    if len(unnamed) > 5:
        measured += f"; ... (+{len(unnamed) - 5} more)"
    limit = structure.get("net_deletion_limit")
    return [
        f"net deletion of {limit}+ lines is unaccounted for: {measured}. "
        "side-effect-audit-evidence must name each path above and state what the "
        "removed content was and why it is no longer needed. If the removal was "
        "not intended, re-read each file at the revision being overwritten before "
        "rerunning review"
    ]


def raised_addition_limit_failures(
    structure: dict[str, Any], structure_evidence: str
) -> list[str]:
    """Keep a raised per-file addition limit an explicitly reviewed decision.

    Raising the limit is legitimate for a file that cannot be split, such as one
    distributed as a single standalone artifact. It stops being legitimate the
    moment it is raised silently, so the reviewer has to say why in the
    structure review evidence.
    """

    limit = structure.get("max_added_lines")
    if not isinstance(limit, int) or limit <= REVIEW_ADDED_LINE_LIMIT:
        return []
    text = structure_evidence.lower()
    if not any(
        phrase in text
        for phrase in (
            "addition limit",
            "added line",
            "added-line",
            "single file",
            "single-file",
            "standalone",
            "cannot be split",
            "추가 줄",
            "단일 파일",
            "분할 불가",
        )
    ):
        return [
            f"per-file addition limit was raised to {limit} from {REVIEW_ADDED_LINE_LIMIT}; "
            "structure-review-evidence must name the file that cannot be split and why, "
            "for example a source file distributed and installed as a single standalone artifact"
        ]
    return []


def review_outcome_failures(outcome: str) -> list[str]:
    """Require a structural review decision instead of interpreting prose."""

    normalized = outcome.strip().lower()
    if normalized == "pass":
        return []
    if normalized == "findings":
        return ["review outcome reports unresolved findings"]
    return ["review outcome is required and must be pass or findings"]


def review_route_gates(project: Path, evidence_path: Path | None) -> list[str]:
    path = evidence_path if evidence_path else project / ".tao" / "preflight.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    gates = (payload.get("route") or {}).get("gates") or []
    return [gate for gate in gates if isinstance(gate, str)]


def review_pathspec(args: Any) -> list[str]:
    return [path.strip() for path in getattr(args, "review_path", []) if path.strip()]


def resolve_review_subject(
    args: Any,
    run_command: CommandRunner,
    review_paths: list[str] | None = None,
) -> dict[str, Any]:
    scope = getattr(args, "review_scope", "working-tree")
    if scope == "local-config":
        return ReviewAttestation.local_config_subject(
            args.project,
            list(review_paths or review_pathspec(args)),
        )
    if scope != "commit-range":
        return {"kind": "working-tree"}
    return resolve_commit_range_subject(
        args.project,
        str(getattr(args, "review_base", "") or ""),
        str(getattr(args, "review_head", "") or ""),
        run_command,
    )


def review_subject_record(subject: dict[str, Any]) -> dict[str, Any]:
    if subject.get("kind") == "local-config":
        return {
            "kind": "local-config",
            "files": [dict(record) for record in subject.get("files") or []],
        }
    if subject.get("kind") != "commit-range":
        return {"kind": "working-tree"}
    return {
        "kind": "commit-range",
        "base_sha": str(subject["base_sha"]),
        "head_sha": str(subject["head_sha"]),
    }


def review_scope_label(
    args: Any,
    review_paths: list[str],
    review_subject: dict[str, Any] | None = None,
) -> str:
    if (review_subject or {}).get("kind") == "commit-range":
        return (
            f"commit-range: {review_subject['base_sha']}..{review_subject['head_sha']}"
        )
    if (review_subject or {}).get("kind") == "local-config":
        return "local-config: " + ", ".join(review_paths)
    if review_paths:
        return "pathspec: " + ", ".join(review_paths)
    return getattr(args, "review_scope", "working-tree")


def git_status_for_review(
    project: Path,
    run_command: CommandRunner,
    git_status: Callable[[Path], tuple[dict[str, Any], list[str]]],
    review_paths: list[str],
) -> tuple[dict[str, Any], list[str]]:
    if not review_paths:
        return git_status(project)
    result = run_command(
        ["git", "status", "--short", "--untracked-files=all", "--", *review_paths],
        project,
    )
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return result, lines


def diff_check_command(
    review_paths: list[str],
    review_subject: dict[str, Any] | None = None,
) -> list[str]:
    if (review_subject or {}).get("kind") == "commit-range":
        return [
            "git",
            "diff",
            "--check",
            str(review_subject["base_sha"]),
            str(review_subject["head_sha"]),
            "--",
        ]
    if not review_paths:
        return ["git", "diff", "--check"]
    return ["git", "diff", "--check", "--", *review_paths]


def local_config_diff_check(project: Path, review_paths: list[str]) -> dict[str, Any]:
    """Represent byte-snapshot validation without claiming an ignored Git diff exists."""

    return {
        "command": ["local-config-byte-snapshot", *review_paths],
        "cwd": str(project),
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "skipped": True,
        "review_note": "Git-ignored local config integrity is enforced by attestation hashes",
    }


def review_vibeguard_command(
    project: Path,
    rules: Path,
    run_command: CommandRunner,
    vibeguard_command: Callable[[Path, Path], list[str]],
    review_paths: list[str],
) -> Callable[[Path, Path], list[str]]:
    supports_path = bool(review_paths) and vibeguard_supports_path_option(
        vibeguard_command(project, rules),
        run_command,
        project,
    )

    def command(project_path: Path, rules_path: Path) -> list[str]:
        base = list(vibeguard_command(project_path, rules_path))
        if not review_paths:
            return base
        scoped = [*base, "--changed-only"]
        if supports_path:
            for review_path in review_paths:
                scoped.extend(["--path", review_path])
        return scoped

    setattr(command, "path_option_supported", supports_path)
    return command


def vibeguard_supports_path_option(
    base_command: list[str],
    run_command: CommandRunner,
    project: Path,
) -> bool:
    if not base_command:
        return False
    command = _vibeguard_help_command(base_command)
    result = run_command(command, project)
    if result.get("returncode") != 0:
        return False
    return "--path" in f"{result.get('stdout', '')}\n{result.get('stderr', '')}"


def _vibeguard_help_command(base_command: list[str]) -> list[str]:
    if base_command[:2] == ["npx", "--yes"] and len(base_command) >= 3:
        return [*base_command[:3], "--help"]
    return [base_command[0], "--help"]


def review_success_details(
    structure: dict[str, Any],
    review_scope: str,
    vibeguard_overall: str = "",
    accepted_vibeguard_reason: str = "",
) -> list[str]:
    details = [
        "code review evidence recorded",
        "docs freshness evidence recorded",
        f"review scope: {review_scope}",
        f"structure review passed for {structure['checked_path_count']} development source/style file(s)",
        f"structure scope: {structure['scope']}",
        "review scope guard passed",
        "review hook left worktree unchanged",
        "diff whitespace check passed",
        "workflow validation passed",
        _vibeguard_success_detail(vibeguard_overall, accepted_vibeguard_reason),
        "next required checkpoint: record every remaining route gate and run finish "
        "before commit, push, release, or handoff; changing the worktree first "
        "invalidates this review attestation",
    ]
    if accepted_vibeguard_reason:
        # Without this, a review that says "passed" is followed by a finish that
        # says "VibeGuard overall: Needs review" about the same audit, and the
        # reason already given here has to be discovered a second time.
        details.append(
            "finish judges the same VibeGuard state and does not read this "
            "review's reason: pass --allow-vibeguard-review to finish as well"
        )
    return details


def _vibeguard_success_detail(overall: str, accepted_reason: str) -> str:
    """Say what the audit found, not only that the hook let it through."""

    if not accepted_reason:
        return "VibeGuard audit passed"
    state = overall or "not Ready"
    return f"VibeGuard overall is {state}, accepted under the reason you passed"


def review_failure_details(
    failures: list[str],
    structure: dict[str, Any],
    review_scope: str,
) -> list[str]:
    details = [
        f"review scope: {review_scope}",
        f"structure scope: {structure['scope']}",
        f"checked development source/style files: {format_checked_paths(structure.get('checked_paths', []))}",
    ]
    details.extend(f"failure detail: {failure}" for failure in failures)
    details.append(
        "required recovery: run an actionable retrospective for this review failure, improve the "
        "owning Tao Agent OS doc, hook, validator, or test, and verify that repair outside the hook. "
        "Create a structural receipt with repair-verify, then verify this checkpoint with "
        "--repair-cycle 1 plus the same repair target, receipt path, and resume checkpoint "
        "before resuming the original task"
    )
    details.append("do not finalize with FAIL; ask only when recovery needs a scope decision, destructive action, credential change, external state, or a broader refactor")
    return details


def review_prerequisite_failure_details(failures: list[str]) -> list[str]:
    details = [f"review prerequisite: {failure}" for failure in failures]
    details.append(
        "review did not start: record or correct the missing prerequisite gate evidence, "
        "then rerun the same review hook without a repair cycle"
    )
    return details


def review_scope_invocation_failure_details(
    failure: str,
    review_scope: str,
    changed_path_count: int,
) -> list[str]:
    return [
        f"review scope: {review_scope}",
        f"review invocation: {failure}",
        "review did not start: narrow the review pathspec or rerun with "
        f"--max-changed-paths {changed_path_count} after confirming the change is one cohesive scope",
    ]


def format_checked_paths(paths: list[str]) -> str:
    if not paths:
        return "none"
    visible = paths[:8]
    suffix = "" if len(paths) <= len(visible) else f" ... (+{len(paths) - len(visible)} more)"
    return ", ".join(visible) + suffix
