"""Conservative request intake and non-authoritative concern inference."""

from __future__ import annotations

import re
from typing import Optional

from workflow_catalog import REQUEST_CONCERN_HINTS
from workflow_common import ANSWER_ONLY_CLARITY, QUESTION_ROUTE_COMMANDS, unique
from workflow_request_decision import classification_decision
from workflow_request_patterns import (
    BROAD_PATTERNS,
    COMMIT_ACTION_PATTERNS,
    COMMIT_BLOCKING_RISK_PATTERNS,
    COMMIT_NEGATION_PATTERNS,
    COMMIT_RELEASE_SUBSTEP_PATTERNS,
    COMPLETION_FAILURE_PATTERNS,
    CORRECTION_ACTION_PATTERNS,
    CORRECTION_WORD_SENSE_QUESTION_PATTERNS,
    DIRECT_QUESTION_PATTERNS,
    EXACT_PATTERNS,
    FOLLOW_UP_APPROVAL_PATTERNS,
    GRILL_ME_REQUEST_PATTERNS,
    IMPERATIVE_CORRECTION_ACTION_PATTERNS,
    INSPECTION_PATTERNS,
    MUTATION_ACTION_NEGATION_PATTERNS,
    PRIOR_COMPLETION_REFERENCE_PATTERNS,
    QUESTION_ACTION_PATTERNS,
    REFACTOR_ACTION_PATTERNS,
    RELEASE_ACTION_PATTERNS,
    RELEASE_BLOCKING_RISK_PATTERNS,
    RELEASE_SCOPE_SIGNAL_PATTERNS,
    REVIEW_ACTION_PATTERNS,
    RISKY_PATTERNS,
    SCOPED_PATTERNS,
    TEST_ACTION_PATTERNS,
    UI_FEATURE_ACTION_PATTERNS,
    VAGUE_PATTERNS,
    WORKFLOW_SETUP_ACTION_PATTERNS,
)


MAX_CONTINUATION_SCOPE_CHARS = 500
MODEL_TIER_BY_EFFORT = {
    "quick": "fast",
    "standard": "balanced",
    "deep": "frontier",
    "specialist": "specialist",
}
CODEX_MODEL_BY_TIER = {
    "fast": "gpt-5.6-luna",
    "balanced": "gpt-5.6-terra",
    "frontier": "gpt-5.6-sol",
    "specialist": "gpt-5.6-sol",
}
CODE_AUTHORING_REQUEST_PATTERNS = (
    r"\b(?:add|create|write|implement|fix|modify|edit|refactor)\b",
    r"(?:추가|작성|구현|수정|고쳐|만들)",
)

