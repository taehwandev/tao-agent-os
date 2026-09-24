"""One invocation of the existing commit lifecycle for exact completed review.

Owner: commit preparation orchestration. Allowed imports: review evidence,
runtime identity and ordinary hook callbacks. Forbidden: Git writes, provider
calls and permission overrides. Callers/tests: agent-hook, test_agent_commit_ready.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from agent_gate_evidence import (
    GateEvidenceAccessError,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
)
from agent_hook_gate_records import _gate_progress
from agent_required_doc_reuse import required_doc_reuse
from agent_review_attestation import ReviewAttestation
from agent_review_reuse import ReviewReuse
from agent_runtime_session import runtime_session

COMMIT_READINESS_GATE = "commit readiness"


def prepare_commit(args: Any, start: Callable, dispatch: Callable) -> int:
    """Reuse proof, never authority; stop before each dependent step on failure."""
    try:
        if args.command not in {"commit", "git_commit"} or args.approved_effect not in {"git_write", "external_write"}:
            raise ValueError("--commit-ready requires commit and current git_write or external_write approval")
        if args.read_only or args.repair_cycle or args.output:
            raise ValueError("--commit-ready does not combine with read-only, repair or output")
        if getattr(args, "review_outcome", "") == "findings":
            raise ValueError("current review findings prevent compact commit preparation")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print(f"FAIL commit-ready: {error}.")
        return 2

    try:
        reuse, review_input = _completed_review(args)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        # Unavailable optimization is not failed authorization. Ordinary start
        # validates current authority and leaves every review gate outstanding.
        current = copy.copy(args)
        current.commit_ready = False
        print(f"Commit review reuse unavailable: {error}. Entering ordinary commit workflow; no evidence was reused. "
              "Continue this run and stage only the intended files before review; do not start again. "
              "For future compact entry, stage the reviewed unit before --commit-ready.")
        return start(current)

    # No staging or committing: the caller already staged the exact reviewed unit.
    current = copy.copy(args)
    current.commit_ready = False
    code = start(current)
    if code:
        return code
    current.continue_from = ""
    current.reuse_inputs = ""
    try:
        if required_doc_reuse(current.evidence)["unread"]:
            print("Compact completion deferred: required knowledge lacks matching history evidence. "
                  "Reuse unchanged readings retained in context; read only missing knowledge. "
                  "Continue this existing run with review and finish; do not start again.")
            return 0
        preflight = ReviewReuse.read(current.evidence)
        if set(preflight["route"]["gates"]) != {"request intake", "review hook", "commit readiness"}:
            raise ValueError("commit route has additional gates; continue this run normally")
        if reuse.capture() != reuse.before:
            raise ValueError("staged scope or rules changed during commit entry")
        for name, value in review_input.items():
            setattr(current, name, value)
        current.review_outcome = "pass"
        current.hook = "review"
        code = dispatch(current)
        if code:
            return code
        if reuse.capture() != reuse.before:
            raise ValueError("staged scope or rules changed during review")
        # Finish derives readiness from the current review; all other gates
        # must already be satisfied before invoking it.
        if set(_gate_progress(current)["remaining_gates"]) - {COMMIT_READINESS_GATE}:
            raise ValueError("commit route gates are incomplete; finish was not attempted")
        current.hook = "finish"
        return dispatch(current)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print(f"FAIL commit-ready: {error}; preserve the current run and staged bytes.")
        return 2


def derive_commit_readiness(project: Path, rules: Path, evidence_path: Path) -> str:
    """Record `commit readiness` at finish when the current review already proves it.

    The gate restates that the staged bytes are the reviewed bytes, which the
    review attestation binds. Only a current, hook-owned attestation derives it;
    any drift leaves the gate missing so finish still refuses.
    """
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        route = preflight.get("route") or {}
        if not {COMMIT_READINESS_GATE, "review hook"} <= set(route.get("gates") or []):
            return ""
        evidence, ledger = merge_gate_evidence_from_ledger(route=route, evidence_path=evidence_path)
        if COMMIT_READINESS_GATE in evidence or "review hook" not in evidence:
            return ""
        if ReviewAttestation.failures(
            project=project, rules=rules, evidence_path=evidence_path, route=route,
            ledger_fields=(ledger.get("entry_fields") or {}).get("review hook") or {},
            ledger_source=(ledger.get("sources") or {}).get("review hook", ""),
        ):
            return ""
        record_gate_evidence(
            evidence_path=evidence_path, preflight=preflight, gate=COMMIT_READINESS_GATE,
            evidence="Derived at finish: current bytes match the attested review; "
                     "no commit or external write executed.",
            source="finish",
        )
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, GateEvidenceAccessError):
        return ""
    return "commit readiness: derived from the current review attestation"


def _completed_review(args: Any) -> tuple[ReviewReuse, dict[str, str]]:
    project = args.project.resolve()
    cached = ReviewReuse.read(project / ".tao" / "review-checks-latest.json")
    source = (project / ".tao" / cached["evidence"]).resolve()
    source.relative_to(project / ".tao" / "runs")
    preflight = ReviewReuse.read(source)
    session = runtime_session()
    prior_session = preflight.get("runtime_session") or {}
    if not session.get("runtime") or not session.get("session_id") or any(
        prior_session.get(key) != session.get(key) for key in ("runtime", "session_id")
    ):
        raise ValueError("prior review belongs to a different or unknown runtime session")
    registry = ReviewReuse.read(project / ".tao" / "run-registry.json")
    records = [record for record in registry.get("runs", [])
               if record.get("run_id") == preflight.get("agent_run_id")]
    if len(records) != 1 or records[0].get("state") != "completed":
        raise ValueError("prior review run has not completed")
    if source != project / ".tao" / "runs" / preflight["agent_run_id"] / "preflight.json":
        raise ValueError("prior review is not canonical run evidence")
    if cached["snapshot"].get("scope") != "working-tree" or cached["snapshot"].get("paths"):
        raise ValueError("compact preparation requires a whole working-tree review")
    if args.review_scope != "working-tree" or args.review_path:
        raise ValueError("compact preparation cannot replace the reviewed scope")
    prior = copy.copy(args)
    prior.evidence = source
    reuse = ReviewReuse(prior, [], {"kind": "working-tree"})
    checks = reuse.load(require_commit_route=False)
    if checks is None or not reuse.before or not reuse.before["files"]:
        raise ValueError("staged bytes, scope, rules or attestation differ from prior review")
    inputs = checks.get("review_input")
    expected = {"code_review_evidence", "docs_freshness_evidence", "structure_review_evidence",
                "boundary_plan_evidence", "side_effect_audit_evidence"}
    if not isinstance(inputs, dict) or set(inputs) != expected or not all(isinstance(value, str) for value in inputs.values()):
        raise ValueError("prior attestation has no reusable review narratives")
    if not inputs.get("code_review_evidence") or not inputs.get("docs_freshness_evidence"):
        raise ValueError("prior review narratives are incomplete")
    return reuse, inputs
