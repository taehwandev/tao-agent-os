"""Request classification and concern inference for workflow routing."""

from __future__ import annotations

import re
from typing import Optional

from workflow_catalog import REQUEST_CONCERN_HINTS
from workflow_common import ANSWER_ONLY_CLARITY, QUESTION_ROUTE_COMMANDS, unique
from workflow_request_patterns import (
    BROAD_PATTERNS,
    DIRECT_QUESTION_PATTERNS,
    GRILL_ME_REQUEST_PATTERNS,
    EXACT_PATTERNS,
    INSPECTION_PATTERNS,
    RELEASE_ACTION_PATTERNS,
    REFACTOR_ACTION_PATTERNS,
    QUESTION_ACTION_PATTERNS,
    REVIEW_ACTION_PATTERNS,
    RISKY_PATTERNS,
    SCOPED_PATTERNS,
    TEST_ACTION_PATTERNS,
    WORKFLOW_SETUP_ACTION_PATTERNS,
    UI_FEATURE_ACTION_PATTERNS,
    VAGUE_PATTERNS,
)

UNRESOLVED_ANSWER_FIRST_PATTERNS = (
    r"\bdirect-question\b",
    r"\bdirect question\b",
    r"\bdirect_question\b",
    r"\banswer_first\b",
    r"\banswer-first\b",
    r"\banswer first\b",
)
UNRESOLVED_CLARIFICATION_PATTERNS = (
    r"\bvague-action\b",
    r"\bbroad-product\b",
    r"\brisky-unclear\b",
    r"\bclarify_first\b",
    r"\bclarify-first\b",
    r"\bclarify first\b",
    r"\bneeds clarification\b",
    r"\bambiguous\b",
    r"\bunclear\b",
    r"\bunknowns?\b",
    r"\bblocker questions?\b",
    r"\bask (the )?user\b",
    r"\bneeds? (a )?question\b",
    r"\bgrill_me\s*[:=]?\s*true\b",
    r"\bgrill[- ]?me\s*[:=]?\s*true\b",
    r"\bquestion_drill\s*[:=]?\s*true\b",
    r"\bquestion[- ]drill\s*[:=]?\s*true\b",
    r"\bquestion drill\s*[:=]?\s*true\b",
    r"\b모호\b",
    r"\b불명확\b",
    r"\b불확실\b",
    r"\b미정\b",
    r"\b질문 필요\b",
    r"\b확인 필요\b",
    r"\b블로커\b",
    r"\b그릴미\b",
)
EXPLICIT_UNRESOLVED_PATTERNS = (
    r"\bnot\s+(?:yet\s+)?(?:answered|clarified|resolved)\b",
    r"\bstill\s+(?:needs?|requires?)\s+(?:clarification|questions?|answers?|resolution)\b",
    r"\bstill\s+(?:ambiguous|unclear|unresolved)\b",
    r"\bpending\s+(?:clarification|questions?|answers?|resolution)\b",
    r"\b아직\b.*(?:모호|불명확|불확실|미정|질문|확인|해결)",
    r"\b미해결\b",
    r"\b해결\s*(?:안|되지\s*않)",
)
# These three phrases mean the opposite of unresolved once a negator applies to
# them, so they cannot live in EXPLICIT_UNRESOLVED_PATTERNS as bare matches.
# The negator is not always the token immediately to the left, which is all a
# fixed-width lookbehind such as `(?<!\bno\s)` can inspect: in a coordinated
# clause ("no open questions or blockers remain") the "no" sits several tokens
# earlier and was missed, so a sentence asserting that nothing is outstanding
# was read as proof that blockers remain. Scan leftward across the whole clause
# for the negator instead.
NEGATABLE_UNRESOLVED_PATTERNS = (
    r"\bunresolved\b",
    r"\bopen\s+(?:questions?|blockers?)\b",
    r"\bblockers?\s+(?:remain|pending|open|unresolved)\b",
)
# A negator only covers its own clause. Punctuation and contrastive
# conjunctions end it, so "no docs changed, blockers remain" and "no open
# questions but blockers remain" still register as genuinely unresolved.
_UNRESOLVED_CLAUSE_BOUNDARY_RE = re.compile(
    r"[.;:,()\[\]\n]|\b(?:but|however|though|although|yet|except|whereas)\b"
)
_UNRESOLVED_NEGATOR_RE = re.compile(r"\b(?:no|none|zero|without)\b")
# Korean negation is post-positional ("블로커 없음"), so it is searched to the
# right of the phrase within the same clause rather than to the left.
_UNRESOLVED_KOREAN_NEGATOR_RE = re.compile(r"없")


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the clause span containing text[start:end]."""
    clause_start = 0
    for boundary in _UNRESOLVED_CLAUSE_BOUNDARY_RE.finditer(text, 0, start):
        clause_start = boundary.end()
    tail = _UNRESOLVED_CLAUSE_BOUNDARY_RE.search(text, end)
    clause_end = tail.start() if tail else len(text)
    return clause_start, clause_end


def _has_explicit_unresolved_signal(text: str) -> bool:
    return _matches(EXPLICIT_UNRESOLVED_PATTERNS, text) or _has_unnegated_unresolved_signal(text)


def _has_unnegated_unresolved_signal(text: str) -> bool:
    for pattern in NEGATABLE_UNRESOLVED_PATTERNS:
        for match in re.finditer(pattern, text):
            clause_start, clause_end = _clause_bounds(text, match.start(), match.end())
            if _UNRESOLVED_NEGATOR_RE.search(text, clause_start, match.start()):
                continue
            if _UNRESOLVED_KOREAN_NEGATOR_RE.search(text, match.end(), clause_end):
                continue
            return True
    return False


CLASSIFICATION_RESOLVED_PATTERNS = (
    r"\bclear-exact\b",
    r"\bclear-scoped\b",
    r"\banswered\b.*\buser asked\b",
    r"\banswered\b.*\bseparate actionable\b",
    r"\banswered\b.*\bseparate action\b",
    r"\bblockers?\s+resolved\b",
    r"\bresolved blockers?\b",
    r"\bambiguity resolved\b",
    r"\bunknowns? resolved\b",
    r"\bno open (?:questions?|blockers?)\b",
    r"\bno blockers?\s+remain\b",
    r"\bno\s+(?:unresolved\s+)?(?:behavior\s+)?blockers?\s+remains?\b",
    r"\bscope clarified\b",
    r"\bdecisions? clarified\b",
    r"\bclarified decisions?\b",
    r"명확(?:한)?\s*(?:범위|스코프)",
    r"(?:질문|직접\s*질문)\s*해결.*(?:별도|추가)\s*(?:작업|요청)",
    r"(?:블로커|차단|막힌)\s*(?:질문|사항)?\s*해결",
    r"(?:모호성|불명확성|미정사항)\s*해결",
)
# The trigger word alone ("재개", "승인", "진행") is not proof of approval --
# "재개하면 안 된다" / "재개하지 마" / "진행 불가" attach negation directly to
# the trigger, but "재개는 승인되지 않았다" negates a DIFFERENT word (승인)
# in a separate clause about the same topic. A single-position lookahead
# right after the trigger only catches the first form; this needs a wider,
# unanchored scan of the text that follows the trigger to also catch the
# second. A regex-only lookahead can't express "scan forward, not just the
# next token" without becoming unreadable, so this is a small dedicated
# function instead of one more tuple entry in CLASSIFICATION_RESOLVED_PATTERNS.
_NEW_RUN_APPROVAL_TRIGGER_RE = re.compile(
    r"(?:별도|새)\s*(?:실행|작업|요청).{0,120}?(?:명시적(?:으로)?\s*)?(?:승인|재개|진행)"
)
_NEW_RUN_APPROVAL_NEGATION_RE = re.compile(
    r"(?:을|를|은|는|이|가)?\s*안\s*(?:하|해|함|한다|합니다|되|돼|됨|된다|됩니다|됐)"
    r"|(?:하|되)지\s*(?:마세요|말아|마|않|못)"
    r"|(?:해서는|하면|돼서는|되면)\s*안"
    r"|(?:할|될)\s*수\s*없"
    r"|\s*못\s*(?:하|한다|합니다|해)"
    r"|\s*불가\b"
    r"|이?\s*없"
)


def _has_new_run_approval_signal(text: str) -> bool:
    for match in _NEW_RUN_APPROVAL_TRIGGER_RE.finditer(text):
        # A wider window (not just the next token) catches negation displaced
        # into a separate clause about the same trigger word, e.g. "재개는
        # 승인되지 않았다" -- the negation attaches to "승인", which follows
        # "재개" by more than a single adjacent token.
        tail = text[match.end() : match.end() + 30]
        if _NEW_RUN_APPROVAL_NEGATION_RE.search(tail):
            continue
        return True
    return False
# A short approval can be a valid continuation of an already settled discussion.
# Keep this deliberately narrow: it must contain a referential cue ("then/that/this"
# or the Korean equivalent) and an explicit action approval. Bare "do it" requests
# remain vague and continue to require triage.
FOLLOW_UP_APPROVAL_PATTERNS = (
    r"^(?:then|so|in that case|that|this)\b.{0,120}\b(?:fix|change|edit|apply|implement|proceed|continue|go ahead)\b",
    r"^(?:아하\s*)?(?:그럼|그러면|그렇다면|그 부분|그건|이건|이렇게)\s*.{0,120}(?:수정|변경|적용|반영|구현|진행|해줘|해주세요|할게)",
)
COMMIT_ACTION_PATTERNS = (
    r"\bcommit(?:ting|s)?\b",
    r"\bgit commit\b",
    r"\bmake a commit\b",
    r"\bcreate a commit\b",
    r"\bcommit message\b",
    # Korean particles and verb endings attach directly to nouns, so word
    # boundaries reject actionable forms such as "커밋하라고". Keep a
    # left-side guard so "미커밋" does not become a commit action signal, and
    # a right-side guard so a bare "커밋" inside a comparison ("커밋보다 더
    # 중요한"), an explicit negation ("커밋하지 마" / "커밋을 하지 마세요" /
    # "커밋은 하지 마" / "커밋 안 해" / "커밋을 하면 안 돼요"), a passive
    # negation ("커밋되지 않았어요" / "커밋이 안 됐습니다" / "커밋이 안됐어요"
    # -- 하다-only "안"/"하지" conjugations missed the passive 되다 family
    # entirely, so "the commit was NOT made" read as a plain commit mention),
    # or a metalinguistic reference ("커밋이라고 부른다") is not mistaken for
    # a commit request either. The negation trigger can follow "커밋" directly
    # or after a particle (을/를/은/는/이/가), so the deny-list allows an
    # optional particle before it.
    r"(?<![가-힣A-Za-z0-9_])커밋"
    r"(?!보다|\s*말고|이라고"
    r"|(?:을|를|은|는|이|가)?\s*안\s*(?:하|해|함|한다|합니다|되|돼|됨|된다|됩니다|됐)"
    r"|(?:을|를|은|는|이|가)?\s*(?:하|되)지\s*(?:마세요|말아|마|않|못)"
    r"|(?:을|를|은|는|이|가)?\s*(?:해서는|하면|돼서는|되면)\s*안"
    r")"
    r"(?:을|를|해|하|하기|으로|까지|부터|만|도)?",
)
# The Korean branch above encodes negation as a lookahead right at the word
# boundary. English negation words are separate tokens that can sit an
# arbitrary distance before "commit" ("do not directly commit", "should
# never just commit"), which Python's fixed-width lookbehind can't express,
# so it is matched forward instead: negation-word (+ a few filler words) +
# commit. This also covers metalinguistic mentions ("commit is only a
# term") and future/conditional references ("before committing").
COMMIT_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|does not|doesn't|never|won't|will not|should not|"
    r"shouldn't|must not|mustn't|cannot|can't)\s+(?:\w+\s+){0,2}commit(?:ting|s)?\b",
    r"\bcommit(?:ting|s)?\s+is\s+(?:only\s+|just\s+|simply\s+)?(?:a\s+|the\s+)?"
    r"(?:term|word|noun|concept)\b",
    r"\b(?:before|prior to)\s+commit(?:ting|s)?\b",
)
COMMIT_RELEASE_SUBSTEP_PATTERNS = (
    r"\b(first|before|current|pending|staged|working tree|worktree|warning cleanup)\b",
    r"\bbefore\s+(?:continuing|release|deploy|publishing|tagging)\b",
    r"\bcommit\b.*\b(?:then|next|after)\b",
    r"\b(?:release|deploy|publish|tag)\b.*\b(?:after|once)\b.*\bcommit\b",
    r"\b(\uba3c\uc800|\uc6b0\uc120|\ud604\uc7ac|\uc21c\uc11c\ub300\ub85c)\b",
)
COMMIT_BLOCKING_RISK_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|payment|billing|secret|token|credential|permission|security|tenant)\b",
    r"\b(force[- ]?push|reset|rebase|amend)\b",
    r"\b(\uc0ad\uc81c|\ub9c8\uc774\uadf8\ub808\uc774\uc158|\ube44\ubc00|secret|token|credential|\uad8c\ud55c|\ubcf4\uc548)\b",
)
RELEASE_BLOCKING_RISK_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|payment|billing|secret|token|credential|permission|security|tenant)\b",
    r"\b(\uc0ad\uc81c|\ub9c8\uc774\uadf8\ub808\uc774\uc158|\ube44\ubc00|secret|token|credential|\uad8c\ud55c|\ubcf4\uc548)\b",
)
RELEASE_SCOPE_SIGNAL_PATTERNS = (
    (
        r"\b(?:v)?\d{2,4}\.\d{1,2}\.\d+(?:[-+][A-Za-z0-9.-]+)?\b",
        r"\bversion\b",
        r"\brelease candidate\b",
        "\ubc84\uc804",
    ),
    (
        r"\b(?:source revision|commit|sha|head|main|branch|tag target|peeled target)\b",
        r"\b[0-9a-f]{7,40}\b",
        "\ucee4\ubc0b",
        "\uc18c\uc2a4",
    ),
    (
        r"\b(?:artifact|package|build|app|binary|dmg|zip|installer|bundle|appcast)\b",
        "\uc0b0\ucd9c\ubb3c",
        "\ud328\ud0a4\uc9c0",
        "\uc571",
    ),
    (
        r"\b(?:push|publish|github release|remote|origin|tag|deploy|release workflow)\b",
        "\uc6d0\uaca9",
        "\ud478\uc26c",
        "\ud0dc\uadf8",
        "\uac8c\uc2dc",
    ),
    (
        r"\b(?:verify|verification|test|build|smoke|package|sign|signed|notary|notarize|rollback|forward-fix)\b",
        "\uac80\uc99d",
        "\ud14c\uc2a4\ud2b8",
        "\ube4c\ub4dc",
        "\ub864\ubc31",
    ),
)

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
        r"\b(?:do not|don't|must not|should not)\s+"
        r"(?:(?:run|use|invoke|call|install|enable)\s+|rely\s+on\s+)graphify\b",
        r"\bwithout\s+(?:(?:running|using|invoking|calling|installing|relying\s+on)\s+)?graphify\b",
        r"\bgraphify\b.{0,40}\b(?:excluded?|disabled?|out\s+of\s+scope)\b",
        r"\bgraphify\b.{0,40}\b(?:must not|should not|do not|don't)\s+"
        r"(?:be\s+)?(?:run|used|invoked|called|installed|enabled)\b",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프).{0,40}"
        r"(?:실행|사용|설치)(?:은|는|을|를)?\s*(?:제외|금지|하지\s*마|하지\s*않)",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프).{0,40}"
        r"(?:돌리면\s*안|돌리지\s*마|안\s*돌)",
        r"(?:graphify|그래피|그래프|프로젝트 그래프|지식 그래프)(?:가|이|를|을)?\s*없이",
    ),
}


def infer_concerns_from_request(text: str) -> list[str]:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    inferred: list[str] = []
    for concern, patterns in REQUEST_CONCERN_HINTS:
        excluded = _matches(
            EXPLICIT_CONCERN_EXCLUSION_PATTERNS.get(concern, ()),
            normalized,
            re.IGNORECASE,
        )
        if _matches(patterns, normalized, re.IGNORECASE) and not excluded:
            inferred.append(concern)
    return unique(inferred)


def classify_request(text: str) -> dict[str, object]:
    normalized = " ".join(text.strip().split())
    lowered = normalized.lower()
    flags = _request_flags(normalized, lowered)
    route, question_drill, response_mode, reason = _classification_decision(flags)
    model_tier = _model_tier_for_effort(str(flags["effort"]))
    code_authoring = requires_code_authoring(normalized)
    if code_authoring and model_tier == "fast":
        model_tier = "balanced"
    model_selection = _model_selection(model_tier, str(flags["effort"]))
    if code_authoring and model_tier == "balanced" and flags["effort"] == "quick":
        model_selection["reason"] = "code authoring requires at least the balanced tier"

    return {
        "request": normalized,
        "clarity": flags["clarity"],
        "effort": flags["effort"],
        "model_tier": model_tier,
        "model_selection": model_selection,
        "recommended_route": route,
        "grill_me": question_drill,
        "question_drill": question_drill,
        "response_mode": response_mode,
        "reason": reason,
        "notes": [
            "Answer direct user questions before routing, editing, or running project work.",
            "Use repo-local instructions before editing.",
            "Escalate effort if local inspection finds broader risk.",
            "Select the lowest capable model tier before runtime-specific model ids.",
        ],
    }


def _model_tier_for_effort(effort: str) -> str:
    return MODEL_TIER_BY_EFFORT.get(effort, "balanced")


def _model_selection(model_tier: str, effort: str) -> dict[str, object]:
    return {
        "tier": model_tier,
        "codex": CODEX_MODEL_BY_TIER.get(model_tier, CODEX_MODEL_BY_TIER["balanced"]),
        "switching_boundary": "task-or-agent-boundary",
        "runtime_mapping": "codex-only-or-runtime-equivalent",
        "fallback": "keep-current-model-and-apply-effort-profile",
        "reason": f"effort={effort} maps to model_tier={model_tier}",
        "runtime_policy": (
            "Map the abstract tier to the active runtime. Use Codex model ids only on Codex; "
            "Claude and other runtimes should use equivalent configured tiers or keep the "
            "current model when switching is unavailable."
        ),
    }


def requires_code_authoring(request: str) -> bool:
    lowered = request.lower()
    return any(re.search(pattern, lowered) for pattern in CODE_AUTHORING_REQUEST_PATTERNS)


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
    has_release_action = _matches(RELEASE_ACTION_PATTERNS, normalized, re.IGNORECASE)
    release_scope_signal_count = _release_scope_signal_count(normalized)
    has_release_scope = release_scope_signal_count >= 2
    commit_release_substep = has_commit_action and (
        not has_release_action or _matches(COMMIT_RELEASE_SUBSTEP_PATTERNS, normalized, re.IGNORECASE)
    )
    inspection_lacks_target = has_inspection and _inspection_lacks_target(lowered)
    has_direct_question = _matches(DIRECT_QUESTION_PATTERNS, lowered)
    asks_agent_action = _matches(QUESTION_ACTION_PATTERNS, lowered)
    short_without_target = len(normalized.split()) <= 8 and not (has_exact or has_scoped)
    asks_drill = _matches(GRILL_ME_REQUEST_PATTERNS, lowered)
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
        "release_scope_signal_count": release_scope_signal_count,
        "commit_release_substep": commit_release_substep,
        "inspection_lacks_target": inspection_lacks_target,
        "has_direct_question": has_direct_question,
        "asks_agent_action": asks_agent_action,
        "short_without_target": short_without_target,
        "asks_drill": asks_drill,
        "underspecified_action": underspecified_action,
    }


def _classification_decision(flags: dict[str, object]) -> tuple[str, bool, str, str]:
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

    if flags["has_direct_question"] and not flags["asks_agent_action"]:
        flags["clarity"] = ANSWER_ONLY_CLARITY
        flags["effort"] = "standard" if has_broad else "quick"
        route = "product" if has_broad else "none"
        reason = _direct_question_reason(has_broad)
        return route, False, "answer_first", reason
    if has_risky and not has_broad and not (has_exact or has_scoped):
        flags["clarity"] = "risky-unclear"
        flags["effort"] = "deep"
        return "ambiguity", True, "clarify_first", "Risk-sensitive terms appear without an exact implementation target."
    if flags["asks_drill"]:
        flags["clarity"] = "vague-action"
        flags["effort"] = "deep" if has_broad or has_risky else "standard"
        return "triage", True, "clarify_first", "The request explicitly asks for the Grill-Me protocol before work."
    return None


def _explicit_action_decision(
    flags: dict[str, object],
) -> tuple[str, bool, str, str] | None:
    has_risky = bool(flags["has_risky"])
    lowered = str(flags.get("lowered") or "")
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
        and not _commit_risk_blocks(lowered)
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
        and not _release_risk_blocks(lowered)
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
        return "feature", False, "work", "The request describes a scoped UI or screen feature to implement."
    return None


def _scope_fallback_decision(flags: dict[str, object]) -> tuple[str, bool, str, str]:
    has_risky = bool(flags["has_risky"])
    lowered = str(flags.get("lowered") or "")

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
        return "code-simplify", False, "work", "The request asks for behavior-preserving code cleanup or simplification."
    if flags["has_test_action"] and not has_risky:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "quick"
        return "test", False, "work", "The request asks for verification or test execution."
    if flags["has_exact"]:
        flags["clarity"] = "clear-exact"
        flags["effort"] = "quick"
        return "task", False, "work", "The request names an exact file, symbol, command, or error signal."
    if flags["has_scoped"]:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return "feature", False, "work", "The request names a scoped UI, code, or feature owner."
    if flags["has_inspection"] and not has_risky and not flags["inspection_lacks_target"]:
        flags["clarity"] = "clear-scoped"
        flags["effort"] = "standard"
        return "task", False, "work", "The request asks for inspection, review, status, or documentation summary work with an inspectable target."
    if _matches(FOLLOW_UP_APPROVAL_PATTERNS, lowered, re.IGNORECASE) and not has_risky:
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
        return "triage", True, "clarify_first", "The request asks for action but lacks a precise target, inspection target, or acceptance criteria."
    flags["clarity"] = "clear-scoped"
    flags["effort"] = "standard"
    return "task", False, "work", "No high-risk ambiguity was detected, but local context is still needed."


def _direct_question_reason(has_broad: bool) -> str:
    if has_broad:
        return (
            "The request asks how to approach app/product/feature work. Answer first, "
            "but include the PRD -> ARD -> implementation gate before lower-level steps."
        )
    return "The request is a direct question, so answer it before starting any workflow or edit."


def _matches(patterns: object, text: str, flags: int = 0) -> bool:
    return any(re.search(pattern, text, flags) for pattern in patterns)


def _has_commit_action(text: str) -> bool:
    if not _matches(COMMIT_ACTION_PATTERNS, text, re.IGNORECASE):
        return False
    # "do not commit", "commit is only a term", "before committing" all
    # match COMMIT_ACTION_PATTERNS' bare \bcommit\b, but none of them are a
    # request or approval to actually commit.
    return not _matches(COMMIT_NEGATION_PATTERNS, text, re.IGNORECASE)


def _release_scope_signal_count(text: str) -> int:
    return sum(1 for patterns in RELEASE_SCOPE_SIGNAL_PATTERNS if _matches(patterns, text, re.IGNORECASE))


def _commit_risk_blocks(text: str) -> bool:
    return _matches(COMMIT_BLOCKING_RISK_PATTERNS, text.lower())


def _release_risk_blocks(text: str) -> bool:
    return _matches(RELEASE_BLOCKING_RISK_PATTERNS, text.lower())


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


def print_classification(result: dict[str, object]) -> None:
    print("# Tao Agent OS Request Classification")
    print()
    print(f"Clarity: `{result['clarity']}`")
    print(f"Effort: `{result['effort']}`")
    model_selection = result.get("model_selection") or {}
    if model_selection:
        print(f"Model tier: `{model_selection['tier']}`")
        print(f"Codex model: `{model_selection['codex']}`")
        print(f"Runtime mapping: `{model_selection['runtime_mapping']}`")
        print(f"Switching boundary: `{model_selection['switching_boundary']}`")
    print(f"Recommended route: `{result['recommended_route']}`")
    print(f"Grill-Me protocol: `{str(result['grill_me']).lower()}`")
    print(f"Response mode: `{result['response_mode']}`")
    print()
    print(f"Reason: {result['reason']}")
    print()
    print("## Next")
    if result["clarity"] == ANSWER_ONLY_CLARITY:
        print("- Answer the user's direct question first.")
        if result["recommended_route"] == "product":
            print("- Include PRD -> ARD -> implementation first; if work proceeds, run the `product` route.")
        print("- Do not start a workflow route, edit files, or run project-specific work unless a separate action remains.")
    elif result["question_drill"]:
        print("- Run `python3 <TAO_ROOT>/scripts/workflow.py route triage --request \"<request text>\"`.")
        print("- Use the Grill-Me `/grilling` protocol after checking available local context.")
        print(
            "- Start the user-visible clarification with `Grill-Me protocol /grilling session`, "
            "ask one blocker question with a recommended answer and tradeoff, then wait for feedback before work."
        )
        print("- If an external Grill-Me skill is unavailable, run the built-in blocker-question protocol and record its output.")
        print("- Record finish evidence as `grill-me if needed=</grilling session/output evidence>`.")
    else:
        print(
            f"- Run `python3 <TAO_ROOT>/scripts/workflow.py route {result['recommended_route']} "
            "--request \"<request text>\"` with matching platform/concerns when needed."
        )
        print("- Inspect the named target or smallest relevant local context first.")
    print("- Keep the route gate ledger current if a workflow route is used.")


def route_block_reason(
    command: str,
    classification: Optional[dict[str, object]],
) -> Optional[str]:
    if not classification:
        return None
    if classification["clarity"] == ANSWER_ONLY_CLARITY:
        reason = (
            "The current request is a direct question. Answer it in the conversation "
            "before starting a workflow route, editing files, or running project-specific work."
        )
        if classification["recommended_route"] == "product":
            reason += " Include PRD -> ARD -> implementation gates before lower-level coding steps."
        return reason
    if classification["question_drill"] and command not in QUESTION_ROUTE_COMMANDS:
        return (
            f"The current request needs clarification before route `{command}`. "
            "Use `triage` or `ambiguity`, run the Grill-Me `/grilling` protocol, "
            "and rerun the work route only after the request is clear."
        )
    if classification["recommended_route"] == "product" and command == "feature":
        return (
            "The current request is broad app/product/feature work. Use route `product` "
            "so PRD and ARD gates run before implementation; do not route it as `feature`."
        )
    return None


def classified_route_block_reason(command: str, classification_evidence: str) -> Optional[str]:
    """Block work routes unless --request-classified proves the request is actionable."""
    if command in QUESTION_ROUTE_COMMANDS:
        return None
    if classification_evidence_allows_command_work(command, classification_evidence):
        return None
    return (
        f"The prior request classification evidence does not prove work can start before route `{command}`. "
        "Answer direct questions first, or use `triage`/`ambiguity` and run Grill-Me or the blocker-question protocol. "
        "Rerun the work route only after evidence states clear scope, a separate actionable request, or resolved blockers."
    )


def classification_evidence_blocks_work(evidence: str) -> bool:
    normalized = " ".join(evidence.strip().lower().split())
    if not normalized:
        return True
    if _has_explicit_unresolved_signal(normalized):
        return True
    return not _has_resolution_signal(normalized)


def _commit_evidence_allows_work(command: str, evidence: str) -> bool:
    if command not in {"commit", "git_commit"}:
        return False
    normalized = " ".join(evidence.strip().lower().split())
    if not normalized or _has_explicit_unresolved_signal(normalized):
        return False
    return _has_commit_action(evidence)


def _release_evidence_allows_work(command: str, evidence: str) -> bool:
    if command not in {"release", "ship"}:
        return False
    normalized = " ".join(evidence.strip().lower().split())
    if not normalized or _has_explicit_unresolved_signal(normalized):
        return False
    has_release_action = _matches(RELEASE_ACTION_PATTERNS, evidence, re.IGNORECASE)
    enough_context_without_action = _release_scope_signal_count(evidence) >= 3
    return (
        (has_release_action or enough_context_without_action)
        and _release_scope_signal_count(evidence) >= 2
        and not _release_risk_blocks(evidence)
    )


def classification_evidence_allows_command_work(command: str, evidence: str) -> bool:
    if _commit_evidence_allows_work(command, evidence):
        return True
    if _release_evidence_allows_work(command, evidence):
        return True
    return classification_evidence_allows_work(evidence)


def classification_evidence_allows_work(evidence: str) -> bool:
    return not classification_evidence_blocks_work(evidence)


def classification_evidence_requires_clarification(evidence: str) -> bool:
    normalized = " ".join(evidence.strip().lower().split())
    if not normalized:
        return False
    has_unresolved_signal = _matches(UNRESOLVED_CLARIFICATION_PATTERNS, normalized)
    has_explicit_unresolved = _has_explicit_unresolved_signal(normalized)
    return has_explicit_unresolved or (has_unresolved_signal and not _has_resolution_signal(normalized))


def _has_resolution_signal(normalized: str) -> bool:
    return _matches(CLASSIFICATION_RESOLVED_PATTERNS, normalized) or _has_new_run_approval_signal(
        normalized
    )
