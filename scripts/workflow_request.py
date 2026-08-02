"""Conservative request intake and non-authoritative concern inference."""

from __future__ import annotations

import re
from typing import Optional

from workflow_catalog import REQUEST_CONCERN_HINTS
from workflow_common import ANSWER_ONLY_CLARITY, QUESTION_ROUTE_COMMANDS, unique
from workflow_request_patterns import (
    CORRECTION_WORD_SENSE_QUESTION_PATTERNS,
    DIRECT_QUESTION_PATTERNS,
    IMPERATIVE_CORRECTION_ACTION_PATTERNS,
    QUESTION_ACTION_PATTERNS,
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
        r"\b(?:skip|omit|exclude|disable|bypass|drop|leave\s+out)\s+"
        r"(?:(?:running|using|invoking|calling|executing|installing|the)\s+)?graphify\b",
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
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프)"
        r"(?:\s*(?:는|은|를|을|도|만))?\s*"
        r"(?:하지\s*마|하지\s*않|안\s*함|금지|제외|생략|건너뛰|스킵|무시|빼)",
    ),
}
EXPLICIT_CONCERN_EXCLUSION_NEGATION_PATTERNS = {
    "graphify": (
        r"\b(?:do not|don'?t|must not|mustn'?t|should not|shouldn'?t|never|"
        r"no need to)\s+(?:\w+\s+){0,2}?"
        r"(?:skip|omit|exclude|disable|bypass|drop|leave\s+out)\b",
        r"(?:제외|생략|무시|배제|스킵)하지\s*(?:마|말|않)",
        r"(?:빼|건너뛰)지\s*(?:마|말|않)",
    ),
}

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
    return {
        "request": normalized,
        "clarity": ANSWER_ONLY_CLARITY if answer_only else "vague-action",
        "effort": effort,
        "model_tier": model_tier,
        "model_selection": _model_selection(model_tier, effort),
        "recommended_route": "none" if answer_only else "triage",
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
