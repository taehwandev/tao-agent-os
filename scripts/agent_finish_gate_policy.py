"""Evidence validation rules for finish-check route gates."""

from __future__ import annotations

from agent_finish_gate_boundary_validators import (
    validate_agentic_run_state,
    validate_boundary_plan,
    validate_side_effect_audit,
)
from agent_finish_gate_collaboration_validators import (
    validate_multi_agent,
    validate_multi_agent_briefs,
    validate_multi_agent_integration_review,
    validate_multi_agent_roles,
    validate_multi_agent_write_scopes,
    validate_workspace_scope_checkpoint,
)
from agent_finish_gate_core_validators import (
    validate_alignment_brief,
    validate_ambiguity,
)
from agent_finish_gate_doc_test_validators import validate_documentation, validate_tests
from agent_finish_gate_cycle_validators import (
    validate_cycle_contract,
)
from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_finish_gate_skip_policy import validate_required_gate_not_skipped
from agent_finish_gate_validators import (
    validate_documentation_impact_evidence,
    validate_documentation_source_to_artifact_evidence,
    validate_platform_selection_evidence,
    validate_prd_draft_evidence,
    validate_product_reentry_evidence,
    validate_review_readiness_evidence,
    validate_source_docs_evidence,
)
from agent_route_state import required_docs_for_route


AMBIGUITY_GATE = "ambiguity check"
ALIGNMENT_BRIEF_GATE = "alignment brief"
DOCUMENTATION_IMPACT_GATE = "documentation impact"
DOCUMENTATION_GATE = "documentation"
TEST_GATE = "tests"
CYCLE_CONTRACT_GATE = "cycle contract"
BOUNDARY_PLAN_GATE = "boundary plan"
MULTI_AGENT_GATE = "multi-agent split decision"
SIDE_EFFECT_AUDIT_GATE = "side-effect audit"
AGENTIC_RUN_STATE_GATE = "agentic run state"
SOURCE_DOCS_GATE = "source docs"
PRODUCT_REENTRY_GATE = "product route re-entry"
RETROSPECTIVE_CHECK_GATE = "retrospective check"
GRAPHIFY_READINESS_GATE = "graphify readiness"
PLATFORM_SELECTION_GATE = "platform selection"
REVIEW_READINESS_GATE = "review readiness"
PRD_DRAFT_GATE = "PRD draft"
MULTI_AGENT_ROLES_GATE = "roles"
MULTI_AGENT_WRITE_SCOPES_GATE = "write scopes"
MULTI_AGENT_BRIEFS_GATE = "agent briefs"
MULTI_AGENT_INTEGRATION_REVIEW_GATE = "integration review"
WORKSPACE_SCOPE_CHECKPOINT_GATES = (
    "workspace scope checkpoint",
    "scope expansion checkpoint",
    "cross-repo scope checkpoint",
)
SKIP_ALLOWED_GATES = {
    DOCUMENTATION_IMPACT_GATE,
    DOCUMENTATION_GATE,
    TEST_GATE,
    MULTI_AGENT_GATE,
    PLATFORM_SELECTION_GATE,
}
VALIDATED_GATES = {
    AMBIGUITY_GATE,
    ALIGNMENT_BRIEF_GATE,
    DOCUMENTATION_IMPACT_GATE,
    DOCUMENTATION_GATE,
    TEST_GATE,
    CYCLE_CONTRACT_GATE,
    BOUNDARY_PLAN_GATE,
    MULTI_AGENT_GATE,
    SIDE_EFFECT_AUDIT_GATE,
    AGENTIC_RUN_STATE_GATE,
    SOURCE_DOCS_GATE,
    PRODUCT_REENTRY_GATE,
    RETROSPECTIVE_CHECK_GATE,
    GRAPHIFY_READINESS_GATE,
    PLATFORM_SELECTION_GATE,
    REVIEW_READINESS_GATE,
    PRD_DRAFT_GATE,
    MULTI_AGENT_ROLES_GATE,
    MULTI_AGENT_WRITE_SCOPES_GATE,
    MULTI_AGENT_BRIEFS_GATE,
    MULTI_AGENT_INTEGRATION_REVIEW_GATE,
    *WORKSPACE_SCOPE_CHECKPOINT_GATES,
}


