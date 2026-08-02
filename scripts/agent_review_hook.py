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
from agent_review_structure import REVIEW_ADDED_LINE_LIMIT, structure_review
from agent_repair_ledger import failure_signature, record_failure_checkpoints
from agent_vibeguard_cache import cached_vibeguard
from agent_workspace_policy import is_git_status_review_only, is_writing_workspace, non_git_writing_workspace_note


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
FinishWithResult = Callable[..., int]


def review_hook(
    args: Any,
    run_command: CommandRunner,
    git_status: Callable[[Path], tuple[dict[str, Any], list[str]]],
    vibeguard_command: Callable[[Path, Path], list[str]],
    parse_overall: Callable[[str], str],
    finish_with_result: FinishWithResult,
) -> int:
    checks: dict[str, Any] = {}
    prerequisite_failures: list[str] = []
    record_review_prerequisite_readiness(args, checks, prerequisite_failures)
    if prerequisite_failures:
        return finish_with_result(
            "review",
            False,
            review_prerequisite_failure_details(prerequisite_failures),
            args.output,
            checks,
            args.repair_cycle,
            invocation_error=True,
        )

    review_paths = review_pathspec(args)
    review_scope = review_scope_label(args, review_paths)
    checks["review_scope"] = review_scope
    checks["review_paths"] = review_paths
    full_status_before, full_status_before_lines = git_status(args.project)
    if is_git_status_review_only(args.project, full_status_before):
        full_status_before["review_only"] = True
        full_status_before["review_note"] = non_git_writing_workspace_note(args.project)
        full_status_before_lines = []
    checks["full_git_status_before"] = full_status_before
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
    checks["changed_path_count"] = len(status_before_lines)
    checks["changed_path_limit"] = args.max_changed_paths
    if status_before["returncode"] != 0 and not status_before.get("review_only"):
        failures = ["git status failed"]
    elif full_status_before["returncode"] != 0 and not full_status_before.get("review_only"):
        failures = ["git status failed"]
    elif len(status_before_lines) > args.max_changed_paths:
        scope_failure = (
            f"review scope has {len(status_before_lines)} changed paths; "
            f"limit is {args.max_changed_paths}; split the change or run a smaller review scope"
        )
        checks["review_scope_failure"] = scope_failure
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

    structure = structure_review(
        args.project,
        args.max_source_file_lines,
        args.max_function_lines,
        run_command,
        review_paths,
        max_added_lines=getattr(args, "max_added_lines", REVIEW_ADDED_LINE_LIMIT),
    )
    checks["structure_review"] = structure
    failures.extend(f"structure review: {failure}" for failure in structure["failures"])
    failures.extend(
        structure_evidence_failures(structure, (args.structure_review_evidence or "").strip())
    )

    diff_check = (
        {
            "command": ["git", "diff", "--check"],
            "cwd": str(args.project),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped": True,
            "review_note": non_git_writing_workspace_note(args.project),
        }
        if status_before.get("review_only")
        else run_command(diff_check_command(review_paths), args.project)
    )
    checks["diff_check"] = diff_check
    if diff_check["returncode"] != 0:
        failures.append("git diff --check failed")

    record_review_workflow_validation(args, checks, failures)
    record_review_vibeguard(
        args,
        run_command,
        vibeguard_command,
        parse_overall,
        review_paths,
        checks,
        failures,
    )
    record_review_worktree_stability(
        args,
        run_command,
        git_status,
        review_paths,
        status_before_lines,
        full_status_before_lines,
        checks,
        failures,
    )

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
    else:
        record_review_failure(args, failures)

    details = (
        review_failure_details(failures, structure, review_scope)
        if failures
        else review_success_details(structure, review_scope)
    )
    return finish_with_result("review", not failures, details, args.output, checks, args.repair_cycle)


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
) -> None:
    scoped_command = review_vibeguard_command(
        args.project,
        args.rules,
        run_command,
        vibeguard_command,
        review_paths,
    )
    checks["vibeguard_pathspec"] = {
        "paths": review_paths,
        "path_option_supported": bool(getattr(scoped_command, "path_option_supported", False)),
    }
    vibeguard = cached_vibeguard(
        project=args.project,
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
        args.project,
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
) -> None:
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


def review_scope_label(args: Any, review_paths: list[str]) -> str:
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


def diff_check_command(review_paths: list[str]) -> list[str]:
    if not review_paths:
        return ["git", "diff", "--check"]
    return ["git", "diff", "--check", "--", *review_paths]


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


def review_success_details(structure: dict[str, Any], review_scope: str) -> list[str]:
    return [
        "code review evidence recorded",
        "docs freshness evidence recorded",
        f"review scope: {review_scope}",
        f"structure review passed for {structure['checked_path_count']} development source/style file(s)",
        f"structure scope: {structure['scope']}",
        "review scope guard passed",
        "review hook left worktree unchanged",
        "diff whitespace check passed",
        "workflow validation passed",
        "VibeGuard audit passed",
    ]


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