EXPLICIT_CONCERN_EXCLUSION_PATTERNS = {
    "graphify": (
        r"\b(?:do not|don't|must not|should not|never)\s+"
        r"(?:(?:run|use|invoke|call|execute|include|install|enable|build|update|query)\s+|"
        r"rely\s+on\s+)graphify\b",
        r"\bwithout\s+(?:(?:running|using|invoking|calling|executing|including|installing|"
        r"relying\s+on)\s+)?graphify\b",
        # An opt-out is as often a bare removal verb as a negated action verb:
        # "Skip Graphify for this task" carries no do-not for the pattern above
        # to attach to.
        r"\b(?:skip|omit|exclude|disable|bypass|drop|leave\s+out)\s+"
        r"(?:(?:running|using|invoking|calling|executing|installing|the)\s+)?"
        r"graphify\b",
        r"\bleave\s+graphify\s+out\b",
        r"\bgraphify\b.{0,40}\b(?:excluded?|disabled?|skipped?|omitted?|"
        r"bypassed?|dropped?|left\s+out|out\s+of\s+scope)\b",
        r"\bgraphify\b.{0,40}\b(?:must not|should not|do not|don't)\s+"
        r"(?:be\s+)?(?:run|used|invoked|called|included|installed|enabled)\b",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프).{0,40}"
        r"(?:실행|사용|설치)(?:은|는|을|를)?\s*(?:제외|금지|하지\s*마|하지\s*않)",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프).{0,40}"
        r"(?:돌리면\s*안|돌리지\s*마|안\s*돌)",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프)"
        r"(?:\s*(?:가|이|를|을))?\s*없이",
        # Korean drops the verb freely: "Graphify 는 하지 마" carries no
        # 실행/사용/설치 for the verb-anchored patterns above to attach to, so a
        # bare topic-marked negation or removal verb ("그래피는 빼줘") has to be
        # recognised on its own. The verb must sit right after the concern word
        # with only a case marker between: 그래프 is an ordinary word, so a
        # wider gap would start excluding sentences that merely mention a chart.
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프)"
        r"(?:\s*(?:는|은|를|을|도|만))?\s*"
        r"(?:하지\s*마|하지\s*않|안\s*함|금지|제외|생략|건너뛰|스킵|무시|빼)",
    ),
}
# Checked before the exclusion patterns above and, when it matches, cancels
# them. "Do not skip graphify" / "Graphify 는 제외하지 마" are negators applied
# to an opt-out verb, so they ask for the exact opposite of the exclusion they
# textually contain. Suppressing the exclusion in one place keeps each pattern
# above readable; the alternative is a negative lookbehind for every negator on
# every exclusion pattern, and Python needs those fixed-width.
EXPLICIT_CONCERN_EXCLUSION_NEGATION_PATTERNS = {
    "graphify": (
        r"\b(?:do not|don'?t|must not|mustn'?t|should not|shouldn'?t|never|"
        r"no need to)\s+(?:\w+\s+){0,2}?"
        r"(?:skip|omit|exclude|disable|bypass|drop|leave\s+out)\b",
        # Korean puts the negator after the verb. Anchored to opt-out verb
        # stems only, so a plain "Graphify 는 하지 마" stays an exclusion.
        r"(?:제외|생략|무시|배제|스킵)하지\s*(?:마|말|않)",
        r"(?:빼|건너뛰)지\s*(?:마|말|않)",
    ),
}


# Korean attaches a particle straight onto a Latin keyword — "Graphify는",
# "SwiftUI에서" — and Python's \b sees no boundary there because Hangul is a
# word character too. That silently blinded every \b-anchored hint and
# exclusion to the ordinary Korean spelling: "Graphify는 제외하지 마" inferred
# no concern at all. Splitting that one junction before matching repairs all of
# them at once instead of loosening 228 individual patterns, and it cannot
# create a substring match: the space only ever lands between a complete
# Latin/digit run and an attached Hangul syllable, never inside an identifier
# like "graphifyer" or a path fragment.
_LATIN_HANGUL_JUNCTION = re.compile(r"(?<=[A-Za-z0-9])(?=[가-힣ㄱ-ㆎ])")
_UNRESOLVED_PATTERNS = (
    r"\b(?:vague[-_ ]action|broad[-_ ]product|risky[-_ ]unclear)\b",
    r"\b(?:clarify[-_ ]first|ambiguous|unclear|unresolved)\b",
    r"\b(?:open|pending)\s+(?:questions?|blockers?|clarification)\b",
    r"\bnot\s+(?:yet\s+)?(?:answered|clarified|resolved)\b",
    r"\b(?:grill[-_ ]?me|question[-_ ]drill)\s*[:=]?\s*true\b",
    r"(?:모호|불명확|불확실|미정|미해결|질문 필요|확인 필요|블로커)",
)
_RESOLVED_PATTERNS = (
    r"\bclear[-_ ]exact\b",
    r"\bclear[-_ ]scoped\b",
    r"\b(?:ambiguity|unknowns?|blockers?)\s+resolved\b",
    r"\bresolved\s+blockers?\b",
    r"\bno\s+(?:open\s+)?(?:questions?|blockers?)\b",
    r"\banswered\b.*\bseparate\s+(?:actionable|action|request)\b",
    r"(?:명확한?\s*(?:범위|스코프)|모호성\s*해결|블로커\s*해결)",
)


def infer_concerns_from_request(text: str) -> list[str]:
    normalized = _match_text(" ".join(text.strip().split()))
    if not normalized:
        return []
    inferred: list[str] = []
    for concern, patterns in REQUEST_CONCERN_HINTS:
        if _matches(patterns, normalized, re.IGNORECASE) and not _is_opted_out(
            concern, normalized
        ):
            inferred.append(concern)
    return unique(inferred)


def _match_text(text: str) -> str:
    ascii_apostrophes = text.replace("’", "'").replace("‘", "'")
    return _LATIN_HANGUL_JUNCTION.sub(" ", ascii_apostrophes)


