"""Launch-time validation and inspect-only rendering for Codex dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable, Mapping

from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_run_registry import latest_run_id
from agent_ipc import emit_heartbeat, emit_worker_failure, emit_worker_result
from agent_scheduler import claim_task, claim_next, choose_capacity, enqueue_task, heartbeat_task, retry_task, resume_task, transition_task
from agent_worker_evidence import create_worker_reservation, worker_reservation_matches
from agent_worktree_identity import (
    new_worktree_path,
    resolve_base_ref,
    validate_worker_worktree_identity,
)
from agent_worktree_session import create_worker_worktree
from workflow_dispatch_handoff import execution_policy


def execute_dispatch_manifest(
    manifest: Mapping[str, object],
    *,
    runner: Callable[[list[str]], int] | None,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
    codex_argv: Callable[..., list[str]],
    build_handoff_prompt: Callable[..., str],
) -> int:
    if manifest.get("execution_mode") == "inline":
        raise ValueError(
            "Inline dispatch is a decision only and cannot execute work in the parent process; "
            "omit --execute or require isolation."
        )
    if runner is not None and _is_worktree_isolated(manifest):
        # The injected runner returns before ``_bind_worker_working_dir`` and so
        # never creates the worktree; letting it proceed would silently run an
        # isolated worker with ``--cd`` pointed at the shared checkout. Fail closed
        # before claiming any scheduler task -- isolated manifests must launch the
        # real worker process (runner=None) that binds a real git worktree.
        raise ValueError(
            "injected-runner execution cannot honor worktree isolation; "
            "isolated manifests must launch the real worker process"
        )
    handoff = manifest.get("handoff_state")
    profile = manifest.get("work_profile")
    if not isinstance(handoff, Mapping) or not isinstance(profile, Mapping):
        raise ValueError("Dispatch manifest is missing handoff state or work profile")
    prepared = prepare_launch_handoff(
        manifest,
        handoff,
        execution_capsule_state=execution_capsule_state,
        isolated_worker_evidence=isolated_worker_evidence,
    )
    prompt = build_handoff_prompt(
        str(manifest["command"]),
        str(manifest.get("request", "")),
        str(manifest["work_kind"]),
        prepared,
        non_authoring=str(manifest.get("authoring_policy", "")).startswith("read-only"),
        continuation_scope=str(manifest.get("continuation_scope", "")),
    )
    argv = codex_argv(
        Path(str(manifest["project"])), profile, str(manifest["sandbox_mode"]), prompt
    )
    project = Path(str(manifest["project"])).resolve()
    scheduler_task = _claim_scheduler_task(manifest, prepared, project)
    heartbeat_interval = float(manifest.get("heartbeat_interval_seconds") or 0)
    task_context = {"task": scheduler_task}
    if runner:
        return _run_scheduled_worker(argv, runner, project, scheduler_task, heartbeat_interval_seconds=heartbeat_interval)
    try:
        working_dir, worktree_path = _bind_worker_working_dir(manifest, project)
    except BaseException:
        # The scheduler task is already marked running; a worktree-creation
        # failure here must transition it to a terminal failed state rather than
        # leaving it stuck as running before the worker loop's own guard begins.
        transition_task(project, str(scheduler_task["task_id"]), "failed")
        raise
    if worktree_path:
        # Rebind ``--cd`` to the freshly created worktree so the real worker
        # process writes inside its isolated tree, never the shared checkout.
        # The ephemeral project-trust override is allowed only after that exact
        # path has passed the same-repository linked-worktree identity check.
        argv = codex_argv(
            project,
            profile,
            str(manifest["sandbox_mode"]),
            prompt,
            working_dir,
            trusted_worktree=working_dir,
        )
    try:
        return _run_scheduled_worker(
            argv,
            lambda command: subprocess.run(
                command,
                check=False,
                env=worker_environment(prepared, task_context["task"], worktree_path=worktree_path),
            ).returncode,
            project,
            scheduler_task,
            heartbeat_interval_seconds=heartbeat_interval,
            task_context=task_context,
        )
    except OSError as error:
        raise RuntimeError("Unable to start the delegated Codex worker") from error


def _is_worktree_isolated(manifest: Mapping[str, object]) -> bool:
    capability = manifest.get("capability_profile")
    if isinstance(capability, Mapping) and capability.get("working_dir_kind") == "worktree":
        return True
    return bool(manifest.get("isolation_required"))


def _bind_worker_working_dir(
    manifest: Mapping[str, object], project: Path
) -> tuple[Path, str]:
    """Create the isolated worktree fail-closed and return its bound working dir.

    Shared (non-isolated) workers keep the project checkout and an empty worktree
    marker. Isolated workers get a real ``git worktree add`` at the manifest's
    planned path; setup failure raises rather than falling back to the checkout.
    """

    if not _is_worktree_isolated(manifest):
        return project, ""
    worktree_path = str(manifest.get("worktree_path") or "") or str(
        new_worktree_path(project)
    )
    base_ref = resolve_base_ref(project)
    create_worker_worktree(project, base_ref, Path(worktree_path))
    verified = validate_worker_worktree_identity(project, Path(worktree_path))
    return verified, str(verified)


def _claim_scheduler_task(
    manifest: Mapping[str, object], prepared: Mapping[str, object], project: Path
) -> dict[str, object]:
    parent_evidence = Path(str(prepared["preflight_evidence"])).resolve()
    run_id = latest_run_id(project, parent_evidence) or uuid.uuid4().hex
    independent_slices = int(manifest.get("independent_slices") or 1)
    max_retries = int(manifest.get("max_retries") or 0)
    capacity = choose_capacity(independent_slices, int(manifest.get("requested_workers") or 1))
    task = enqueue_task(
        project,
        run_id,
        priority=int(manifest.get("priority") or 0),
        independent_slices=independent_slices,
        max_retries=max_retries,
        partial_result_id=str(manifest.get("partial_result_id") or "") or None,
    )
    claimed = claim_next(project, capacity=capacity)
    if not claimed or claimed.get("task_id") != task.get("task_id"):
        raise RuntimeError("scheduler capacity is exhausted; worker remains queued")
    return task


def _run_scheduled_worker(
    argv: list[str],
    runner: Callable[[list[str]], int],
    project: Path,
    task: Mapping[str, object],
    *,
    heartbeat_interval_seconds: float = 0,
    task_context: dict[str, object] | None = None,
) -> int:
    if heartbeat_interval_seconds < 0:
        raise ValueError("heartbeat_interval_seconds must be non-negative")
    current_task = dict(task)
    while True:
        task_id = str(current_task["task_id"])
        worker_id = f"worker-{task_id}"
        stop_heartbeat = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        events_enabled = heartbeat_interval_seconds > 0
        if events_enabled:
            heartbeat_task(project, task_id)
            emit_heartbeat(
                project,
                run_id=str(current_task["run_id"]),
                task_id=task_id,
                worker_id=worker_id,
                attempt=int(current_task.get("attempt") or 1),
            )

            def heartbeat_loop() -> None:
                while not stop_heartbeat.wait(heartbeat_interval_seconds):
                    if heartbeat_task(project, task_id) is None:
                        return
                    emit_heartbeat(
                        project,
                        run_id=str(current_task["run_id"]),
                        task_id=task_id,
                        worker_id=worker_id,
                        attempt=int(current_task.get("attempt") or 1),
                    )

            heartbeat_thread = threading.Thread(target=heartbeat_loop, name=f"agent-heartbeat-{task_id}", daemon=True)
            heartbeat_thread.start()
        try:
            result = runner(argv)
        except BaseException:
            stop_heartbeat.set()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=max(1.0, heartbeat_interval_seconds))
            if events_enabled:
                emit_worker_failure(
                    project,
                    run_id=str(current_task["run_id"]),
                    task_id=task_id,
                    worker_id=worker_id,
                    attempt=int(current_task.get("attempt") or 1),
                )
            transition_task(project, task_id, "failed")
            raise
        stop_heartbeat.set()
        if heartbeat_thread:
            heartbeat_thread.join(timeout=max(1.0, heartbeat_interval_seconds))
        if result == 0:
            if events_enabled:
                emit_worker_result(
                    project,
                    run_id=str(current_task["run_id"]),
                    task_id=task_id,
                    worker_id=worker_id,
                    result_id=f"result-{uuid.uuid4().hex}",
                    attempt=int(current_task.get("attempt") or 1),
                )
            transition_task(project, task_id, "completed")
            return result
        if events_enabled:
            emit_worker_failure(
                project,
                run_id=str(current_task["run_id"]),
                task_id=task_id,
                worker_id=worker_id,
                attempt=int(current_task.get("attempt") or 1),
            )
        transition_task(project, task_id, "failed")
        retried = resume_task(project, task_id) if current_task.get("partial_result_id") else retry_task(project, task_id)
        if retried is None:
            return result
        claimed = claim_task(
            project,
            task_id,
            capacity=choose_capacity(
                int(retried.get("independent_slices") or 1),
                int(retried.get("requested_workers") or 1),
            ),
        )
        if not claimed or claimed.get("task_id") != task_id:
            return result
        current_task = claimed
        if task_context is not None:
            task_context["task"] = current_task


def prepare_launch_handoff(
    manifest: Mapping[str, object],
    handoff: Mapping[str, object],
    *,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
) -> dict[str, object]:
    prepared = dict(handoff)
    project = Path(str(manifest["project"])).resolve()
    rules = Path(str(prepared["rules"])).resolve()
    parent_evidence = Path(str(prepared["preflight_evidence"])).resolve()
    route = prepared.get("route_manifest")
    if not isinstance(route, Mapping):
        raise ValueError("Dispatch manifest is missing the parent route manifest")
    prepared["execution_capsule"] = execution_capsule_state(
        project,
        rules,
        parent_evidence,
        route,
        parent_context_reusable=prepared.get("parent_context_reusable") is True,
    )
    capsule = prepared["execution_capsule"]
    if isinstance(capsule, Mapping) and capsule.get("reusable"):
        return prepared
    worker_evidence = Path(str(prepared["worker_preflight_evidence"])).resolve()
    token = prepared.get("worker_reservation_token")
    if prepared.get("worker_evidence_reserved"):
        if not token or not worker_reservation_matches(worker_evidence.parent, str(token)):
            raise ValueError("Fallback worker reservation token does not match the reserved evidence path.")
    else:
        worker_evidence = isolated_worker_evidence(
            project, parent_evidence, worker_evidence, reserve=True
        )
        token = create_worker_reservation(worker_evidence.parent)
    prepared["worker_preflight_evidence"] = str(worker_evidence)
    prepared["worker_gate_ledger"] = str(gate_evidence_path_for_preflight(worker_evidence))
    prepared["worker_evidence_reserved"] = True
    prepared["worker_reservation_token"] = token
    return prepared


def worker_environment(
    handoff: Mapping[str, object],
    task: Mapping[str, object] | None = None,
    *,
    worktree_path: str = "",
) -> dict[str, str]:
    environment = dict(os.environ)
    if worktree_path:
        environment["TAO_WORKER_WORKTREE"] = worktree_path
    capsule = handoff.get("execution_capsule")
    if isinstance(capsule, Mapping) and capsule.get("reusable"):
        environment["TAO_PARENT_EVIDENCE_READONLY"] = "1"
        environment["TAO_CAPABILITY_ENFORCEMENT"] = "parent-evidence-readonly"
        return environment
    environment["TAO_WORKER_EVIDENCE"] = str(handoff["worker_preflight_evidence"])
    environment["TAO_WORKER_RESERVATION_TOKEN"] = str(
        handoff["worker_reservation_token"]
    )
    environment["TAO_CAPABILITY_ENFORCEMENT"] = "worker-evidence-and-state"
    if task and task.get("task_id"):
        environment["TAO_TASK_ID"] = str(task["task_id"])
    if task and task.get("partial_result_id"):
        environment["TAO_RESUME_RESULT_ID"] = str(task["partial_result_id"])
    return environment


def print_dispatch_manifest(manifest: Mapping[str, object], output_format: str) -> None:
    if output_format == "json":
        output = dict(manifest)
        output["codex_exec_argv"] = []
        output["codex_exec_command"] = ""
        output["execution_policy"] = execution_policy(str(manifest.get("execution_mode")))
        print(json.dumps(output, indent=2, sort_keys=True))
        return
    profile = manifest["work_profile"]
    assert isinstance(profile, Mapping)
    capsule = manifest["handoff_state"]["execution_capsule"]
    assert isinstance(capsule, Mapping)
    print("# Tao Agent OS Codex Handoff\n")
    print(f"- Work kind: `{profile['work_kind']}`")
    print(f"- Codex model: `{profile['codex_model']}`")
    print(f"- Reasoning effort: `{profile['reasoning_effort']}`")
    print(f"- Authoring policy: `{manifest['authoring_policy']}`")
    print(f"- Execution mode: `{manifest['execution_mode']}`")
    print(f"- Execution capsule reusable: `{str(bool(capsule['reusable'])).lower()}`")
    print(f"- Selection: {manifest['selection_reason']}\n")
    print("## Execution Boundary")
    print(execution_policy(str(manifest.get("execution_mode"))))
