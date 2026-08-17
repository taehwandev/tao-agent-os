"""Boundary, side-effect, and run-state finish gate validators."""

from __future__ import annotations


RUN_STATE_NAMES = (
    "intake",
    "oriented",
    "scoped",
    "acting",
    "verifying",
    "reviewing",
    "done",
    "blocked",
    "retrospective",
)


# Named so the same phrases can be stated before the work as well as after a
# refusal. A wording requirement discoverable only by failing is one an agent
# pays for once per refusal, and gate-evidence wording is the largest recurring
# failure class in the lesson store.
BOUNDARY_PLAN_PHRASES = {
    "owned boundary": (
        "boundary",
        "owner",
        "owned",
        "scope",
        "same file",
        "single-file",
        "existing",
        "contract",
        "allowed import",
        "forbidden import",
        "no new package",
    ),
    "nearest verification": (
        "verification",
        "verify",
        "test",
        "check",
        "manual",
        "pytest",
        "unittest",
        "typecheck",
        "smoke",
        "validate",
    ),
    "runtime structure decision": (
        "review budget",
        "structural budget",
        "top-level owner",
        "top level owner",
        "public owner",
        "owner count",
        "file split",
        "one public owner",
        "single public owner",
        "no runtime source change",
        "no development source change",
    ),
}


def validate_boundary_plan(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_boundary = any(
        phrase in text for phrase in BOUNDARY_PLAN_PHRASES["owned boundary"]
    )
    has_verification = any(
        phrase in text for phrase in BOUNDARY_PLAN_PHRASES["nearest verification"]
    )
    has_runtime_structure_decision = any(
        phrase in text
        for phrase in BOUNDARY_PLAN_PHRASES["runtime structure decision"]
    )
    if has_boundary and has_verification and has_runtime_structure_decision:
        return []
    return [
        "boundary plan evidence must name the owned boundary/scope or contract, "
        "the nearest verification/check, and the runtime file/top-level-owner review "
        "budget or an explicit no-runtime-source-change decision before implementation"
    ]


def validate_side_effect_audit(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_audit = any(
        phrase in text
        for phrase in (
            "side-effect",
            "side effect",
            "diff",
            "audit",
            "reviewed",
            "checked",
        )
    )
    has_scope = any(
        phrase in text
        for phrase in (
            "no unexpected",
            "none",
            "unrelated",
            "generated",
            "lockfile",
            "docs",
            "public api",
            "contract",
            "auth",
            "data",
            "release",
            "external",
            "risk",
        )
    )
    if has_audit and has_scope:
        return []
    return [
        "side-effect audit evidence must state that the final diff/side effects were checked "
        "and name unexpected changes, public-contract risk, generated/lockfile churn, or that none were found"
    ]


def validate_agentic_run_state(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_state = any(state in text for state in RUN_STATE_NAMES) or any(
        phrase in text
        for phrase in (
            "run state",
            "state:",
            "state=",
            "상태",
        )
    )
    has_transition = any(
        phrase in text
        for phrase in (
            "transition",
            "next",
            "entered",
            "moved",
            "->",
            "resume",
            "restart",
            "다음",
            "전환",
            "재시작",
            "이어",
        )
    )
    has_evidence = any(
        phrase in text
        for phrase in (
            "evidence",
            "gate",
            "command",
            "check",
            "test",
            "hook",
            "diff",
            "verification",
            "증거",
            "게이트",
            "검증",
        )
    )
    has_checkpoint = any(
        phrase in text
        for phrase in (
            "checkpoint",
            "resume point",
            "recovery point",
            "next gate",
            "handoff",
            "rollback point",
            "stop condition",
            "체크포인트",
            "재개 지점",
            "중단 조건",
        )
    )
    has_blocker_status = any(
        phrase in text
        for phrase in (
            "blocker",
            "blocked",
            "no blocker",
            "no blockers",
            "not blocked",
            "unblocked",
            "fail",
            "failed",
            "실패",
            "블로커",
        )
    )
    if has_state and has_transition and has_evidence and has_checkpoint and has_blocker_status:
        return []
    return [
        "agentic run state evidence must state the current run state, "
        "the next transition or resume point, the gate/command/check evidence, "
        "the checkpoint or stop condition, and the blocker status"
    ]