def validate_gate_evidence(
    gate_evidence: dict[str, str],
    required_gates: list[str],
    *,
    route: dict[str, object] | None = None,
    allowed_skill_ids: set[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    required = set(required_gates)
    for gate in required:
        failures.extend(
            validate_required_gate_not_skipped(
                gate,
                gate_evidence.get(gate, ""),
                SKIP_ALLOWED_GATES,
            )
        )
    if AMBIGUITY_GATE in required:
        failures.extend(validate_ambiguity(gate_evidence.get(AMBIGUITY_GATE, "")))
    if ALIGNMENT_BRIEF_GATE in required:
        failures.extend(validate_alignment_brief(gate_evidence.get(ALIGNMENT_BRIEF_GATE, "")))
    if DOCUMENTATION_IMPACT_GATE in required:
        failures.extend(
            validate_documentation_impact_evidence(
                gate_evidence.get(DOCUMENTATION_IMPACT_GATE, "")
            )
        )
    if DOCUMENTATION_GATE in required:
        failures.extend(validate_documentation(gate_evidence.get(DOCUMENTATION_GATE, "")))
    if SOURCE_DOCS_GATE in required:
        required_docs = required_docs_for_route(route) if route is not None else None
        failures.extend(
            validate_source_docs_evidence(
                gate_evidence.get(SOURCE_DOCS_GATE, ""),
                required_docs=required_docs,
            )
        )
    if PRODUCT_REENTRY_GATE in required:
        failures.extend(validate_product_reentry_evidence(gate_evidence.get(PRODUCT_REENTRY_GATE, "")))
    if RETROSPECTIVE_CHECK_GATE in required:
        failures.extend(
            validate_retrospective_check(
                gate_evidence.get(RETROSPECTIVE_CHECK_GATE, ""),
                allowed_skill_ids=allowed_skill_ids,
            )
        )
    if GRAPHIFY_READINESS_GATE in required:
        failures.extend(_validate_graphify_readiness(gate_evidence.get(GRAPHIFY_READINESS_GATE, "")))
    if SOURCE_DOCS_GATE in required and DOCUMENTATION_IMPACT_GATE in required:
        failures.extend(
            validate_documentation_source_to_artifact_evidence(
                gate_evidence.get(SOURCE_DOCS_GATE, ""),
                gate_evidence.get(DOCUMENTATION_IMPACT_GATE, ""),
            )
        )
    if PRD_DRAFT_GATE in required:
        failures.extend(validate_prd_draft_evidence(gate_evidence.get(PRD_DRAFT_GATE, "")))
    if PLATFORM_SELECTION_GATE in required:
        failures.extend(validate_platform_selection_evidence(gate_evidence.get(PLATFORM_SELECTION_GATE, "")))
    if REVIEW_READINESS_GATE in required:
        failures.extend(validate_review_readiness_evidence(gate_evidence.get(REVIEW_READINESS_GATE, "")))
    if TEST_GATE in required:
        failures.extend(validate_tests(gate_evidence.get(TEST_GATE, "")))
    if CYCLE_CONTRACT_GATE in required:
        failures.extend(validate_cycle_contract(gate_evidence.get(CYCLE_CONTRACT_GATE, "")))
    if BOUNDARY_PLAN_GATE in required:
        failures.extend(validate_boundary_plan(gate_evidence.get(BOUNDARY_PLAN_GATE, "")))
    if MULTI_AGENT_GATE in required:
        failures.extend(validate_multi_agent(gate_evidence.get(MULTI_AGENT_GATE, "")))
    if SIDE_EFFECT_AUDIT_GATE in required:
        failures.extend(validate_side_effect_audit(gate_evidence.get(SIDE_EFFECT_AUDIT_GATE, "")))
    if AGENTIC_RUN_STATE_GATE in required:
        failures.extend(validate_agentic_run_state(gate_evidence.get(AGENTIC_RUN_STATE_GATE, "")))
    if MULTI_AGENT_ROLES_GATE in required:
        failures.extend(validate_multi_agent_roles(gate_evidence.get(MULTI_AGENT_ROLES_GATE, "")))
    if MULTI_AGENT_WRITE_SCOPES_GATE in required:
        failures.extend(validate_multi_agent_write_scopes(gate_evidence.get(MULTI_AGENT_WRITE_SCOPES_GATE, "")))
    if MULTI_AGENT_BRIEFS_GATE in required:
        failures.extend(validate_multi_agent_briefs(gate_evidence.get(MULTI_AGENT_BRIEFS_GATE, "")))
    if MULTI_AGENT_INTEGRATION_REVIEW_GATE in required:
        failures.extend(
            validate_multi_agent_integration_review(
                gate_evidence.get(MULTI_AGENT_INTEGRATION_REVIEW_GATE, "")
            )
        )
    for gate in WORKSPACE_SCOPE_CHECKPOINT_GATES:
        if gate in gate_evidence:
            failures.extend(validate_workspace_scope_checkpoint(gate_evidence[gate]))
    return failures


def _validate_graphify_readiness(evidence: str) -> list[str]:
    lower = evidence.lower()
    ownership_anchor = (
        "runtime ownership="
        if "runtime ownership=" in lower
        else "git ownership="
        if "git ownership=" in lower
        else "runtime ownership="
    )
    required_anchors = (
        "cli=",
        "skill doc=",
        "runtime links=",
        ownership_anchor,
        "project integration=",
        "target graph=",
        "query smoke=",
    )
    missing = [anchor.rstrip("=") for anchor in required_anchors if anchor not in lower]
    if missing:
        return [
            "graphify readiness evidence must contain structured status for " + ", ".join(missing)
        ]
    invalid: list[str] = []
    for index, anchor in enumerate(required_anchors):
        start = lower.find(anchor) + len(anchor)
        later_positions = [
            lower.find(later, start)
            for later in required_anchors[index + 1:]
            if lower.find(later, start) >= 0
        ]
        finish = min(later_positions) if later_positions else len(lower)
        value = lower[start:finish].strip(" ;")
        if value != "success":
            invalid.append(anchor.rstrip("="))
    if invalid:
        return [
            "graphify readiness structured status must be exactly success for "
            + ", ".join(invalid)
        ]
    return []
