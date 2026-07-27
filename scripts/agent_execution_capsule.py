#!/usr/bin/env python3
"""Provider-neutral execution capsule lifecycle and CLI."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_continuation_outbound import assert_no_continuation_outbound
from agent_execution_capsule_state import (
    PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
    REUSE_POLICY,
    SCHEMA_VERSION,
    atomic_write_json,
    capsule_path_for_evidence,
    file_hash_record,
    git_states_for_paths,
    read_json_object,
)
from agent_execution_capsule_validation import (
    gate_ledger_failures,
    validate_execution_capsule as _validate_execution_capsule,
)
from agent_execution_capsule_docs import current_required_docs
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_route_state import request_fingerprint, route_fingerprint


def refresh_execution_capsule(
    project: Path,
    rules: Path,
    evidence_path: Path,
    route: dict[str, Any],
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Create or refresh a capsule bound to the current local execution state."""

    project = project.resolve()
    rules = rules.resolve()
    evidence_path = evidence_path.resolve()
    selected_output = (output_path or capsule_path_for_evidence(evidence_path)).resolve()
    project_git, rules_git = git_states_for_paths(project, rules)
    docs = current_required_docs(rules, route)
    ledger_path = gate_evidence_path_for_preflight(evidence_path)
    ledger_failures = gate_ledger_failures(ledger_path, evidence_path, route)
    phase = "ready" if docs is not None and not ledger_failures else "preflight"

    capsule: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(_request_intake(evidence_path)),
        "preflight_evidence": file_hash_record(evidence_path),
        "required_docs": docs or [],
        "project_git": project_git,
        "rules_git": rules_git,
        "reuse_policy": REUSE_POLICY,
    }
    if ledger_path.is_file():
        capsule["gate_ledger"] = file_hash_record(ledger_path)
    _write_execution_capsule(selected_output, capsule)
    return capsule


def create_preflight_snapshot(
    rules: Path,
    route: dict[str, Any],
    request_intake: dict[str, Any],
) -> dict[str, Any]:
    """Capture the source-doc binding needed by a serial parent workflow.

    This deliberately excludes mutable worktree Git state.  That expensive
    state is only needed for a child-reuse capsule and is captured lazily by
    the handoff boundary.
    """

    docs = current_required_docs(rules.resolve(), route)
    return {
        "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
        "route_fingerprint": route_fingerprint(route),
        "request_fingerprint": request_fingerprint(request_intake),
        "required_docs": docs or [],
    }


def synchronize_execution_capsule_gate_ledger(
    capsule: dict[str, Any],
    evidence_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Update only the ledger record after binding pre-existing gate evidence.

    Preflight must write request-intake evidence before a ready capsule exists,
    then bind that entry to the new capsule.  Recomputing the complete capsule
    after that binding would repeat the full worktree hash walk even though the
    ledger is the only changed input.  Keep the ready snapshot intact and
    atomically refresh just its ledger hash instead.
    """

    evidence_path = evidence_path.resolve()
    selected_output = (output_path or capsule_path_for_evidence(evidence_path)).resolve()
    ledger_path = gate_evidence_path_for_preflight(evidence_path)
    if not ledger_path.is_file():
        raise FileNotFoundError(f"execution capsule gate ledger is missing: {ledger_path}")
    updated = dict(capsule)
    updated["gate_ledger"] = file_hash_record(ledger_path)
    _write_execution_capsule(selected_output, updated)
    return updated


def _write_execution_capsule(path: Path, payload: dict[str, Any]) -> None:
    assert_no_continuation_outbound(
        {"path": path, "payload": payload},
        boundary="execution_capsule",
    )
    atomic_write_json(path, payload)


def read_execution_capsule(path: Path) -> dict[str, Any]:
    """Read a capsule without raising for a missing or malformed JSON file."""

    return read_json_object(path)


def validate_execution_capsule(
    capsule: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    route: dict[str, Any],
) -> list[str]:
    """Return invalidation reasons; an empty list means reusable."""

    evidence_path = evidence_path.resolve()
    return _validate_execution_capsule(
        capsule,
        project.resolve(),
        rules.resolve(),
        evidence_path,
        route,
    )


def _load_route(evidence_path: Path) -> dict[str, Any]:
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    route = payload.get("route") if isinstance(payload, dict) else None
    if not isinstance(route, dict):
        raise ValueError("preflight evidence does not contain a route manifest")
    return route


def _request_intake(evidence_path: Path) -> dict[str, Any]:
    """Read only the preflight's request-identity fields for capsule binding."""

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    intake = payload.get("request_intake") if isinstance(payload, dict) else None
    return dict(intake) if isinstance(intake, dict) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh or check an execution capsule.")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("refresh", "check"):
        command = commands.add_parser(action)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--rules", type=Path, required=True)
        command.add_argument("--evidence", type=Path, required=True)
    commands.choices["refresh"].add_argument("--output", type=Path)
    commands.choices["check"].add_argument("--capsule", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = args.evidence.resolve()
        route = _load_route(evidence)
        if args.action == "refresh":
            output = args.output.resolve() if args.output else capsule_path_for_evidence(evidence)
            capsule = refresh_execution_capsule(
                args.project, args.rules, evidence, route, output_path=output
            )
            print(json.dumps({"capsule": str(output), "phase": capsule["phase"]}, sort_keys=True))
            return 0
        capsule_path = args.capsule.resolve() if args.capsule else capsule_path_for_evidence(evidence)
        failures = validate_execution_capsule(
            read_execution_capsule(capsule_path),
            args.project,
            args.rules,
            evidence,
            route,
        )
        print(json.dumps({
            "capsule": str(capsule_path),
            "reusable": not failures,
            "reasons": failures,
        }, sort_keys=True))
        return 0 if not failures else 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"reusable": False, "reasons": [str(error)]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
