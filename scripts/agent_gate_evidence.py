"""Structured route gate evidence ledger."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_execution_capsule_state import (
    atomic_write_json,
    capsule_path_for_evidence,
    execution_capsule_binding_fingerprint,
    preflight_snapshot_binding_fingerprint,
    read_json_object,
)
from agent_delegation_plan import SEQUENTIAL_MULTI_AGENT_MARKER
from agent_execution_capsule_docs import bind_required_doc_update_receipt
from agent_route_state import (
    preflight_evidence_sha256,
    required_docs_for_route,
    route_fingerprint,
)
from agent_repair_ledger import (
    record_finish_failure_checkpoints,
    register_repair_attempt,
)
from agent_run_registry import (
    latest_run_id,
    ledger_writable_run_claim_transaction,
    registry_path,
)
from agent_state_lock import state_lock


GATE_EVIDENCE_FILENAME = "gate-evidence.json"
SCHEMA_VERSION = 1
CAPSULE_BINDING_FIELD = "execution_capsule_binding"


class GateEvidenceAccessError(PermissionError):
    """A logical caller/evidence boundary rejected mutation before a gate ran."""


FIELD_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "agentic run state": ("state", "transition", "evidence", "checkpoint", "blockers"),
    "alignment brief": (
        "shared_understanding",
        "possible_differences",
        "assumptions",
        "checkpoint",
    ),
    "ambiguity check": ("blocker_status", "assumptions", "decision"),
    "boundary plan": ("scope", "verification"),
    "cycle contract": (
        "cycle_type",
        "input_scope",
        "allowed_changes",
        "forbidden_changes",
        "acceptance_criteria",
        "verification",
        "stop_condition",
        "checkpoint",
    ),
    "documentation": ("decision", "target", "reason"),
    "documentation impact": ("artifact", "decision", "reason"),
    "graphify readiness": (
        "cli",
        "skill_doc",
        "runtime_links",
        "runtime_ownership",
        "project_integration",
        "graph",
        "query_smoke",
    ),
    "work surface resolution": (
        "result",
        "owner",
        "anchors",
        "evidence",
        "surface_paths",
        "concerns",
        "search_hops",
        "verification",
    ),
    "multi-agent split decision": ("mode", "reason", "verification"),
    "retrospective check": ("skills_checked", "outcome", "observation"),
    "side-effect audit": ("scope", "result"),
    "source docs": ("required_docs", "source", "takeaway"),
    "tests": ("check", "result"),
}

AMBIGUITY_BLOCKER_STATUSES = ("none", "resolved")
AMBIGUITY_DECISIONS = ("proceed",)
ALIGNMENT_BRIEF_CHECKPOINTS = ("user_visible_before_edits",)
GRAPHIFY_READINESS_STATUS = "success"
WORK_SURFACE_RESOLUTION_RESULTS = ("resolved",)


# Fields whose validator tests exact membership, so `start` can state the
# accepted values instead of leaving them to be found by failing finish. Naming
# the field was not enough: `retrospective check` was the largest recurring
# lesson class in the store, and its outcome and observation vocabularies are
# discoverable nowhere else.
#
# Only exact-membership fields belong here. A phrase-matching validator -- run
# state, documentation decision, multi-agent mode, tests result -- accepts prose
# containing a marker, so listing its markers as a closed set would advertise a
# restriction that does not exist. A prose-compatible gate may still constrain
# individual fields on its structured path; advertise only those fields. Values
# come from the owning validator, never restated here, so the advertisement
# cannot drift from the check.
def gate_field_enums(gate: str) -> dict[str, tuple[str, ...]]:
    """Return the exact accepted values for this gate's closed-set fields."""

    # Imported inside the call because the learning validators sit beside this
    # module's own consumers; a module-level import would couple load order for
    # no benefit.
    from agent_finish_gate_learning_validators import (
        RETROSPECTIVE_OBSERVATION_STATES,
        RETROSPECTIVE_OUTCOMES,
    )

    registry: dict[str, dict[str, tuple[str, ...]]] = {
        "ambiguity check": {
            "blocker_status": AMBIGUITY_BLOCKER_STATUSES,
            "decision": AMBIGUITY_DECISIONS,
        },
        "alignment brief": {
            "checkpoint": ALIGNMENT_BRIEF_CHECKPOINTS,
        },
        "retrospective check": {
            "outcome": tuple(sorted(RETROSPECTIVE_OUTCOMES)),
            "observation": tuple(sorted(RETROSPECTIVE_OBSERVATION_STATES)),
        },
        "graphify readiness": {
            field: (GRAPHIFY_READINESS_STATUS,)
            for field in FIELD_REQUIREMENTS["graphify readiness"]
        },
        "work surface resolution": {
            "result": WORK_SURFACE_RESOLUTION_RESULTS,
        },
    }
    return registry.get(gate, {})