def _is_opted_out(concern: str, normalized: str) -> bool:
    if not _matches(
        EXPLICIT_CONCERN_EXCLUSION_PATTERNS.get(concern, ()),
        normalized,
        re.IGNORECASE,
    ):
        return False
    return not _matches(
        EXPLICIT_CONCERN_EXCLUSION_NEGATION_PATTERNS.get(concern, ()),
        normalized,
        re.IGNORECASE,
    )


def classify_request(text: str, *, continuation_scope: str = "") -> dict[str, object]:
    normalized = " ".join(text.strip().split())
    lowered = normalized.lower()
    _normalize_continuation_scope(continuation_scope)
    direct_question = _matches(DIRECT_QUESTION_PATTERNS, lowered)
    imperative_correction = _matches(
        IMPERATIVE_CORRECTION_ACTION_PATTERNS, lowered, re.IGNORECASE
    )
    word_sense_question = direct_question and _matches(
        CORRECTION_WORD_SENSE_QUESTION_PATTERNS, lowered, re.IGNORECASE
    )
    asks_action = _matches(QUESTION_ACTION_PATTERNS, lowered) or (
        imperative_correction and not word_sense_question
    )
    answer_only = direct_question and not asks_action
    effort = "quick" if answer_only else "standard"
    model_tier = MODEL_TIER_BY_EFFORT[effort]
    if requires_code_authoring(normalized) and model_tier == "fast":
        model_tier = "balanced"
    shape, shape_mode = _route_shape(answer_only, normalized, lowered)
    return {
        "request": normalized,
        "clarity": ANSWER_ONLY_CLARITY if answer_only else "vague-action",
        "effort": effort,
        "model_tier": model_tier,
        "model_selection": _model_selection(model_tier, effort),
        "recommended_route": "none" if answer_only else "triage",
        "route_shape": shape,
        "shape_response_mode": shape_mode,
        "grill_me": not answer_only,
        "question_drill": not answer_only,
        "response_mode": "answer_first" if answer_only else "clarify_first",
        "continuation_scope_used": False,
        "reason": (
            "The request is a direct question, so answer it before starting work."
            if answer_only
            else "Natural-language intake cannot authorize work; supply a current, session-bound intent envelope."
        ),
        "notes": [
            "Answer direct user questions before routing or editing.",
            "Use triage without an intent envelope.",
            "Use repo-local instructions before editing.",
        ],
    }


def _route_shape(answer_only: bool, normalized: str, lowered: str) -> tuple[str, str]:
    """The route this prompt is *shaped* like. Never an authorization.

    ``recommended_route`` deliberately stays `triage`: natural-language intake
    must not select a work route, because deriving work authority from request
    words is exactly what the intent envelope replaced. This is a separate,
    advisory key, so reading it can never be mistaken for intake having decided.

    It exists for the one caller that has no envelope yet and cannot get one --
    the prompt hook. Routing every prompt to `triage` asked a deploy for test
    and implementation evidence while nobody asked for smoke or rollback. The
    hook may pick a manifest by shape; the work route it leads to still refuses
    without an envelope.

    A direct question is answered rather than routed, and any failure falls back
    to `triage`: intake must never be the reason a session cannot start.
    """

    if answer_only:
        return "none", "answer_first"
    try:
        flags = _request_flags(normalized, lowered)
        decided, _drill, mode, _reason = classification_decision(flags)
    except Exception:  # pragma: no cover - a shortlist must never block intake
        return "triage", "clarify_first"
    return (decided or "triage"), (mode or "clarify_first")


