"""Execution-capsule handoff boundary for the hook CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_execution_capsule import (
    capsule_path_for_evidence,
    refresh_execution_capsule,
    synchronize_execution_capsule_gate_ledger,
    validate_execution_capsule,
)
from agent_execution_capsule_bindings import preflight_identity_failures
from agent_hook_gate_records import bind_existing_gate_evidence, preflight_evidence_path
from agent_hook_runtime import finish_with_result
from agent_worker_evidence import reserve_isolated_worker_evidence


def handoff_hook(args: argparse.Namespace) -> int:
    """Refresh and validate the optional parent-to-worker execution capsule."""

    evidence_path = preflight_evidence_path(args)
    details: list[str] = []
    capsule: dict[str, Any] = {}
    reasons: list[str] = []
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        route = preflight.get("route") if isinstance(preflight, dict) else None
        if not isinstance(route, dict):
            raise ValueError("preflight evidence does not contain a route manifest")
        capsule = refresh_execution_capsule(
            project=args.project,
            rules=args.rules,
            evidence_path=evidence_path,
            route=route,
        )
        if capsule.get("phase") == "ready":
            # A handoff captures a newer parent snapshot. Rebind the parent
            # ledger to that snapshot before the worker sees it, then update
            # only the ledger record without repeating the full hash walk.
            bind_existing_gate_evidence(evidence_path, preflight)
            capsule = synchronize_execution_capsule_gate_ledger(capsule, evidence_path)
        # refresh_execution_capsule has just captured the current git, required
        # document, and gate-ledger bindings. Avoid hashing that same state a
        # second time here; the child-launch boundary validates it again.
        reasons = preflight_identity_failures(
            evidence_path,
            args.project.resolve(),
            args.rules.resolve(),
        )
        if not reasons and capsule.get("phase") != "ready":
            reasons = validate_execution_capsule(
                capsule,
                project=args.project,
                rules=args.rules,
                evidence_path=evidence_path,
                route=route,
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        reasons = [str(error)]

    capsule_path = capsule_path_for_evidence(evidence_path)
    fallback_preflight: Path | None = None
    fallback_ledger: Path | None = None
    fallback_reservation_token: str | None = None
    if reasons:
        try:
            (
                fallback_preflight,
                fallback_ledger,
                fallback_reservation_token,
            ) = _fallback_worker_evidence_paths(args.project, evidence_path)
        except (OSError, ValueError) as error:
            details.append(f"unsafe fallback evidence boundary: {error}")
            return finish_with_result(
                "handoff",
                False,
                details,
                args.output,
                {
                    "execution_capsule": {
                        "path": str(capsule_path),
                        "reusable": False,
                        "invalidation_reasons": [*reasons, str(error)],
                        "fallback_worker_preflight_evidence": None,
                        "fallback_worker_gate_ledger": None,
                        "fallback_worker_reservation_token": None,
                    }
                },
                args.repair_cycle,
            )
        details.append(
            "execution capsule is not reusable; delegated workers must use the full lifecycle"
        )
        details.extend(f"invalidation: {reason}" for reason in reasons)
        details.extend(
            [
                f"worker preflight evidence: {fallback_preflight}",
                f"worker gate ledger: {fallback_ledger}",
                f"worker reservation token: {fallback_reservation_token}",
                "dispatch/start flags: "
                f"--evidence {fallback_preflight} "
                f"--worker-reservation-token {fallback_reservation_token}",
                "worker must pass its preflight path with --evidence and must never write the parent ledger",
            ]
        )
    else:
        details.extend(
            [
                "execution capsule is ready and valid",
                f"capsule: {capsule_path}",
                "worker may reuse route, preflight, and the required-doc manifest",
                "parent remains the sole gate-ledger owner; this hook does not record the route handoff gate",
            ]
        )
    return finish_with_result(
        "handoff",
        True,
        details,
        args.output,
        {
            "execution_capsule": {
                "path": str(capsule_path),
                "reusable": not reasons,
                "invalidation_reasons": reasons,
                "fallback_worker_preflight_evidence": (
                    str(fallback_preflight) if fallback_preflight else None
                ),
                "fallback_worker_gate_ledger": (
                    str(fallback_ledger) if fallback_ledger else None
                ),
                "fallback_worker_reservation_token": fallback_reservation_token,
            }
        },
        args.repair_cycle,
    )


def _fallback_worker_evidence_paths(
    project: Path,
    parent_evidence: Path,
) -> tuple[Path, Path, str]:
    """Reserve fallback evidence through the shared dispatch boundary helper."""

    return reserve_isolated_worker_evidence(project, parent_evidence)