MULTI_AGENT_PARALLEL_FIELDS = (
    "owned_scope",
    "forbidden_scope",
    "contract",
    "acceptance",
    "integration_owner",
)
MULTI_AGENT_SERIAL_MODES = {"serial", "single-agent", "single agent"}
# Several workers, dispatched one at a time, never concurrent. These modes are
# deliberately absent from MULTI_AGENT_SERIAL_MODES: real workers ran, so the
# record must still carry the full MULTI_AGENT_PARALLEL_FIELDS brief set. The
# only thing they are excused is the concurrent-writer delegation plan.
MULTI_AGENT_SEQUENTIAL_MODES = {
    "sequential",
    "serial-multi-agent",
    "sequential-multi-agent",
    "serial multi-agent",
    "sequential multi-agent",
    "serial-workers",
    "sequential-workers",
}
PROSE_COMPATIBLE_STRUCTURED_GATES = {"ambiguity check", "alignment brief"}


def _sibling_evidence_path(evidence_path: Path, default_filename: str, suffix: str) -> Path:
    """Resolve a file that lives next to one preflight evidence file.

    Every per-preflight side-file (gate ledger, repair-checkpoints record,
    ...) shares this naming rule: the canonical filename when evidence_path
    is the default "preflight.json", otherwise a name derived from that
    evidence file's own stem so worker-isolated evidence paths (which are
    not literally named "preflight.json") still get their own side-file
    instead of colliding with the parent's.
    """

    if evidence_path.name != "preflight.json":
        return evidence_path.parent / f"{evidence_path.stem}-{suffix}"
    return evidence_path.parent / default_filename


def gate_evidence_path_for_preflight(evidence_path: Path) -> Path:
    return _sibling_evidence_path(evidence_path, GATE_EVIDENCE_FILENAME, "gate-evidence.json")


def parse_field(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError("field must use key=value")
    key, field_value = value.split("=", 1)
    key = key.strip()
    field_value = field_value.strip()
    if not key or not field_value:
        raise ValueError("field key and value must both be non-empty")
    return key, field_value


def read_gate_evidence_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"invalid_json": True, "path": str(path)}


