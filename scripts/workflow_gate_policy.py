"""Automatic workflow gates shared by Tao Agent OS routes."""

from __future__ import annotations

from agent_skill_state import CURRENT_TASK_REVIEW_THRESHOLD


WORK_PRODUCING_COMMANDS = {
    "build",
    "bugfix",
    "code-simplify",
    "docs",
    "feature",
    "product",
    "prd",
    "refactor",
    "release",
    "ship",
    "spec",
    "task",
    "workflow-setup",
}
# A bounded investigation is intentionally not work-producing. Keep this
# explicit so broad automatic-gate additions cannot silently turn the
# lightweight analysis route into a code/documentation/review lifecycle.
LIGHTWEIGHT_ANALYSIS_COMMANDS = {"analysis"}
AGENTIC_RUN_STATE_COMMANDS = WORK_PRODUCING_COMMANDS | {
    "multi-agent",
}
CODE_WORK_COMMANDS = {
    "build",
    "bugfix",
    "code-simplify",
    "feature",
    "product",
    "refactor",
    "task",
    "workflow-setup",
}
ALIGNMENT_BRIEF_COMMANDS = {
    "ambiguity",
    "build",
    "bugfix",
    "code-simplify",
    "docs",
    "feature",
    "multi-agent",
    "plan",
    "planning",
    "prd",
    "product",
    "refactor",
    "release",
    "ship",
    "spec",
    "task",
    "test",
    "triage",
    "webperf",
    "workflow-setup",
}

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
WORK_SURFACE_RESOLUTION_GATE = "work surface resolution"
PRODUCT_REENTRY_GATE = "product route re-entry"
RETROSPECTIVE_CHECK_GATE = "retrospective check"
SKILL_FEEDBACK_HOOK = "skill-feedback"
SKILL_DRAFT_HOOK = "skill-draft"
SKILL_CURATE_HOOK = "skill-curate"
SKILL_REVIEW_HOOK = "skill-review"
SKILL_MAINTENANCE_HOOK = "skill-maintenance"

# Triage/plan routes classify and recommend but do not run the product PRD/ARD
# gates. When their output expands into an implementation roadmap, nothing used
# to force product-route re-entry, so PRD coverage was silently skipped. This
# gate closes that gap: every triage/plan finish must declare product coverage.
PRODUCT_REENTRY_COMMANDS = {
    "triage",
    "plan",
    "planning",
}

SOURCE_DOCS_COMMANDS = WORK_PRODUCING_COMMANDS | {
    "ambiguity",
    "commit",
    "docs-review",
    "git_commit",
    "multi-agent",
    "plan",
    "planning",
    "retrospective",
    "review",
    "test",
    "triage",
    "webperf",
}

# Every user-visible workflow performs one lightweight retrospective check.
# The check itself is required; observation storage and later skill maintenance
# remain a non-blocking side channel.
RETROSPECTIVE_CHECK_COMMANDS = SOURCE_DOCS_COMMANDS | LIGHTWEIGHT_ANALYSIS_COMMANDS


def automatic_gates(command: str) -> list[str]:
    gates: list[str] = []
    if command in CODE_WORK_COMMANDS:
        gates.append(WORK_SURFACE_RESOLUTION_GATE)
    if command in SOURCE_DOCS_COMMANDS:
        gates.append(SOURCE_DOCS_GATE)
    if command in WORK_PRODUCING_COMMANDS:
        gates.extend([AMBIGUITY_GATE, DOCUMENTATION_IMPACT_GATE])
    if command in ALIGNMENT_BRIEF_COMMANDS:
        gates.append(ALIGNMENT_BRIEF_GATE)
    if command in AGENTIC_RUN_STATE_COMMANDS:
        gates.append(AGENTIC_RUN_STATE_GATE)
    if command in WORK_PRODUCING_COMMANDS:
        gates.extend([CYCLE_CONTRACT_GATE, DOCUMENTATION_GATE])
    if command in PRODUCT_REENTRY_COMMANDS:
        gates.append(PRODUCT_REENTRY_GATE)
    if command in CODE_WORK_COMMANDS:
        gates.extend(
            [TEST_GATE, BOUNDARY_PLAN_GATE, MULTI_AGENT_GATE, SIDE_EFFECT_AUDIT_GATE]
        )
    if command in RETROSPECTIVE_CHECK_COMMANDS:
        gates.append(RETROSPECTIVE_CHECK_GATE)
    return gates


