"""Core finish gate evidence validators."""

from __future__ import annotations


def validate_ambiguity(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    resolved = (
        "no blocker" in text
        or "no blocking" in text
        or "blockers resolved" in text
        or "asked" in text
        or "clarified" in text
        or "assumption" in text
        or "not ambiguous" in text
    )
    if resolved:
        return []
    return [
        "ambiguity check evidence must state no blockers, blockers resolved, "
        "questions asked, clarified decisions, or explicit safe assumptions"
    ]


def validate_alignment_brief(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_shared = any(
        phrase in text
        for phrase in (
            "same understanding",
            "shared understanding",
            "aligned",
            "explicit goal",
            "confirmed fact",
            "같은 이해",
            "같이 이해",
            "명시된 목표",
            "확인된 사실",
        )
    )
    has_difference = any(
        phrase in text
        for phrase in (
            "may differ",
            "different understanding",
            "could differ",
            "possible difference",
            "possible differences",
            "possible mismatch",
            "uncertain scope",
            "다를 수",
            "다른 이해",
            "불확실한 범위",
        )
    )
    has_assumption = any(
        phrase in text
        for phrase in (
            "assumption",
            "unknown",
            "unsupported",
            "no evidence",
            "default",
            "blocker question",
            "minimal question",
            "가정",
            "근거 없음",
            "미확인",
            "질문",
        )
    )
    has_user_visible_checkpoint = any(
        phrase in text
        for phrase in (
            "user-visible",
            "told the user",
            "told user",
            "presented to the user",
            "presented to user",
            "reported to the user",
            "reported to user",
            "asked the user",
            "asked user",
            "choice question",
            "choices presented",
            "presented choices",
            "confirmed with user",
            "shared with user",
            "sent to user",
            "before edits",
            "before editing",
            "사용자에게",
            "유저에게",
            "전달",
            "물어",
            "확인받",
            "수정 전",
            "작업 전",
        )
    )
    if has_shared and has_difference and has_assumption and has_user_visible_checkpoint:
        return []
    # Name the parts that are actually absent. A refusal that only restates the
    # full requirement makes the agent re-guess which clause it missed.
    missing = [
        label
        for label, present in (
            ("shared understanding", has_shared),
            ("possible differences", has_difference),
            ("unsupported assumptions/unknowns or minimal blocker questions", has_assumption),
            ("user-visible checkpoint", has_user_visible_checkpoint),
        )
        if not present
    ]
    return [
        "alignment brief evidence must state shared understanding, possible differences, "
        "unsupported assumptions/unknowns or minimal blocker questions, and the user-visible "
        "checkpoint before requirements analysis or modification work. Missing: "
        + "; ".join(missing)
    ]