def reset_gate_evidence_ledger(evidence_path: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    with _ledger_mutation_transaction(evidence_path, preflight) as path:
        ledger = _new_ledger(evidence_path, preflight)
        _write_gate_evidence_ledger(path, ledger)
    return ledger


def record_gate_evidence(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    gate: str,
    evidence: str = "",
    fields: dict[str, str] | None = None,
    status: str = "SUCCESS",
    source: str = "manual",
) -> dict[str, Any]:
    entries = record_many_gate_evidence(
        evidence_path=evidence_path,
        preflight=preflight,
        records=[
            {
                "gate": gate,
                "evidence": evidence,
                "fields": fields or {},
                "status": status,
                "source": source,
            }
        ],
    )
    return entries[0]


def record_many_gate_evidence(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not records:
        return []
    with _ledger_mutation_transaction(evidence_path, preflight) as path:
        ledger = read_gate_evidence_ledger(path)
        if not _ledger_matches_preflight(ledger, evidence_path, preflight):
            ledger = _new_ledger(evidence_path, preflight)
        entries = [item for item in ledger.get("entries", []) if isinstance(item, dict)]
        recorded: list[dict[str, Any]] = []
        for record in records:
            gate = str(record.get("gate") or "").strip()
            if not gate:
                raise ValueError("gate evidence record requires a non-empty gate")
            status = str(record.get("status") or "SUCCESS").strip()
            if status not in {"SUCCESS", "FAIL"}:
                raise ValueError(f"gate evidence record has invalid status: {status}")
            fields = canonical_gate_fields(
                gate,
                _string_fields(record.get("fields") or {}),
                preflight,
            )
            fields = bind_required_doc_update_receipt(
                evidence_path=evidence_path,
                gate=gate,
                status=status,
                fields=fields,
            )
            capsule_binding = _capsule_binding_for_preflight(evidence_path, preflight)
            if capsule_binding:
                fields[CAPSULE_BINDING_FIELD] = capsule_binding
            entry = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "gate": gate,
                "status": status,
                "source": str(record.get("source") or "manual"),
                "evidence": str(record.get("evidence") or ""),
                "fields": dict(sorted(fields.items())),
            }
            entries.append(entry)
            recorded.append(entry)
        _refresh_ledger_binding(ledger, evidence_path, preflight)
        ledger["entries"] = entries
        _write_gate_evidence_ledger(path, ledger)
    return recorded


def bind_gate_evidence_to_capsule(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
) -> int:
    """Attach the ready capsule fingerprint to already-recorded route gates.

    Start must record request intake before a capsule can become ready.  This
    post-refresh pass closes that ordering gap without making a second
    document-reading command part of the lifecycle.
    """

    changed = 0
    with _ledger_mutation_transaction(evidence_path, preflight) as path:
        binding = _capsule_binding_for_preflight(evidence_path, preflight)
        if not binding:
            return 0
        ledger = read_gate_evidence_ledger(path)
        if not _ledger_matches_preflight(ledger, evidence_path, preflight):
            return 0
        required_gates = {str(gate) for gate in (preflight.get("route") or {}).get("gates", [])}
        entries = ledger.get("entries")
        if not isinstance(entries, list):
            return 0
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or entry.get("status") != "SUCCESS"
                or str(entry.get("gate") or "") not in required_gates
            ):
                continue
            fields = _string_fields(entry.get("fields") or {})
            if fields.get(CAPSULE_BINDING_FIELD) == binding:
                continue
            fields[CAPSULE_BINDING_FIELD] = binding
            entry["fields"] = dict(sorted(fields.items()))
            changed += 1
        if changed:
            _write_gate_evidence_ledger(path, ledger)
    return changed


def resync_gate_evidence_ledger(evidence_path: Path, preflight: dict[str, Any]) -> None:
    """Refresh the ledger's preflight binding after we mutate preflight.json ourselves.

    agent-hook.py's _register_started_run rewrites preflight.json in place to
    add agent_run_id right after "request intake" was already recorded
    against the pre-mutation content. Left alone, the ledger's stored
    preflight_evidence_sha256 goes stale, and the next gate write's self-heal
    check (record_many_gate_evidence / register_repair_attempt: "a stale
    ledger for the current preflight is not the same as an empty one") can no
    longer tell that stale-because-we-just-mutated-it apart from
    stale-because-this-is-a-genuinely-different-request, and silently wipes
    every already-recorded entry -- including "request intake" -- on every
    real task that reaches this point, not just when a new request begins.
    Call this immediately after any in-place preflight.json mutation whose
    route/request identity did not actually change.
    """

    with _ledger_mutation_transaction(evidence_path, preflight) as path:
        ledger = read_gate_evidence_ledger(path)
        if not ledger or ledger.get("invalid_json"):
            return
        # Only resync the binding fields when the route identity itself is
        # unchanged. If it genuinely differs (a real new request), leave the
        # mismatch alone so the normal self-heal path replaces the ledger.
        if ledger.get("route_fingerprint") != route_fingerprint(preflight.get("route") or {}):
            return
        _refresh_ledger_binding(ledger, evidence_path, preflight)
        _write_gate_evidence_ledger(path, ledger)


def _enforce_worker_evidence_boundary(evidence_path: Path) -> None:
    if os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        raise GateEvidenceAccessError(
            "reusable worker capsule cannot write parent gate evidence"
        )
    expected = os.environ.get("TAO_WORKER_EVIDENCE")
    if expected and evidence_path.resolve() != Path(expected).expanduser().resolve():
        raise GateEvidenceAccessError(
            "worker may write only its launcher-issued gate evidence"
        )