def automatic_docs(command: str) -> list[str]:
    docs: list[str] = []
    gates = set(automatic_gates(command))
    if AMBIGUITY_GATE in gates:
        docs.append("workflows/skills/ambiguity-gate/SKILL.md")
    if ALIGNMENT_BRIEF_GATE in gates:
        docs.extend(
            [
                "common/skills/task-intake-effort-routing/SKILL.md",
                "common/skills/product-spec-to-implementation/SKILL.md",
            ]
        )
        if command in {"prd", "product", "spec"}:
            docs.append("workflows/skills/prd-creation/SKILL.md")
    if DOCUMENTATION_GATE in gates or DOCUMENTATION_IMPACT_GATE in gates:
        docs.append("workflows/skills/documentation-update/SKILL.md")
    if CYCLE_CONTRACT_GATE in gates:
        docs.append("workflows/skills/cycle-contract/SKILL.md")
    if RETROSPECTIVE_CHECK_GATE in gates:
        docs.append("workflows/skills/retrospective-learning/SKILL.md")
    if PRODUCT_REENTRY_GATE in gates:
        docs.append("common/skills/product-spec-to-implementation/SKILL.md")
    if SOURCE_DOCS_GATE in gates:
        docs.extend(
            [
                "common/skills/product-spec-to-implementation/SKILL.md",
                "common/skills/source-driven-development/SKILL.md",
            ]
        )
    if WORK_SURFACE_RESOLUTION_GATE in gates:
        docs.append("common/skills/source-driven-development/SKILL.md")
    if TEST_GATE in gates:
        docs.extend(
            [
                "common/skills/testing/SKILL.md",
                "common/skills/scenario-driven-testing/SKILL.md",
                "common/skills/verification-policy/SKILL.md",
            ]
        )
    if BOUNDARY_PLAN_GATE in gates:
        docs.append("common/skills/code-structure-ownership/SKILL.md")
    if MULTI_AGENT_GATE in gates:
        docs.append("workflows/skills/multi-agent-collaboration/SKILL.md")
    if SIDE_EFFECT_AUDIT_GATE in gates:
        docs.append("workflows/skills/development-cycle/SKILL.md")
    if AGENTIC_RUN_STATE_GATE in gates:
        docs.extend(
            [
                "workflows/skills/agent-task-lifecycle/SKILL.md",
                "workflows/skills/scripted-agent-workflow/SKILL.md",
            ]
        )
    return docs


