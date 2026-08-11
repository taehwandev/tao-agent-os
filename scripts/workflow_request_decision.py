"""Private route-shape decisions for request intake classification."""

from __future__ import annotations

from workflow_common import ANSWER_ONLY_CLARITY


def classification_decision(flags: dict[str, object]) -> tuple[str, bool, str, str]:
    """Return the advisory route shape for already-computed request flags."""

    decision = _intake_gate_decision(flags)
    if decision is None:
        decision = _explicit_action_decision(flags)
    if decision is None:
        decision = _scope_fallback_decision(flags)
    return decision


def _intake_gate_decision(
    flags: dict[str, object],
) -> tuple[str, bool, str, str] | None:
    has_broad = bool(flags["has_broad"])
    has_exact = bool(flags["has_exact"])
    has_scoped = bool(flags["has_scoped"])
    has_risky = bool(flags["has_risky"])

    if (
        flags["has_direct_question"]
        and not flags["asks_agent_action"]
        and not flags["has_user_correction"]
    ):
        flags["clarity"] = ANSWER_ONLY_CLARITY
        flags["effort"] = "standard" if has_broad else "quick"
        route = "product" if has_broad else "none"
        reason = _direct_question_reason(has_broad)
        return route, False, "answer_first", reason
    if has_risky and not has_broad and not (has_exact or has_scoped):
        flags["clarity"] = "risky-unclear"
        flags["effort"] = "deep"
        return (
            "ambiguity",
            True,
            "clarify_first",
            "Risk-sensitive terms appear without an exact implementation target.",
        )
    if flags["asks_drill"]:
        flags["clarity"] = "vague-action"
        flags["effort"] = "deep" if has_broad or has_risky else "standard"
        return (
            "triage",
            True,
            "clarify_first",
            "The request explicitly asks for the Grill-Me protocol before work.",
        )
    return None


def _explicit_action_decision(
    flags: dict[str, object],
) -> tuple[str, bool, str, str] | None:
    has_risky = bool(flags["has_risky"])
    review_only_request = flags["has_review_action"] and not any(
        (
            flags["has_commit_action"],
            flags["has_release_action"],
            flags["has_refactor_action"],
            flags["has_test_action"],
            flags["has_workflow_setup_action"],
            flags["has_ui_feature_action"],
        )
    )
    if flags["has_user_correction"]:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "retrospective",
            False,
            "work",
            "The user explicitly reports that a previously completed result was wrong "
            "and asks to correct that same result; repair the failed closeout before "
            "resuming the original work.",
        )
    if review_only_request:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "review",
            False,
            "work",
            "The request asks only to review inspectable changes; domain risk nouns do not turn a read-only review into product work.",
        )
    if (
        flags["has_commit_action"]
        and flags["commit_release_substep"]
        and not flags["commit_risk_blocked"]
    ):
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "quick"
        return (
            "commit",
            False,
            "work",
            "The request asks for local commit preparation or commit creation; use the lightweight commit route.",
        )
    if (
        flags["has_release_action"]
        and flags["has_release_scope"]
        and not flags["release_risk_blocked"]
    ):
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "deep"
        return (
            "release",
            False,
            "work",
            "The request names enough release context to run the release readiness route without Grill-Me.",
        )
    if flags["has_workflow_setup_action"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "workflow-setup",
            False,
            "work",
            "The request changes document routing, natural-language discovery, or hook enforcement behavior.",
        )
    if flags["has_ui_feature_action"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "feature",
            False,
            "work",
            "The request describes a scoped UI or screen feature to implement.",
        )
    return None


def _scope_fallback_decision(flags: dict[str, object]) -> tuple[str, bool, str, str]:
    has_risky = bool(flags["has_risky"])

    if flags["has_broad"] and not flags["has_exact"]:
        flags["clarity"] = "broad-product"
        flags["effort"] = "deep"
        return (
            "product",
            True,
            "clarify_first",
            "Broad product or architecture work needs Grill-Me blocker-question discovery before PRD, ARD, or implementation unless existing acceptance criteria are already known.",
        )
    if flags["has_refactor_action"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "code-simplify",
            False,
            "work",
            "The request asks for behavior-preserving code cleanup or simplification.",
        )
    if flags["has_test_action"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "quick"
        return (
            "test",
            False,
            "work",
            "The request asks for verification or test execution.",
        )
    if flags["has_exact"]:
        flags["clarity"] = "clear-exact"
        flags["effort"] = "quick"
        return (
            "task",
            False,
            "work",
            "The request names an exact file, symbol, command, or error signal.",
        )
    if flags["has_scoped"]:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "feature",
            False,
            "work",
            "The request names a scoped UI, code, or feature owner.",
        )
    if flags["has_inspection"] and not has_risky and not flags["inspection_lacks_target"]:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "task",
            False,
            "work",
            "The request asks for inspection, review, status, or documentation summary work with an inspectable target.",
        )
    if flags["has_follow_up_approval"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return (
            "task",
            False,
            "work",
            "The request is an explicit approval to continue the already-confirmed scope from the preceding discussion.",
        )
    if (
        flags["asks_drill"]
        or flags["has_vague"]
        or flags["short_without_target"]
        or flags["underspecified_action"]
    ):
        flags["clarity"] = "vague-action"
        flags["effort"] = "standard"
        return (
            "triage",
            True,
            "clarify_first",
            "The request asks for action but lacks a precise target, inspection target, or acceptance criteria.",
        )
    flags["clarity"] = "clear-scoped"
    flags["effort"] = "standard"
    return (
        "task",
        False,
        "work",
        "No high-risk ambiguity was detected, but local context is still needed.",
    )


def _direct_question_reason(has_broad: bool) -> str:
    if has_broad:
        return (
            "The request asks how to approach app/product/feature work. Answer first, "
            "but include the PRD -> ARD -> implementation gate before lower-level steps."
        )
    return "The request is a direct question, so answer it before starting any workflow or edit."