def _claim_project(evidence_path: Path) -> Path | None:
    """Locate the one ancestor registry that actually claims this evidence.

    Which registry answers "may this caller write here" has to be decided by
    the file about to be written, never by the preflight. Reading the project
    out of the preflight let a caller repoint that field at an unrelated
    directory: the guard then consulted a registry holding no claim, waved the
    write through, and the write still landed on the real evidence path. The
    same forged value also drove the registry's state lock into creating
    directories under a caller-supplied path.

    Directory shape is only candidate discovery, never ownership proof. Picking
    the nearest or outermost ``.tao`` is ambiguous when state roots are nested,
    and picking the nearest ancestor that merely *has* a state root lets an
    unrelated intermediate directory hide the registry with the real claim.
    Inspect only existing ancestor registries and keep the one whose opaque
    evidence binding actually matches this path. Multiple matching registries
    are an ownership ambiguity and fail closed instead of selecting by path
    order. No matching registry means this is a registry-free caller.
    """

    try:
        resolved = evidence_path.resolve()
    except OSError:
        return None
    matches: list[Path] = []
    for parent in resolved.parents:
        try:
            if not registry_path(parent).is_file():
                continue
        except OSError:
            continue
        if latest_run_id(parent, resolved):
            matches.append(parent)
    if len(matches) > 1:
        raise GateEvidenceAccessError(
            "gate evidence write rejected: multiple ancestor registries claim "
            "this evidence path; ownership is ambiguous"
        )
    return matches[0] if matches else None


@contextmanager
def _ledger_mutation_transaction(
    evidence_path: Path,
    preflight: dict[str, Any],
) -> Iterator[Path]:
    """Serialize claim validation and one gate-ledger mutation.

    Claimed evidence uses the system-wide project-state -> run-registry ->
    gate-ledger lock order implemented by
    ``ledger_writable_run_claim_transaction``. Keeping all four mutation paths
    here -- append, reset, resync, and capsule bind -- prevents any one of them
    from reopening the check-before-lock race. Evidence with no registry claim
    preserves the legacy ledger-only transaction.
    """

    _enforce_worker_evidence_boundary(evidence_path)
    path = gate_evidence_path_for_preflight(evidence_path)

    # The registry, not the preflight, decides whether a claim exists. The
    # preflight is the same caller-supplied file this guard protects, so
    # reading the answer out of it let one dropped field switch the guard off
    # and a foreign owner replace a recorded FAIL with SUCCESS. Where the
    # registry holds no claim for this evidence path there is nothing to
    # violate, which keeps registry-free callers working.
    project = _claim_project(evidence_path)
    if project is None:
        with state_lock(path):
            yield path
        return
    run_id = str(preflight.get("agent_run_id") or "").strip()
    with ledger_writable_run_claim_transaction(
        project,
        evidence_path,
        run_id,
        path,
    ) as writable:
        if not writable:
            raise GateEvidenceAccessError(
                "gate evidence write rejected: this run claim is not writable by the "
                "caller; either another live session owns it, the claim changed, or "
                "the run is already settled. A failed or reconcile_required run "
                "stays writable so its owner can record the missing gates and rerun "
                "finish."
            )
        yield path


