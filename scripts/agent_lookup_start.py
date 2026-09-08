"""Stateless compatibility entry for ordinary read-only analysis.

Owner: lookup intake and guidance delivery. Allowed imports: request/effect
validation, route resolution, and standard library. Forbidden: lifecycle state
writers, registry, checkpoints, subprocess launchers. Caller: agent-hook main;
verification: test_agent_lookup_start. Explicit evidence and workers retain
their existing lifecycle boundary.
"""

from __future__ import annotations

import argparse
import json
import os

from agent_route_state import request_fingerprint
from workflow_doc_surfaces import extract_request_surface_paths
from workflow_gate_policy import READ_ONLY_LOOKUP
from workflow_intent_dual_run import route_intake_decision
from workflow_intent_envelope import read_approval_record, read_intent_envelope
from workflow_request import infer_concerns_from_request
from workflow_route import resolve_docs


def lookup_start(args: argparse.Namespace) -> int | None:
    """Handle fresh analysis without persistent state; None keeps legacy dispatch."""

    if args.hook != "start":
        return None
    if any(os.environ.get(name) for name in (
        "TAO_PARENT_EVIDENCE_READONLY", "TAO_WORKER_EVIDENCE",
    )) or args.worker_reservation_token:
        return None
    if args.evidence:
        try:
            existing = json.loads(args.evidence.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        route = existing.get("route") if isinstance(existing, dict) else None
        if isinstance(route, dict) and route.get("lifecycle_version", 1) == 1:
            print(json.dumps({"status": "FAIL", "lookup": False, "failures": [
                "existing legacy evidence is pinned; resume or finish that run, "
                "or use a fresh evidence path instead of overwriting it",
            ]}))
            return 2
        return None
    if args.command != "analysis":
        return None
    failures: list[str] = []
    if not args.request:
        failures.append("start requires --request with the real current request")
    if args.request_classified:
        failures.append("classified worker intake requires its existing capsule lifecycle")
    if args.output:
        failures.append("stateless lookup prints its result; omit --output")
    if args.repair_cycle:
        failures.append("stateless lookup has no repair cycle; omit --repair-cycle")
    intake = {
        "request": args.request,
        "continuation_scope": args.continuation_scope,
        "request_classified": args.request_classified,
        "classification_evidence": args.classification_evidence,
    }
    envelope = read_intent_envelope(args.intent_envelope)
    classification, authorization_failures = route_intake_decision(
        "analysis", envelope,
        approval=read_approval_record(args.approval_record),
        request_fingerprint=request_fingerprint(intake),
        runtime_session_id=args.runtime_session_id,
    )
    failures.extend(authorization_failures)
    if classification and classification["intent_envelope"]["effective_effect"] != "read":
        failures.append("stateless analysis permits only the read effect; select a work route")
    if failures:
        print(json.dumps({"status": "FAIL", "lookup": True, "failures": failures}))
        return 2

    concerns = list(dict.fromkeys([*args.concern, *infer_concerns_from_request(args.request)]))
    token = READ_ONLY_LOOKUP.set(True)
    try:
        route = resolve_docs(
            "analysis", args.platform[-1] if args.platform else None, concerns,
            request_classification=classification,
            request_text=args.request, project_root=args.project.resolve(),
            surface_paths=getattr(args, "surface_path", []),
        )
    finally:
        READ_ONLY_LOOKUP.reset(token)
    route.update(gates=[], gate_ledger=[], hooks=[])
    for field in (
        "skill_feedback", "parallel_execution", "repair_cycle_limit", "repair_policy",
        "resume_scope", "stop_condition", "notes",
    ):
        route.pop(field, None)
    candidates = [path for path in extract_request_surface_paths(args.request)
                  if path not in getattr(args, "surface_path", [])]
    if candidates:
        route["surface_candidates"] = {"request_paths": candidates, "dirty_paths": []}
    failed = bool(route["missing"] or route.get("blocking"))
    print(json.dumps({"status": "FAIL" if failed else "SUCCESS", "lookup": True, "route": route}))
    return 1 if failed else 0
