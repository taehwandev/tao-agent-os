"""Build safe Codex subtask handoffs from workflow execution profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from workflow_dispatch_evidence import (
    execution_capsule_state as _execution_capsule_state,
    isolated_worker_evidence as _isolated_worker_evidence,
)
from workflow_dispatch_handoff import (
    build_handoff_state,
    build_handoff_prompt,
    codex_argv as _codex_argv,
    execution_policy as _execution_policy,
)
from workflow_dispatch_launch import (
    execute_dispatch_manifest as _execute_dispatch_manifest,
    print_dispatch_manifest as _print_dispatch_manifest,
)
from workflow_dispatch_profiles import (
    ORCHESTRATOR_PROFILE,
    WORK_KINDS,
    profile_for_work_kind,
    select_work_kind,
)
from agent_capability_policy import READ_ONLY_WORK_KINDS, capability_profile, validate_capability_profile
from agent_worktree_identity import new_worktree_path as _new_worktree_path
from agent_os_api import api_contract_manifest, runtime_adapter_contract, validate_runtime_adapter_contract
from workflow_classified_exemption import (
    parent_capsule_exemption,
    parent_evidence_path,
)
from workflow_request import (
    classified_route_block_reason,
    classify_request,
    route_block_reason,
)


def _validated_capability(
    selected_kind: str, *, isolation_required: bool
) -> tuple[dict[str, object], dict[str, object]]:
    """The worker's capability profile and runtime contract, both proven valid.

    Both are validated here rather than at use because an invalid profile must
    stop the dispatch, not reach a launcher that would read it as permission.
    """

    capability = capability_profile(selected_kind, isolation_required=isolation_required)
    capability_failures = validate_capability_profile(capability)
    if capability_failures:
        raise ValueError("invalid capability profile: " + "; ".join(capability_failures))
    runtime_contract = runtime_adapter_contract(
        "codex",
        capabilities={
            "read_only": capability["sandbox_mode"] == "read-only",
            "workspace_write": capability["sandbox_mode"] == "workspace-write",
            "isolated_write": capability.get("isolation_mode") == "isolated-write",
        },
        enforcement=str(capability["enforcement"]),
    )
    runtime_failures = validate_runtime_adapter_contract(runtime_contract)
    if runtime_failures:
        raise ValueError("invalid runtime adapter contract: " + "; ".join(runtime_failures))
    return capability, runtime_contract


def _worker_invocation(
    *,
    command: str,
    request: str,
    selected_kind: str,
    handoff_state: Mapping[str, object],
    continuation_scope: str,
    capability: Mapping[str, object],
    project: Path,
    profile: str,
    sandbox_mode: str,
) -> tuple[str, list[str]]:
    """Where the worker runs and the argv that starts it there.

    The two are decided together because the working directory is an argument
    of the command: a capability that asks for an isolated worktree has to name
    that path in the argv, and deciding them apart is how they drift.
    """

    handoff_prompt = build_handoff_prompt(
        command,
        request,
        selected_kind,
        handoff_state,
        non_authoring=selected_kind in READ_ONLY_WORK_KINDS,
        continuation_scope=continuation_scope,
    )
    isolated_worktree = capability.get("working_dir_kind") == "worktree"
    worktree_path = str(_new_worktree_path(project)) if isolated_worktree else ""
    working_dir = Path(worktree_path) if worktree_path else project
    return worktree_path, _codex_argv(
        project, profile, sandbox_mode, handoff_prompt, working_dir
    )


def build_dispatch_manifest(
    command: str,
    request: str,
    project: Path,
    *,
    continuation_scope: str = "",
    work_kind: str = "auto",
    complexity_evidence: str = "",
    route: Mapping[str, object] | None = None,
    request_classified: bool = False,
    classification_evidence: str = "",
    request_classification: Mapping[str, object] | None = None,
    parent_model: str = "",
    parent_reasoning_effort: str = "",
    parent_sandbox_mode: str = "",
    isolation_required: bool = False,
    heartbeat_interval_seconds: float = 0,
    partial_result_id: str = "",
    rules: Path | None = None,
    evidence_path: Path | None = None,
    worker_evidence_path: Path | None = None,
    parent_context_reusable: bool = True,
    reserve_worker_evidence: bool = False,
    worker_reservation_token: str = "",
    defer_capsule_validation: bool = False,
) -> dict[str, object]:
    """Create an inspectable dispatch decision for one bounded task stage."""

    classification = dict(
        request_classification
        or classify_request(request, continuation_scope=continuation_scope)
    )
    lexical_project = project.expanduser().absolute()
    project = project.expanduser().resolve()
    rules = (rules or Path(__file__).resolve().parents[1]).expanduser().resolve()
    parent_evidence = _parent_evidence_path(project, evidence_path)
    _raise_if_request_is_blocked(
        command,
        request,
        classification,
        continuation_scope=continuation_scope,
        request_classified=request_classified,
        classification_evidence=classification_evidence,
        project=project,
        rules=rules,
        evidence_path=parent_evidence,
    )
    selected_kind, profile, sandbox_mode, execution_mode, same_profile, selection_reason = (
        _select_execution_context(
            command,
            classification,
            work_kind=work_kind,
            complexity_evidence=complexity_evidence,
            parent_model=parent_model,
            parent_reasoning_effort=parent_reasoning_effort,
            parent_sandbox_mode=parent_sandbox_mode,
            isolation_required=isolation_required,
        )
    )
    handoff_state = build_handoff_state(
        command=command,
        project=project,
        lexical_project=lexical_project,
        rules=rules,
        route=route,
        parent_evidence=parent_evidence,
        parent_context_reusable=parent_context_reusable,
        worker_evidence_path=worker_evidence_path,
        execution_mode=execution_mode,
        reserve_worker_evidence=reserve_worker_evidence,
        worker_reservation_token=worker_reservation_token,
        defer_capsule_validation=defer_capsule_validation,
        execution_capsule_state=_execution_capsule_state,
        isolated_worker_evidence=_isolated_worker_evidence,
    )
    capability, runtime_contract = _validated_capability(
        selected_kind, isolation_required=isolation_required
    )
    worktree_path, argv = _worker_invocation(
        command=command,
        request=request,
        selected_kind=selected_kind,
        handoff_state=handoff_state,
        continuation_scope=continuation_scope,
        capability=capability,
        project=project,
        profile=profile,
        sandbox_mode=sandbox_mode,
    )
    return {
        "schema_version": 1,
        "project": str(project),
        "command": command,
        "request": request,
        "continuation_scope": continuation_scope,
        "request_classification": classification,
        "orchestrator_profile": ORCHESTRATOR_PROFILE,
        "work_profile": profile,
        "work_kind": selected_kind,
        "authoring_policy": capability["authoring_policy"],
        "sandbox_mode": capability["sandbox_mode"],
        "capability_profile": capability,
        "api_contract": api_contract_manifest(),
        "runtime_adapter": runtime_contract,
        "selection_reason": selection_reason,
        "execution_mode": execution_mode,
        "profile_matches_parent": same_profile,
        "isolation_required": isolation_required,
        "worktree_path": worktree_path or None,
        "heartbeat_interval_seconds": max(0.0, float(heartbeat_interval_seconds)),
        "partial_result_id": str(partial_result_id or ""),
        "handoff_state": handoff_state,
        # Kept for programmatic callers. Human-facing output always redacts it:
        # launch revalidates and rebuilds this argv immediately before execution.
        "codex_exec_argv": argv,
        "execution_policy": _execution_policy(execution_mode),
    }


def _raise_if_request_is_blocked(
    command: str,
    request: str,
    classification: Mapping[str, object],
    *,
    continuation_scope: str = "",
    request_classified: bool,
    classification_evidence: str,
    project: Path | None = None,
    rules: Path | None = None,
    evidence_path: Path | None = None,
) -> None:
    """Block a dispatch whose request was never actually resolved.

    ``--request-classified`` used to replace the classifier's verdict with a
    regex over free text the caller wrote about itself. Dispatch always has the
    real request in hand, so the classifier's verdict is dropped only when a
    ready and valid parent capsule proves a parent already resolved it.
    """

    exempt = False
    if request_classified:
        exempt, _reason = parent_capsule_exemption(
            project,
            rules,
            parent_evidence_path(project, evidence_path),
            command=command,
            request=request,
            continuation_scope=continuation_scope,
        )
    reason = route_block_reason(command, None if exempt else classification)
    if not reason and request_classified:
        reason = classified_route_block_reason(command, classification_evidence)
    if reason:
        raise ValueError(reason)


def _select_execution_context(
    command: str,
    classification: Mapping[str, object],
    *,
    work_kind: str,
    complexity_evidence: str,
    parent_model: str,
    parent_reasoning_effort: str,
    parent_sandbox_mode: str,
    isolation_required: bool,
) -> tuple[str, Mapping[str, str], str, str, bool, str]:
    selected_kind, selection_reason = select_work_kind(
        command, classification, work_kind, complexity_evidence
    )
    profile = profile_for_work_kind(selected_kind)
    sandbox_mode = (
        "read-only" if selected_kind in READ_ONLY_WORK_KINDS else "workspace-write"
    )
    parent_fields = (parent_model, parent_reasoning_effort, parent_sandbox_mode)
    same_profile = all(
        (
            parent_model == profile["codex_model"],
            parent_reasoning_effort == profile["reasoning_effort"],
            parent_sandbox_mode == sandbox_mode,
        )
    )
    # Dispatch is an execution-boundary decision, not a model-switching
    # mechanism. Keep any profile mismatch inspectable, but stay in the
    # parent session unless the caller explicitly requires isolation.
    if isolation_required:
        execution_reason = "explicit isolation requires a child process"
    elif not all(parent_fields):
        execution_reason = "parent profile is incomplete; continue inline"
    elif same_profile:
        execution_reason = "parent profile matches; continue inline"
    else:
        execution_reason = "parent profile differs; continue inline without a nested Codex process"
    return (
        selected_kind,
        profile,
        sandbox_mode,
        "child" if isolation_required else "inline",
        same_profile,
        f"{selection_reason}; {execution_reason}",
    )


def _parent_evidence_path(project: Path, evidence_path: Path | None) -> Path:
    return evidence_path.expanduser().resolve() if evidence_path else project / ".tao" / "preflight.json"


def execute_dispatch_manifest(
    manifest: Mapping[str, object],
    *,
    runner: Callable[[list[str]], int] | None = None,
) -> int:
    return _execute_dispatch_manifest(
        manifest,
        runner=runner,
        execution_capsule_state=_execution_capsule_state,
        isolated_worker_evidence=_isolated_worker_evidence,
        codex_argv=_codex_argv,
        build_handoff_prompt=build_handoff_prompt,
    )


def print_dispatch_manifest(manifest: Mapping[str, object], output_format: str) -> None:
    _print_dispatch_manifest(manifest, output_format)