def merge_gate_evidence_from_ledger(
    *,
    route: dict[str, Any],
    evidence_path: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    path = gate_evidence_path_for_preflight(evidence_path)
    ledger = read_gate_evidence_ledger(path)
    diagnostics: dict[str, Any] = {
        "path": str(path),
        "used": False,
        "warnings": [],
        "failed_gates": {},
        "invalid_statuses": {},
        "missing_fields": {},
        "sources": {},
        "capsule_bindings": {},
        "entry_fields": {},
    }
    if not ledger:
        return {}, diagnostics
    if ledger.get("invalid_json"):
        diagnostics["warnings"].append("gate evidence ledger is not valid JSON")
        return {}, diagnostics
    if not _ledger_matches_route(ledger, evidence_path, route):
        diagnostics["warnings"].append("gate evidence ledger is stale for the current preflight route")
        return {}, diagnostics

    merged: dict[str, str] = {}
    required_gates = {str(gate) for gate in (route.get("gates") or [])}
    for entry in ledger.get("entries", []):
        if not isinstance(entry, dict):
            continue
        gate = str(entry.get("gate") or "")
        if gate not in required_gates:
            continue
        status = str(entry.get("status") or "")
        if status == "FAIL":
            # Ledger order is authoritative.  A later structural failure must
            # invalidate every earlier success for the same checkpoint until a
            # gate hook records a later SUCCESS after repair.
            merged.pop(gate, None)
            diagnostics["failed_gates"][gate] = {
                "evidence": str(entry.get("evidence") or ""),
                "source": str(entry.get("source") or "ledger"),
            }
            diagnostics["sources"].pop(gate, None)
            diagnostics["capsule_bindings"].pop(gate, None)
            diagnostics["entry_fields"].pop(gate, None)
            diagnostics["missing_fields"].pop(gate, None)
            diagnostics["invalid_statuses"].pop(gate, None)
            continue
        if status != "SUCCESS":
            # A corrupt or hand-edited latest record must fail closed instead of
            # allowing an older success to remain authoritative.
            merged.pop(gate, None)
            diagnostics["failed_gates"].pop(gate, None)
            diagnostics["sources"].pop(gate, None)
            diagnostics["capsule_bindings"].pop(gate, None)
            diagnostics["entry_fields"].pop(gate, None)
            diagnostics["missing_fields"].pop(gate, None)
            diagnostics["invalid_statuses"][gate] = status or "<missing>"
            continue
        # Every later record is authoritative for its checkpoint.  Clear the
        # prior synthesized success before validating this one so an incomplete
        # or empty SUCCESS cannot silently fall back to older evidence.
        merged.pop(gate, None)
        diagnostics["failed_gates"].pop(gate, None)
        diagnostics["sources"].pop(gate, None)
        diagnostics["capsule_bindings"].pop(gate, None)
        diagnostics["entry_fields"].pop(gate, None)
        diagnostics["missing_fields"].pop(gate, None)
        diagnostics["invalid_statuses"].pop(gate, None)
        evidence, missing = synthesize_gate_evidence(
            gate,
            str(entry.get("evidence") or ""),
            _string_fields(entry.get("fields") or {}),
        )
        if missing:
            diagnostics["missing_fields"][gate] = missing
            continue
        if evidence:
            merged[gate] = evidence
            diagnostics["sources"][gate] = str(entry.get("source") or "ledger")
            entry_fields = _string_fields(entry.get("fields") or {})
            diagnostics["entry_fields"][gate] = entry_fields
            binding = entry_fields.get(CAPSULE_BINDING_FIELD)
            if binding:
                diagnostics["capsule_bindings"][gate] = binding
            else:
                diagnostics["capsule_bindings"].pop(gate, None)
            diagnostics["missing_fields"].pop(gate, None)

    diagnostics["used"] = bool(merged)
    return merged, diagnostics


def _render_cycle_contract(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'cycle contract' gate."""

    return (
        f"cycle_type={fields['cycle_type']}; input_scope={fields['input_scope']}; "
        f"allowed_changes={fields['allowed_changes']}; "
        f"forbidden_changes={fields['forbidden_changes']}; "
        f"acceptance criteria={fields['acceptance_criteria']}; "
        f"verification={fields['verification']}; "
        f"stop condition={fields['stop_condition']}; checkpoint={fields['checkpoint']}",
        [],
    )


def _render_agentic_run_state(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'agentic run state' gate."""

    return (
        f"run state: {fields['state']}; next transition: {fields['transition']}; "
        f"gate/command/check evidence: {fields['evidence']}; "
        f"checkpoint: {fields['checkpoint']}; blocker status: {fields['blockers']}",
        [],
    )


def _render_ambiguity_check(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'ambiguity check' gate."""

    failures: list[str] = []
    blocker_status = fields["blocker_status"].strip().lower()
    decision = fields["decision"].strip().lower()
    if blocker_status not in AMBIGUITY_BLOCKER_STATUSES:
        failures.append(
            "ambiguity check blocker_status must be "
            + " or ".join(AMBIGUITY_BLOCKER_STATUSES)
        )
    if decision not in AMBIGUITY_DECISIONS:
        failures.append(
            "ambiguity check decision must be " + " or ".join(AMBIGUITY_DECISIONS)
        )
    if failures:
        return "", failures
    return (
        "ambiguity check; no blockers or blockers resolved: "
        f"{blocker_status}; explicit safe assumptions: {fields['assumptions']}; "
        f"clarified decision: {decision}",
        [],
    )


def _render_alignment_brief(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'alignment brief' gate."""

    checkpoint = fields["checkpoint"].strip().lower()
    if checkpoint not in ALIGNMENT_BRIEF_CHECKPOINTS:
        return "", [
            "alignment brief checkpoint must be "
            + " or ".join(ALIGNMENT_BRIEF_CHECKPOINTS)
        ]
    return (
        f"alignment brief; shared understanding: {fields['shared_understanding']}; "
        f"possible differences: {fields['possible_differences']}; "
        f"unsupported assumptions/unknowns: {fields['assumptions']}; "
        "user-visible checkpoint before edits: user_visible_before_edits",
        [],
    )


def _render_boundary_plan(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'boundary plan' gate."""

    return (
        f"boundary/scope: {fields['scope']}; nearest verification/check: "
        f"{fields['verification']}",
        [],
    )


def _render_work_surface_resolution(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'work surface resolution' gate."""

    from agent_finish_gate_surface_validators import (
        validate_work_surface_resolution,
    )

    rendered = (
        f"work surface resolution: result={fields['result']}; "
        f"owner={fields['owner']}; anchors={fields['anchors']}; "
        f"evidence chain={fields['evidence']}; verified surface paths="
        f"{fields['surface_paths']}; concerns={fields['concerns']}; "
        f"search hops={fields['search_hops']}; nearest falsifying verification="
        f"{fields['verification']}"
    )
    return rendered, validate_work_surface_resolution(rendered)


def _render_multi_agent_split_decision(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'multi-agent split decision' gate."""

    mode = fields["mode"].lower()
    if mode in {"serial", "single-agent", "single agent"}:
        return (
            "serial/single-agent decision; concrete reason: "
            f"{fields['reason']}; verification: {fields['verification']}",
            [],
        )
    if mode in MULTI_AGENT_SEQUENTIAL_MODES:
        return (
            "sequential multi-agent/subagent delegation; "
            f"{SEQUENTIAL_MULTI_AGENT_MARKER}; concrete reason: {fields['reason']}; "
            f"owned scope: {fields['owned_scope']}; "
            f"forbidden scope: {fields['forbidden_scope']}; "
            f"contract/brief: {fields['contract']}; "
            f"acceptance checks: {fields['acceptance']}; "
            f"integration owner: {fields['integration_owner']}; "
            f"verification: {fields['verification']}",
            [],
        )
    return (
        "multi-agent/subagent split; owned scope: "
        f"{fields['owned_scope']}; forbidden scope: {fields['forbidden_scope']}; "
        f"contract/brief: {fields['contract']}; acceptance checks: {fields['acceptance']}; "
        f"integration owner: {fields['integration_owner']}; verification: {fields['verification']}",
        [],
    )


def _render_side_effect_audit(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'side-effect audit' gate."""

    return (
        "side-effect audit checked final diff; "
        f"scope/risk reviewed: {fields['scope']}; result: {fields['result']}",
        [],
    )


def _render_retrospective_check(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'retrospective check' gate."""

    return (
        "retrospective check; "
        f"skills checked: {fields['skills_checked']}; "
        f"outcome: {fields['outcome']}; "
        f"observation: {fields['observation']}",
        [],
    )


def _render_documentation_impact(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'documentation impact' gate."""

    return (
        "pre-code/pre-edit documentation artifact selection: "
        f"{fields['artifact']}; impact decision: {fields['decision']}; "
        f"reason: {fields['reason']}; original evidence: {evidence}",
        [],
    )


def _render_documentation(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'documentation' gate."""

    return (
        f"documentation decision: {fields['decision']}; source-of-truth target: "
        f"{fields['target']}; reason: {fields['reason']}; original evidence: {evidence}",
        [],
    )


def _render_source_docs(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'source docs' gate."""

    return (
        "read every route required_docs entry directly before implementation or edits; "
        f"required-doc reading: {fields['required_docs']}; "
        "searched and opened/read source-of-truth docs before implementation or edits; "
        f"source: {fields['source']}; applied takeaway: {fields['takeaway']}; "
        f"original evidence: {evidence}",
        [],
    )


def _render_tests(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'tests' gate."""

    return f"test/check run: {fields['check']}; result: {fields['result']}", []


def _render_graphify_readiness(
    gate: str, fields: dict[str, str], evidence: str
) -> tuple[str, list[str]]:
    """Render recorded evidence for the 'graphify readiness' gate."""

    invalid = [
        field
        for field in FIELD_REQUIREMENTS[gate]
        if fields[field].strip().lower() != GRAPHIFY_READINESS_STATUS
    ]
    if invalid:
        return "", [
            "graphify readiness fields must use exact success status: "
            + ", ".join(invalid)
        ]
    return (
        f"graphify readiness: cli={fields['cli']}; skill doc="
        f"{fields['skill_doc']}; runtime links={fields['runtime_links']}; "
        f"runtime ownership={fields['runtime_ownership']}; project integration="
        f"{fields['project_integration']}; target graph={fields['graph']}; "
        f"query smoke={fields['query_smoke']}",
        [],
    )


# One renderer per gate, because that is what the chain this replaced was:
# fourteen `if gate == ...` arms in one 181-line block, against the
# 120-line limit this repository enforces on every change. A table also
# says the thing the chain only implied -- that a gate with no renderer
# keeps the evidence it was given.
_GATE_RENDERERS = {
    "cycle contract": _render_cycle_contract,
    "agentic run state": _render_agentic_run_state,
    "ambiguity check": _render_ambiguity_check,
    "alignment brief": _render_alignment_brief,
    "boundary plan": _render_boundary_plan,
    "work surface resolution": _render_work_surface_resolution,
    "multi-agent split decision": _render_multi_agent_split_decision,
    "side-effect audit": _render_side_effect_audit,
    "retrospective check": _render_retrospective_check,
    "documentation impact": _render_documentation_impact,
    "documentation": _render_documentation,
    "source docs": _render_source_docs,
    "tests": _render_tests,
    "graphify readiness": _render_graphify_readiness,
}


def synthesize_gate_evidence(
    gate: str,
    evidence: str,
    fields: dict[str, str],
) -> tuple[str, list[str]]:
    fields = _canonical_structured_gate_fields(gate, fields)
    missing = missing_structured_gate_fields(gate, evidence, fields)
    if missing:
        return "", missing
    if gate in PROSE_COMPATIBLE_STRUCTURED_GATES and evidence.strip() and any(
        not fields.get(field, "").strip()
        for field in FIELD_REQUIREMENTS[gate]
    ):
        return evidence, []
    renderer = _GATE_RENDERERS.get(gate)
    if renderer is not None:
        return renderer(gate, fields, evidence)
    if not evidence.strip():
        generic_fields = {
            key: value
            for key, value in fields.items()
            if key != CAPSULE_BINDING_FIELD and value.strip()
        }
        if generic_fields:
            evidence = "; ".join(
                f"{key}={generic_fields[key]}" for key in sorted(generic_fields)
            )
    return evidence, []


def missing_structured_gate_fields(
    gate: str,
    evidence: str,
    fields: dict[str, str],
) -> list[str]:
    """Return the complete structured-field requirement for one gate record."""

    fields = _canonical_structured_gate_fields(gate, fields)
    if gate in PROSE_COMPATIBLE_STRUCTURED_GATES and evidence.strip():
        return []

    missing = [
        field
        for field in FIELD_REQUIREMENTS.get(gate, ())
        if not fields.get(field, "").strip()
    ]
    if gate != "multi-agent split decision":
        return missing

    mode = fields.get("mode", "").strip().lower()
    parallel = mode not in MULTI_AGENT_SERIAL_MODES
    if parallel:
        missing.extend(
            field
            for field in MULTI_AGENT_PARALLEL_FIELDS
            if not fields.get(field, "").strip()
        )
    return list(dict.fromkeys(missing))


def _canonical_structured_gate_fields(
    gate: str,
    fields: dict[str, str],
) -> dict[str, str]:
    """Translate bounded legacy field names without preserving them on new writes."""

    if gate != "graphify readiness":
        return fields
    canonical = dict(fields)
    if not canonical.get("runtime_ownership", "").strip():
        legacy_value = canonical.get("git_ownership", "")
        if legacy_value.strip():
            canonical["runtime_ownership"] = legacy_value
    canonical.pop("git_ownership", None)
    return canonical


def incomplete_gate_evidence_failures(diagnostics: dict[str, Any]) -> list[str]:
    """Expose legacy ledger omissions as complete, actionable finish failures."""

    failures: list[str] = []
    invalid_statuses = diagnostics.get("invalid_statuses") or {}
    if isinstance(invalid_statuses, dict):
        for gate, status in invalid_statuses.items():
            failures.append(
                f"structured gate evidence for {gate} has invalid status: {status}"
            )
    failed_gates = diagnostics.get("failed_gates") or {}
    if isinstance(failed_gates, dict):
        for gate in failed_gates:
            failures.append(
                f"structured gate evidence for {gate} is FAIL; record a later "
                "SUCCESS through the gate or gate-batch hook only after repair"
            )
    missing_fields = diagnostics.get("missing_fields") or {}
    if not isinstance(missing_fields, dict):
        return failures
    for gate, missing in missing_fields.items():
        if not isinstance(missing, list) or not missing:
            continue
        failures.append(
            f"structured gate evidence for {gate} is incomplete: " + ", ".join(str(item) for item in missing)
        )
    return failures


def latest_successful_gate_fields(
    *,
    route: dict[str, Any],
    evidence_path: Path,
    gate: str,
) -> dict[str, str]:
    """Return the latest current-route fields for one successful gate."""

    ledger = read_gate_evidence_ledger(gate_evidence_path_for_preflight(evidence_path))
    if not _ledger_matches_route(ledger, evidence_path, route):
        return {}
    for entry in reversed(ledger.get("entries", [])):
        if not isinstance(entry, dict) or str(entry.get("gate") or "") != gate:
            continue
        if entry.get("status") != "SUCCESS":
            return {}
        return _string_fields(entry.get("fields") or {})
    return {}


def _new_ledger(evidence_path: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    route = preflight.get("route") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "preflight_evidence": str(evidence_path.resolve()),
        "preflight_evidence_sha256": preflight_evidence_sha256(evidence_path),
        "route_fingerprint": route_fingerprint(route),
        "entries": [],
    }


def _ledger_matches_preflight(
    ledger: dict[str, Any],
    evidence_path: Path,
    preflight: dict[str, Any],
) -> bool:
    return _ledger_matches_route(ledger, evidence_path, preflight.get("route") or {})


def _ledger_matches_route(ledger: dict[str, Any], evidence_path: Path, route: dict[str, Any]) -> bool:
    if ledger.get("schema_version") != SCHEMA_VERSION:
        return False
    if not _same_evidence_path(ledger.get("preflight_evidence"), evidence_path):
        return False
    if ledger.get("preflight_evidence_sha256") != preflight_evidence_sha256(evidence_path):
        return False
    return ledger.get("route_fingerprint") == route_fingerprint(route)


def _same_evidence_path(recorded: Any, evidence_path: Path) -> bool:
    try:
        return Path(str(recorded)).expanduser().resolve() == evidence_path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _refresh_ledger_binding(
    ledger: dict[str, Any],
    evidence_path: Path,
    preflight: dict[str, Any],
) -> None:
    ledger["preflight_evidence"] = str(evidence_path.resolve())
    ledger["preflight_evidence_sha256"] = preflight_evidence_sha256(evidence_path)
    ledger["route_fingerprint"] = route_fingerprint(preflight.get("route") or {})


def canonical_gate_fields(
    gate: str,
    fields: dict[str, str],
    preflight: dict[str, Any],
) -> dict[str, str]:
    """Populate fields the agent must not be allowed to self-declare."""

    fields = _canonical_structured_gate_fields(gate, fields)
    if gate != "source docs":
        return fields
    required_docs = required_docs_for_route(preflight.get("route") or {})
    if required_docs:
        fields["required_docs"] = "required_docs manifest: " + ", ".join(required_docs)
    else:
        fields["required_docs"] = "required_docs manifest: empty"
    return fields


def _capsule_binding_for_preflight(
    evidence_path: Path,
    preflight: dict[str, Any],
) -> str | None:
    capsule = read_json_object(capsule_path_for_evidence(evidence_path))
    binding = execution_capsule_binding_fingerprint(capsule)
    if not binding:
        return _preflight_snapshot_binding(preflight)
    expected_hash = preflight_evidence_sha256(evidence_path)
    preflight_record = capsule.get("preflight_evidence")
    if not isinstance(preflight_record, dict):
        return _preflight_snapshot_binding(preflight)
    if preflight_record.get("sha256") != expected_hash:
        return _preflight_snapshot_binding(preflight)
    if capsule.get("route_fingerprint") != route_fingerprint(preflight.get("route") or {}):
        binding = None
    if binding:
        return binding
    return _preflight_snapshot_binding(preflight)


def _preflight_snapshot_binding(preflight: dict[str, Any]) -> str | None:
    snapshot = preflight.get("execution_snapshot")
    return (
        preflight_snapshot_binding_fingerprint(snapshot)
        if isinstance(snapshot, dict)
        else None
    )


def _string_fields(fields: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in fields.items() if value is not None}


def _write_gate_evidence_ledger(path: Path, ledger: dict[str, Any]) -> None:
    atomic_write_json(path, ledger)