def add_automatic_gates(command: str, gates: list[str]) -> list[str]:
    result = list(gates)
    before_implementation = (
        "act",
        "implementation",
        "code work",
        "fix",
        "small refactor",
        "install or repair",
    )
    for gate in automatic_gates(command):
        if gate in result:
            continue
        if gate == SOURCE_DOCS_GATE:
            _insert_after_any(
                result,
                gate,
                anchors=(WORK_SURFACE_RESOLUTION_GATE, "orient"),
            )
        elif gate == WORK_SURFACE_RESOLUTION_GATE:
            _insert_after_any(result, gate, anchors=("orient",))
        elif gate == AMBIGUITY_GATE:
            _insert_after_any(
                result,
                gate,
                anchors=(SOURCE_DOCS_GATE, "orient", "PRD/ARD applicability", "reproduce"),
            )
        elif gate == DOCUMENTATION_IMPACT_GATE:
            _insert_after_any(
                result,
                gate,
                anchors=(SOURCE_DOCS_GATE, "orient"),
            )
        elif gate == ALIGNMENT_BRIEF_GATE:
            _insert_before_any(
                result,
                gate,
                anchors=(
                    "PRD/ARD applicability",
                    "PRD",
                    "PRD draft",
                    "ARD",
                    "acceptance criteria",
                    "scope",
                    "act",
                    "implementation",
                    "code work",
                    "fix",
                    "baseline",
                    "measure",
                    "test scope",
                    "run checks",
                    "simplification plan",
                    "small refactor",
                    "edit",
                    "install or repair",
                    "sources",
                    "options",
                    "recommendation",
                    "roles",
                    "write scopes",
                    "agent briefs",
                    "package",
                    "config",
                    "grill-me if needed",
                    "question drill if needed",
                    "route recommendation",
                    "ask blockers",
                    "record assumptions",
                ),
            )
        elif gate == AGENTIC_RUN_STATE_GATE:
            _insert_after_any(
                result,
                gate,
                anchors=(ALIGNMENT_BRIEF_GATE, AMBIGUITY_GATE, SOURCE_DOCS_GATE, "orient"),
            )
        elif gate == CYCLE_CONTRACT_GATE:
            _insert_before_any(result, gate, anchors=before_implementation)
        elif gate == BOUNDARY_PLAN_GATE:
            _insert_before_any(result, gate, anchors=before_implementation)
        elif gate == MULTI_AGENT_GATE:
            _insert_before_any(result, gate, anchors=before_implementation)
        elif gate == PRODUCT_REENTRY_GATE:
            _insert_before_any(
                result,
                gate,
                anchors=(
                    "route recommendation",
                    "recommendation",
                    "grill-me if needed",
                    "handoff",
                    "report",
                ),
            )
        elif gate == SIDE_EFFECT_AUDIT_GATE:
            _insert_before_any(result, gate, anchors=("verify", "verification", "handoff", "commit readiness"))
        elif gate in {DOCUMENTATION_GATE, TEST_GATE}:
            _insert_before_any(result, gate, anchors=("verify", "verification", "handoff", "commit readiness"))
        elif gate == RETROSPECTIVE_CHECK_GATE:
            _insert_before_any(
                result,
                gate,
                anchors=("handoff", "report", "commit readiness"),
            )
        else:
            result.append(gate)
    return result


def _insert_after_any(gates: list[str], gate: str, anchors: tuple[str, ...]) -> None:
    for anchor in anchors:
        if anchor in gates:
            gates.insert(gates.index(anchor) + 1, gate)
            return
    gates.insert(0, gate)


def _insert_before_any(gates: list[str], gate: str, anchors: tuple[str, ...]) -> None:
    for anchor in anchors:
        if anchor in gates:
            gates.insert(gates.index(anchor), gate)
            return
    gates.append(gate)


def skill_feedback_policy(command: str) -> dict[str, object]:
    """Describe same-closeout skill-document maintenance."""

    enabled = command in RETROSPECTIVE_CHECK_COMMANDS
    return {
        "enabled": enabled,
        "mode": "observe_draft_review_stage_maintain_same_closeout",
        "trigger": "after_task_verification_before_finish",
        "evaluation_required": enabled,
        "evaluation_gate": RETROSPECTIVE_CHECK_GATE if enabled else "",
        "blocking": True,
        "blocking_scope": "reusable_gap_same_closeout",
        "threshold_followup_required": enabled,
        "record_only_when": "actually_used_skill_and_structured_observation",
        "candidate_threshold": CURRENT_TASK_REVIEW_THRESHOLD,
        # The observing run is the only participant holding the context that
        # explains the gap. Without a draft, a later reviewer sees only slugs and
        # counts and can do nothing but return no_change.
        "draft": "observing_run_authors_bounded_proposal_no_authority",
        "draft_required_for_reusable_gap": enabled,
        "curation": "deterministic_current_occurrence_queue",
        "review": "required_for_current_occurrence_no_change_or_staged_patch",
        "write_policy": "draft_required_before_staged_patch",
        "maintenance": "explicit_verified_terminal_same_closeout",
        "review_policy": "single_agent_default_optional_multi_agent_for_high_impact",
    }
