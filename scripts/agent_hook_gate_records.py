"""Gate ledger helpers for the Tao Agent OS hook CLI."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from agent_delegation_plan import (
    MULTI_AGENT_ROUTE_GATES,
    read_delegation_plan,
    validate_delegation_plan_evidence,
)
from agent_gate_evidence import (
    GateEvidenceAccessError,
    bind_gate_evidence_to_capsule,
    canonical_gate_fields,
    missing_structured_gate_fields,
    parse_field,
    record_gate_evidence,
    record_many_gate_evidence,
    reset_gate_evidence_ledger,
    synthesize_gate_evidence,
)
from agent_finish_gate_policy import MULTI_AGENT_GATE, validate_gate_evidence
from agent_finish_check_steps import validate_recorded_grill_me_evidence
from agent_finish_documentation import required_doc_target_failures
from agent_hook_runtime import finish_with_result
from agent_skill_catalog import canonical_skill_ids
from agent_runtime_session import resolve_runtime_evidence, runtime_session
from support.stage_timing import set_timing_sink


HOOK_OWNED_GATES = frozenset({"review hook"})


def preflight_evidence_path(args: argparse.Namespace) -> Path:
    """Resolve this hook's evidence path, and point stage timings beside it.

    Naming the timing sink here rather than in `main` is deliberate: this is
    the only function that knows which run directory a hook works in, and
    every caller reaches it after the worker evidence boundary has had its
    say, so a worker's durations land in the worker's run.
    """

    path = _resolve_preflight_evidence_path(args)
    set_timing_sink(path.parent / "timings.jsonl")
    return path


def _resolve_preflight_evidence_path(args: argparse.Namespace) -> Path:
    if args.evidence:
        return args.evidence
    session = runtime_session()
    if session:
        active = resolve_runtime_evidence(args.project, session)
        if active is not None:
            args.evidence = active
            return active
    if getattr(args, "hook", "") == "start":
        generated = (
            args.project / ".tao" / "runs" / uuid.uuid4().hex / "preflight.json"
        )
        args.evidence = generated
        return generated
    return args.project / ".tao" / "preflight.json"


def gate_hook(args: argparse.Namespace) -> int:
    fields: dict[str, str] = {}
    for raw_field in args.field:
        try:
            key, value = parse_field(raw_field)
        except ValueError as error:
            return _gate_failure(args, "gate", error, invocation_error=True)
        fields[key] = value
    try:
        entry = record_hook_gate(
            args,
            args.gate_name,
            args.gate_evidence or "",
            fields,
            args.source,
            args.status,
        )
    except json.JSONDecodeError as error:
        return _gate_failure(args, "gate", error, invocation_error=False)
    except ValueError as error:
        return _gate_failure(args, "gate", error, invocation_error=True)
    except GateEvidenceAccessError as error:
        return _gate_failure(args, "gate", error, invocation_error=True)
    except OSError as error:
        return _gate_failure(args, "gate", error, invocation_error=False)
    return finish_with_result(
        "gate",
        True,
        [f"gate evidence recorded: {entry['gate']}"],
        args.output,
        {"gate_evidence": entry},
        args.repair_cycle,
    )


def gate_batch_hook(args: argparse.Namespace) -> int:
    try:
        records = _gate_records_from_args(args)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return _gate_failure(args, "gate-batch", error, invocation_error=True)
    try:
        entries = record_hook_gate_batch(args, records)
    except json.JSONDecodeError as error:
        return _gate_failure(args, "gate-batch", error, invocation_error=False)
    except ValueError as error:
        return _gate_failure(args, "gate-batch", error, invocation_error=True)
    except GateEvidenceAccessError as error:
        return _gate_failure(args, "gate-batch", error, invocation_error=True)
    except OSError as error:
        return _gate_failure(args, "gate-batch", error, invocation_error=False)
    details = [f"{len(entries)} gate evidence entries recorded"]
    details.extend(f"recorded gate: {entry['gate']}" for entry in entries[:8])
    if len(entries) > 8:
        details.append(f"recorded gates truncated: {len(entries) - 8} more")
    return finish_with_result(
        "gate-batch",
        True,
        details,
        args.output,
        {"gate_evidence": entries},
        args.repair_cycle,
    )


def _gate_failure(
    args: argparse.Namespace,
    name: str,
    error: Exception,
    *,
    invocation_error: bool,
) -> int:
    if invocation_error and args.repair_cycle:
        rollback = getattr(args, "repair_invocation_rollback", None)
        if callable(rollback):
            rollback()
    return finish_with_result(
        name,
        False,
        [f"gate evidence ledger update failed: {error}"],
        args.output,
        {},
        args.repair_cycle,
        invocation_error=invocation_error,
    )


def record_hook_gate(
    args: argparse.Namespace,
    gate: str,
    evidence: str,
    fields: dict[str, str],
    source: str,
    status: str = "SUCCESS",
) -> dict[str, Any]:
    evidence_path = preflight_evidence_path(args)
    preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    record = {
        "gate": gate,
        "evidence": evidence,
        "fields": fields,
        "status": status,
        "source": source,
    }
    _validate_records_before_write(args, preflight, [record])
    return record_gate_evidence(
        evidence_path=evidence_path,
        preflight=preflight,
        gate=gate,
        evidence=evidence,
        fields=fields,
        status=status,
        source=source,
    )


def record_hook_gate_batch(
    args: argparse.Namespace,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_path = preflight_evidence_path(args)
    preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    _validate_records_before_write(args, preflight, records)
    return record_many_gate_evidence(
        evidence_path=evidence_path,
        preflight=preflight,
        records=records,
    )


def reset_and_record_start_gate(args: argparse.Namespace) -> None:
    evidence_path = preflight_evidence_path(args)
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    reset_and_record_preflight_gate(evidence_path, preflight, source="start")


def bind_existing_gate_evidence(evidence_path: Path, preflight: dict[str, Any]) -> int:
    """Bind start-time entries after their execution capsule becomes ready."""

    return bind_gate_evidence_to_capsule(
        evidence_path=evidence_path,
        preflight=preflight,
    )


def reset_and_record_preflight_gate(
    evidence_path: Path,
    preflight: dict[str, Any],
    *,
    source: str = "preflight",
) -> None:
    """Give direct preflight callers the same ledger initialization as start."""

    reset_gate_evidence_ledger(evidence_path, preflight)
    classification_evidence = (
        (preflight.get("request_intake") or {}).get("classification_evidence")
        or "request provided to preflight"
    )
    record_gate_evidence(
        evidence_path=evidence_path,
        preflight=preflight,
        gate="request intake",
        evidence=f"preflight request intake completed: {classification_evidence}",
        fields={"classification_evidence": str(classification_evidence)},
        status="SUCCESS",
        source=source,
    )


def _gate_records_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_record in args.gate_record:
        records.extend(_parse_gate_records(raw_record))
    if args.gate_json:
        records.extend(_parse_gate_records(args.gate_json.read_text(encoding="utf-8")))
    if not records:
        raise ValueError("gate-batch requires --gate-record or --gate-json")
    return records


def _parse_gate_records(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(raw)
    if isinstance(payload, list):
        return [_normalize_gate_record(item) for item in payload]
    return [_normalize_gate_record(payload)]


def _normalize_gate_record(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("gate record JSON must be an object or an array of objects")
    gate = str(payload.get("gate") or payload.get("gate_name") or "").strip()
    if not gate:
        raise ValueError("gate record JSON requires gate")
    status = str(payload.get("status") or "SUCCESS").strip()
    if status not in {"SUCCESS", "FAIL"}:
        raise ValueError(f"gate record JSON has invalid status: {status}")
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError(f"gate record for {gate} has non-object fields")
    return {
        "gate": gate,
        "status": status,
        "source": str(payload.get("source") or "manual"),
        "evidence": str(payload.get("evidence") or payload.get("gate_evidence") or ""),
        "fields": {str(key): str(value) for key, value in fields.items()},
    }


def _validate_records_before_write(
    args: argparse.Namespace,
    preflight: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    route = preflight.get("route") or {}
    required_gates = [str(gate) for gate in (route.get("gates") or [])]
    gate_evidence: dict[str, str] = {}
    validates_delegation_plan = False
    failures: list[str] = []

    for record in records:
        gate = str(record.get("gate") or "").strip()
        if gate in HOOK_OWNED_GATES:
            failures.append(
                f"{gate} is hook-owned; run tao-hook review instead of "
                "recording it through gate or gate-batch"
            )
            continue
        if str(record.get("status") or "SUCCESS") != "SUCCESS":
            continue
        evidence = str(record.get("evidence") or "")
        fields = canonical_gate_fields(
            gate,
            {str(key): str(value) for key, value in (record.get("fields") or {}).items()},
            preflight,
        )
        missing = missing_structured_gate_fields(gate, evidence, fields)
        if missing:
            failures.append(
                f"structured gate record for {gate} missing required fields: "
                + ", ".join(missing)
            )
            continue

        if gate == "documentation" and fields.get("decision", "").strip().lower() == "updated":
            target_failures = required_doc_target_failures(
                target=fields.get("target", ""),
                route=route,
            )
            if target_failures:
                failures.extend(target_failures)
                continue

        synthesized, synthesis_failures = synthesize_gate_evidence(
            gate,
            evidence,
            fields,
        )
        if synthesis_failures:
            failures.append(
                f"structured gate record for {gate} is incomplete: "
                + ", ".join(synthesis_failures)
            )
            continue
        # The observation-exists check belongs to finish, not here. Requiring it at
        # gate time deadlocked every reusable gap: `observation: recorded` needed a
        # stored observation, while the observation writer needed this gate to
        # already be recorded, and the transitional value was removed. Finish still
        # refuses a reusable gap whose observation is missing, via
        # skill_followup_failures.
        gate_evidence[gate] = synthesized or evidence
        if gate == MULTI_AGENT_GATE or gate in MULTI_AGENT_ROUTE_GATES:
            validates_delegation_plan = True

    failures.extend(
        validate_gate_evidence(
            gate_evidence,
            list(gate_evidence),
            route=route,
            allowed_skill_ids=canonical_skill_ids(
                args.project,
                getattr(args, "rules", Path(__file__).resolve().parents[1]),
            ),
        )
    )
    failures.extend(validate_recorded_grill_me_evidence(route, gate_evidence))

    if validates_delegation_plan:
        failures.extend(
            validate_delegation_plan_evidence(
                required_gates,
                gate_evidence,
                read_delegation_plan(args.project),
            )
        )
    if failures:
        raise ValueError("; ".join(dict.fromkeys(failures)))
