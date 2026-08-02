"""Prompt and argv construction for a bounded Codex handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

from agent_execution_capsule import capsule_path_for_evidence
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_worker_evidence import create_worker_reservation, worker_reservation_matches


def codex_argv(
    project: Path,
    profile: Mapping[str, object],
    sandbox_mode: str,
    handoff_prompt: str,
    working_dir: Path | None = None,
    *,
    trusted_worktree: Path | None = None,
) -> list[str]:
    # ``--cd`` binds the worker's working directory. For an isolated worker that
    # is its dedicated git worktree; otherwise it is the shared project checkout.
    cd = working_dir if working_dir is not None else project
    config_args = [
        "--config",
        f'model_reasoning_effort="{profile["reasoning_effort"]}"',
    ]
    if trusted_worktree is not None:
        trusted = Path(trusted_worktree).expanduser().resolve()
        bound = Path(cd).expanduser().resolve()
        if working_dir is None or trusted != bound:
            raise ValueError(
                "Codex worktree trust must target the exact verified --cd path"
            )
        quoted_path = json.dumps(str(trusted), ensure_ascii=False)
        config_args.extend(
            [
                "--config",
                f'projects={{ {quoted_path} = {{ trust_level = "trusted" }} }}',
            ]
        )
    return [
        "codex",
        "exec",
        "--model",
        str(profile["codex_model"]),
        *config_args,
        "--sandbox",
        sandbox_mode,
        "--cd",
        str(cd),
        handoff_prompt,
    ]


def execution_policy(execution_mode: str) -> str:
    if execution_mode == "inline":
        return "Continue inline in the parent; dispatch --execute must not start another Codex process."
    return (
        "Inspect-only manifest intentionally withholds the raw worker command. "
        "Use --execute to revalidate the capsule and reserve isolated worker "
        "evidence immediately before launch."
    )


def build_handoff_state(
    *,
    command: str,
    project: Path,
    lexical_project: Path,
    rules: Path,
    route: Mapping[str, object] | None,
    parent_evidence: Path,
    parent_context_reusable: bool,
    worker_evidence_path: Path | None,
    execution_mode: str,
    reserve_worker_evidence: bool,
    worker_reservation_token: str,
    defer_capsule_validation: bool,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
) -> dict[str, object]:
    """Create the parent evidence and fallback worker boundary for a manifest."""

    if defer_capsule_validation:
        # ``dispatch --execute`` immediately transfers control to the launch
        # boundary. Hashing the full worktree here and again at launch doubles
        # its cost without increasing safety.
        capsule_state: dict[str, object] = {
            "path": str(capsule_path_for_evidence(parent_evidence)),
            "reusable": False,
            "invalidation_reasons": ["execution capsule validation deferred to launch"],
            "phase": "pending",
        }
    else:
        capsule_state = execution_capsule_state(
            project,
            rules,
            parent_evidence,
            route,
            parent_context_reusable=parent_context_reusable,
        )
    worker_evidence = isolated_worker_evidence(
        project,
        parent_evidence,
        worker_evidence_path,
        lexical_project=lexical_project,
        reserve=False,
    )
    token = worker_reservation_token or None
    pre_reserved = bool(token) and worker_reservation_matches(
        worker_evidence.parent, str(token)
    )
    if token and not pre_reserved:
        raise ValueError(
            "Fallback worker reservation token does not match the requested evidence path."
        )
    should_reserve = (
        reserve_worker_evidence
        and not defer_capsule_validation
        and execution_mode == "child"
        and not bool(capsule_state.get("reusable"))
        and not pre_reserved
    )
    if should_reserve:
        worker_evidence = isolated_worker_evidence(
            project, parent_evidence, worker_evidence, reserve=True
        )
        token = create_worker_reservation(worker_evidence.parent)
    return {
        "route_command": command,
        "route_manifest": dict(route or {}),
        "required_docs": list(route.get("required_docs", [])) if route else [],
        "gates": list(route.get("gates", [])) if route else [],
        "rules": str(rules),
        "preflight_evidence": str(parent_evidence),
        "gate_ledger": str(gate_evidence_path_for_preflight(parent_evidence)),
        "worker_preflight_evidence": str(worker_evidence),
        "worker_gate_ledger": str(gate_evidence_path_for_preflight(worker_evidence)),
        "worker_evidence_reserved": pre_reserved or should_reserve,
        "worker_reservation_token": token,
        "parent_context_reusable": parent_context_reusable,
        "capsule_validation_deferred": defer_capsule_validation,
        "execution_capsule": capsule_state,
        "verification_plan": "run the nearest verification required by the parent route",
    }


def build_handoff_prompt(
    command: str,
    request: str,
    work_kind: str,
    handoff_state: Mapping[str, object],
    *,
    non_authoring: bool,
    continuation_scope: str = "",
) -> str:
    required_docs = ", ".join(str(doc) for doc in handoff_state["required_docs"])
    gates = ", ".join(str(gate) for gate in handoff_state["gates"])
    instructions = [
        "You are a delegated Codex worker for one bounded task stage.",
        "Do not delegate another Codex child from this worker.",
        "Follow the scoped handoff and preserve existing user changes.",
    ]
    if non_authoring:
        instructions.append(
            "This is a read-only non-authoring stage. Do not modify files, write code, generate patches, or create tests."
        )
    _add_capsule_instructions(instructions, handoff_state)
    reusable_capsule = _has_reusable_capsule(handoff_state)
    instructions.extend(
        [
            f"Workflow command: {command}",
            f"Work kind: {work_kind}",
            f"Tao Agent OS rules root: {handoff_state['rules']}",
            f"Parent route gates: {gates or 'resolve from the route'}",
            f"Parent preflight evidence: {handoff_state['preflight_evidence']}",
            f"Parent gate ledger: {handoff_state['gate_ledger']}",
            f"Verification plan: {handoff_state['verification_plan']}",
            "Read existing parent evidence when present. Do not overwrite parent gate-ledger entries.",
            "User request:",
            request,
        ]
    )
    if continuation_scope:
        instructions.extend(
            [
                "Continuation target (target identity only; not current intent or authorization):",
                continuation_scope,
            ]
        )
    if reusable_capsule:
        instructions.insert(
            instructions.index(f"Parent route gates: {gates or 'resolve from the route'}"),
            f"Required docs already read by the parent: {required_docs or 'none'}",
        )
    else:
        instructions.insert(
            instructions.index(f"Parent route gates: {gates or 'resolve from the route'}"),
            "Open and read every required doc from the parent route manifest before editing, reviewing, or running project-specific work.",
        )
        instructions.insert(
            instructions.index("Open and read every required doc from the parent route manifest before editing, reviewing, or running project-specific work."),
            f"Required docs from the parent route: {required_docs or 'resolve from the route'}",
        )
    return "\n".join(instructions)


def _add_capsule_instructions(
    instructions: list[str], handoff_state: Mapping[str, object]
) -> None:
    capsule_state = handoff_state.get("execution_capsule") or {}
    if isinstance(capsule_state, Mapping) and capsule_state.get("reusable"):
        instructions.extend(
            [
                f"Validated parent execution capsule: {capsule_state['path']}",
                "The parent already completed route, preflight, required-doc reading, VibeGuard, and review preparation.",
                "Reuse that route, preflight, and document-read evidence. Do not reread required docs or rerun route, startup, preflight, VibeGuard, review, finish, or other lifecycle work.",
                "Return only scoped implementation and verification evidence to the parent for its single integration, workflow validation, and final review.",
                "The parent remains the only owner of the gate ledger; child runtime guards make parent evidence read-only.",
            ]
        )
        return
    reasons = "; ".join(
        str(reason) for reason in capsule_state.get("invalidation_reasons", [])
    ) if isinstance(capsule_state, Mapping) else ""
    token = handoff_state.get("worker_reservation_token")
    instructions.extend(
        [
            "No reusable execution capsule is available. Follow the normal project lifecycle before work"
            + (f" ({reasons})." if reasons else "."),
            f"Use isolated worker preflight evidence: {handoff_state['worker_preflight_evidence']}",
            f"Use isolated worker gate ledger: {handoff_state['worker_gate_ledger']}",
            "Never write the parent evidence files.",
        ]
    )
    if token:
        instructions.append(
            f"Pass the worker preflight path with --evidence and --worker-reservation-token {token} to the worker start command; the token is single-use."
        )
    else:
        instructions.append(
            "The launcher must reserve the worker evidence directory and mint its single-use token before this worker starts."
        )


def _has_reusable_capsule(handoff_state: Mapping[str, object]) -> bool:
    capsule_state = handoff_state.get("execution_capsule")
    return isinstance(capsule_state, Mapping) and bool(capsule_state.get("reusable"))