def _normalize_continuation_scope(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if "\x00" in normalized:
        raise ValueError("continuation scope cannot contain NUL bytes")
    if len(normalized) > MAX_CONTINUATION_SCOPE_CHARS:
        raise ValueError("continuation scope exceeds the 500-character bounded summary limit")
    return normalized


def _model_selection(model_tier: str, effort: str) -> dict[str, object]:
    return {
        "tier": model_tier,
        "codex": CODEX_MODEL_BY_TIER[model_tier],
        "switching_boundary": "task-or-agent-boundary",
        "runtime_mapping": "codex-only-or-runtime-equivalent",
        "fallback": "keep-current-model-and-apply-effort-profile",
        "reason": f"effort={effort} maps to model_tier={model_tier}",
    }


def requires_code_authoring(request: str) -> bool:
    return _matches(CODE_AUTHORING_REQUEST_PATTERNS, request.lower())


def print_classification(result: dict[str, object]) -> None:
    print("# Tao Agent OS Request Classification\n")
    print(f"Clarity: `{result['clarity']}`")
    print(f"Effort: `{result['effort']}`")
    print(f"Recommended route: `{result['recommended_route']}`")
    print(f"Grill-Me protocol: `{str(result['grill_me']).lower()}`")
    print(f"Response mode: `{result['response_mode']}`\n")
    print(f"Reason: {result['reason']}")


def route_block_reason(
    command: str, classification: Optional[dict[str, object]]
) -> Optional[str]:
    if not classification:
        return None
    if classification.get("clarity") == ANSWER_ONLY_CLARITY:
        return "The current request is a direct question. Answer it before starting a workflow route or editing files."
    response_mode = classification.get("response_mode")
    if response_mode and response_mode != "work" and command not in QUESTION_ROUTE_COMMANDS:
        return (
            f"Route `{command}` requires a current, session-bound intent envelope. "
            "Use `triage` or `ambiguity` without one; natural-language text cannot authorize work."
        )
    return None


def classified_route_block_reason(command: str, evidence: str) -> Optional[str]:
    if command in QUESTION_ROUTE_COMMANDS or classification_evidence_allows_work(evidence):
        return None
    return (
        f"The prior request classification evidence does not prove resolved scope before route `{command}`. "
        "Use `triage` or `ambiguity`; classification evidence never replaces an intent envelope."
    )


def classification_evidence_blocks_work(evidence: str) -> bool:
    normalized = " ".join(evidence.strip().lower().split())
    return not normalized or _matches(_UNRESOLVED_PATTERNS, normalized) or not _matches(
        _RESOLVED_PATTERNS, normalized
    )


def classification_evidence_allows_command_work(command: str, evidence: str) -> bool:
    del command
    return classification_evidence_allows_work(evidence)


def classification_evidence_allows_work(evidence: str) -> bool:
    return not classification_evidence_blocks_work(evidence)


def classification_evidence_requires_clarification(evidence: str) -> bool:
    normalized = " ".join(evidence.strip().lower().split())
    return bool(normalized and _matches(_UNRESOLVED_PATTERNS, normalized))


def _matches(patterns: object, text: str, flags: int = 0) -> bool:
    return any(re.search(pattern, text, flags) for pattern in patterns)


def _request_flags(normalized: str, lowered: str) -> dict[str, object]:
    has_exact = _matches(EXACT_PATTERNS, normalized, re.IGNORECASE)
    has_scoped = _matches(SCOPED_PATTERNS, normalized)
    has_broad = _matches(BROAD_PATTERNS, lowered)
    has_risky = _matches(RISKY_PATTERNS, lowered)
    has_vague = _matches(VAGUE_PATTERNS, lowered)
    has_inspection = _matches(INSPECTION_PATTERNS, lowered)
    has_refactor_action = _matches(REFACTOR_ACTION_PATTERNS, lowered)
    has_review_action = _matches(REVIEW_ACTION_PATTERNS, lowered)
    has_test_action = _matches(TEST_ACTION_PATTERNS, lowered)
    has_workflow_setup_action = _matches(WORKFLOW_SETUP_ACTION_PATTERNS, lowered)
    has_ui_feature_action = _matches(UI_FEATURE_ACTION_PATTERNS, lowered)
    has_commit_action = _has_commit_action(normalized)
    has_release_action = _has_release_action(normalized)
    release_scope_signal_count = _release_scope_signal_count(normalized)
    has_release_scope = release_scope_signal_count >= 2
    commit_risk_blocked = _commit_risk_blocks(lowered)
    release_risk_blocked = _release_risk_blocks(lowered)
    has_follow_up_approval = _matches(
        FOLLOW_UP_APPROVAL_PATTERNS,
        lowered,
        re.IGNORECASE,
    )
    commit_release_substep = has_commit_action and (
        not has_release_action or _matches(COMMIT_RELEASE_SUBSTEP_PATTERNS, normalized, re.IGNORECASE)
    )
    inspection_lacks_target = has_inspection and _inspection_lacks_target(lowered)
    has_direct_question = _matches(DIRECT_QUESTION_PATTERNS, lowered)
    asks_agent_action = _matches(QUESTION_ACTION_PATTERNS, lowered) or _matches(
        IMPERATIVE_CORRECTION_ACTION_PATTERNS,
        lowered,
        re.IGNORECASE,
    )
    short_without_target = len(normalized.split()) <= 8 and not (has_exact or has_scoped)
    asks_drill = _matches(GRILL_ME_REQUEST_PATTERNS, lowered)
    has_user_correction = _has_user_confirmed_correction(lowered)
    underspecified_action = (
        asks_agent_action
        and not (has_exact or has_scoped or has_inspection)
        and not (has_direct_question and not asks_agent_action)
    )
    return {
        "normalized": normalized,
        "lowered": lowered,
        "has_exact": has_exact,
        "has_scoped": has_scoped,
        "has_broad": has_broad,
        "has_risky": has_risky,
        "has_vague": has_vague,
        "has_inspection": has_inspection,
        "has_refactor_action": has_refactor_action,
        "has_review_action": has_review_action,
        "has_test_action": has_test_action,
        "has_workflow_setup_action": has_workflow_setup_action,
        "has_ui_feature_action": has_ui_feature_action,
        "has_commit_action": has_commit_action,
        "has_release_action": has_release_action,
        "has_release_scope": has_release_scope,
        "commit_risk_blocked": commit_risk_blocked,
        "release_risk_blocked": release_risk_blocked,
        "has_follow_up_approval": has_follow_up_approval,
        "release_scope_signal_count": release_scope_signal_count,
        "commit_release_substep": commit_release_substep,
        "inspection_lacks_target": inspection_lacks_target,
        "has_direct_question": has_direct_question,
        "asks_agent_action": asks_agent_action,
        "short_without_target": short_without_target,
        "asks_drill": asks_drill,
        "has_user_correction": has_user_correction,
        "underspecified_action": underspecified_action,
    }


def _inspection_lacks_target(lowered: str) -> bool:
    compact = lowered.strip(" .,!?:;")
    if not compact:
        return False
    targetless_patterns = (
        r"^(?:please\s+)?(?:check|review|inspect|verify|status|summarize|report)(?:\s+(?:it|this|that|please))?$",
        r"^(?:can you|could you|would you)\s+(?:check|review|inspect|verify|summarize|report)(?:\s+(?:it|this|that))?$",
        r"^(?:이거|그거|저거)?\s*(?:확인|체크|검토|점검|상태|파악|정리)\s*(?:해줘|해주세요|해줄래|좀)?$",
    )
    return _matches(targetless_patterns, compact)


def _has_commit_action(text: str) -> bool:
    if not _matches(COMMIT_ACTION_PATTERNS, text, re.IGNORECASE):
        return False
    # "do not commit", "commit is only a term", "before committing" all
    # match COMMIT_ACTION_PATTERNS' bare \bcommit\b, but none of them are a
    # request or approval to actually commit.
    return not _matches(
        COMMIT_NEGATION_PATTERNS + MUTATION_ACTION_NEGATION_PATTERNS,
        text,
        re.IGNORECASE,
    )


def _has_release_action(text: str) -> bool:
    return _matches(RELEASE_ACTION_PATTERNS, text, re.IGNORECASE) and not _matches(
        MUTATION_ACTION_NEGATION_PATTERNS,
        text,
        re.IGNORECASE,
    )


def _has_user_confirmed_correction(text: str) -> bool:
    return (
        _matches(PRIOR_COMPLETION_REFERENCE_PATTERNS, text, re.IGNORECASE)
        and _matches(COMPLETION_FAILURE_PATTERNS, text, re.IGNORECASE)
        and _matches(CORRECTION_ACTION_PATTERNS, text, re.IGNORECASE)
    )


def _commit_risk_blocks(text: str) -> bool:
    return _matches(COMMIT_BLOCKING_RISK_PATTERNS, text.lower())


def _release_risk_blocks(text: str) -> bool:
    return _matches(RELEASE_BLOCKING_RISK_PATTERNS, text.lower())


def _release_scope_signal_count(text: str) -> int:
    return sum(1 for patterns in RELEASE_SCOPE_SIGNAL_PATTERNS if _matches(patterns, text, re.IGNORECASE))
