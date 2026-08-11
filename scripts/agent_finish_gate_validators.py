"""Focused validators for route gates with larger evidence contracts."""

from __future__ import annotations

import re


def has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _render(label: str, phrases: tuple[str, ...], limit: int) -> str:
    shown = [phrase for phrase in phrases if phrase][:limit]
    if not shown:
        return ""
    more = ", ..." if len(phrases) > len(shown) else ""
    return f" {label}: " + ", ".join(shown) + more


def accepted(phrases: tuple[str, ...], limit: int = 8) -> str:
    """Name the wording that satisfies a substring check.

    These gates decide pass or fail by substring match, but the refusal only
    restated the requirement in prose. An agent that wrote a truthful sentence
    the matcher did not recognise had no way to learn which wording it wanted, so
    the only route forward was to open the validator source -- once per refusal,
    every time. Naming the phrases turns a source dive into a reread of the
    message. It leaks nothing: the phrases are the contract, not a secret.
    """
    return _render("accepted wording includes", phrases, limit)


def matched(text: str, phrases: tuple[str, ...]) -> str:
    """Return the first phrase in ``text``, or an empty string."""
    for phrase in phrases:
        if phrase and phrase in text:
            return phrase
    return ""


def triggers(text: str, phrases: tuple[str, ...], limit: int = 8) -> str:
    """Name the wording that caused a refusal.

    The mirror of ``accepted``. Where a check refuses on a match rather than
    passing on one, listing what it accepts points the reader the wrong way: what
    they need is the word their own sentence tripped over. Naming the match beats
    listing the first few candidates, because the phrase that fired is often not
    among them -- observed on a Korean skip token that sat last in a 21-entry
    list, so the refusal showed eight English phrases and none of them was the
    reason.
    """
    hit = matched(text, phrases)
    if hit:
        return f" refused on the wording: {hit}"
    return _render("reads as such on wording like", phrases, limit)


DOC_ARTIFACT_PHRASES = (
    "artifact", "doc type", "doc class", "prd", "product requirements",
    "spec", "feature spec", "functional spec", "ard", "architecture note",
    "architecture doc", "adr", "rfc", "decision record", "module readme", "readme",
    "api contract", "api reference", "schema", "event contract",
    "runbook", "ops guide", "operator guide", "migration note",
    "release note", "changelog", "test plan", "qa plan", "skill card",
    "platform card", "workflow card", "agent instruction", "agents.md",
    "contributing", "wiki", "knowledge-base", "요구사항", "스펙",
    "아키텍처", "런북", "마이그레이션", "릴리즈", "테스트 계획",
)

NO_DURABLE_DOC_REASONS = (
    "answer-only", "purely local", "local-only", "mechanical",
    "no durable behavior", "no durable change", "no user-visible",
    "no workflow policy", "no public contract", "no operator action",
    "no acceptance criteria", "no product behavior", "no architecture",
    "no runtime behavior", "docs-only typo", "format-only",
    "no workflow policy changed", "no public contract changed",
    "no operator action changed", "no acceptance criteria changed",
    "no product behavior changed", "no architecture changed",
    "no release behavior changed", "no test plan changed",
    "답변만", "기계적", "동작 변경 없음", "문서 영향 없음",
)

NON_CREATION_DECISIONS = (
    "unchanged", "not applicable", "no doc", "no docs",
    "변경 없음", "해당 없음",
)

UNCHANGED_DECISIONS = ("unchanged", "변경 없음")

NO_DOC_DECISIONS = ("not applicable", "no doc", "no docs", "해당 없음")

EXPLICIT_DOCUMENTATION_DECISION_PATTERN = re.compile(
    r"\b(?:documentation|impact)\s+decision\s*[:=]\s*"
    r"(updated|created|added|unchanged|not applicable|no docs?|변경 없음|해당 없음)\b"
)

UNCHANGED_COVERAGE_PHRASES = (
    "already covered", "already cover", "already covers", "already documented",
    "existing doc", "existing docs", "inspected", "current doc",
    "current docs", "up to date", "still current", "no edit needed",
    "covered by", "coverage:", "covered_by=", "covers the",
    "이미", "커버", "반영되어", "반영됨", "현재 문서",
)

# An `unchanged` documentation decision must prove the doc was actually opened
# and read, not merely asserted to already cover the change. These phrases are
# the inspection proof; a bare coverage claim without one of them is a
# self-granted exception and must fail the gate.
DOC_INSPECTION_PROOF_PHRASES = (
    "inspected", "opened", "re-read", "reread", "read the",
    "reviewed", "checked ", "verified", "looked at", "examined",
    "confirmed by reading", "opened and", "re-opened",
    "열어", "열람", "확인", "검토", "재검토", "읽어", "읽고",
)

# The coverage-state claim that pairs with the inspection proof: why the opened
# doc already reflects the change.
DOC_COVERAGE_STATE_PHRASES = (
    "already covered", "already cover", "already covers", "already documented",
    "already contains", "contains the requested", "contains the required",
    "existing doc", "existing docs", "current doc", "current docs",
    "up to date", "still current", "no edit needed", "covered by",
    "coverage:", "covered_by=", "covers the",
    "remains accurate", "remain accurate", "still accurate",
    "stays accurate", "stays correct", "still correct",
    "accurate as written", "correct as written",
    "이미", "커버", "반영되어", "반영됨", "이미 포함", "현재 문서", "여전히 정확",
)


def _explicit_documentation_decision(text: str) -> str | None:
    match = EXPLICIT_DOCUMENTATION_DECISION_PATTERN.search(text)
    return match.group(1) if match else None


def documentation_decision_has_any(text: str, phrases: tuple[str, ...]) -> bool:
    """Prefer a labeled decision over decision-like words in its reason."""

    explicit = _explicit_documentation_decision(text)
    return has_any(explicit if explicit is not None else text, phrases)

DURABLE_DOC_CHANGE_PATTERNS = (
    r"\b(planning|plan|requirements?|spec|scope|acceptance criteria)\b.*\b(changed?|updated?|new|added|removed|revised?)\b",
    r"\b(changed?|updated?|new|added|removed|revised?)\b.*\b(planning|plan|requirements?|spec|scope|acceptance criteria)\b",
    r"\b(product behavior|workflow policy|public contract|operator action|architecture|api contract|schema|migration|release|runbook|test plan)\b.*\b(changed?|updated?|new|added|removed|revised?)\b",
    r"\b(changed?|updated?|new|added|removed|revised?)\b.*\b(product behavior|workflow policy|public contract|operator action|architecture|api contract|schema|migration|release|runbook|test plan)\b",
    r"(기획|요구사항|요건|스펙|범위|수용 기준|수락 기준|제품 동작|워크플로우 정책|공개 계약|운영자 조치|아키텍처|api|스키마|마이그레이션|배포|릴리즈|런북|테스트 계획)\s*(변경|수정|갱신|추가|삭제)",
    r"(변경|수정|갱신|추가|삭제).*(기획|요구사항|요건|스펙|범위|수용 기준|수락 기준|제품 동작|워크플로우 정책|공개 계약|운영자 조치|아키텍처|api|스키마|마이그레이션|배포|릴리즈|런북|테스트 계획)",
)


def validate_source_docs_evidence(
    evidence: str,
    *,
    required_docs: list[str] | None = None,
) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    empty_required_manifest = any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:route\s+)?required_docs\b.{0,48}\b(?:empty|none|no entries|zero|0)\b",
            r"\b(?:route\s+)?required[- ]docs?\s+manifest\b.{0,48}\b(?:empty|none|no entries|zero|0)\b",
            r"(?:route의\s*)?(?:required_docs|필수\s*문서).{0,40}(?:비어|없음|(?<!\d)0개)",
        )
    )
    reads_route_required_docs = any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:read|opened|reviewed|loaded)\b.{0,80}\b(?:route\s+required_docs|required_docs|route\s+required\s+docs|required[- ]docs?\s+manifest|required[- ]documents?\s+manifest|every\s+required\s+doc|all\s+required\s+docs)\b",
            r"\b(?:route\s+required_docs|required_docs|route\s+required\s+docs|required[- ]docs?\s+manifest|required[- ]documents?\s+manifest|every\s+required\s+doc|all\s+required\s+docs)\b.{0,80}\b(?:read|opened|reviewed|loaded)\b",
            r"(?:route의\s*)?(?:required_docs|필수\s*문서).{0,40}(?:읽|열람|검토)",
            r"(?:읽|열람|검토).{0,40}(?:route의\s*)?(?:required_docs|필수\s*문서)",
        )
    )
    has_discovery = has_any(
        text,
        (
            "searched", "discovered", "found", "opened", "read", "checked",
            "no prd", "no spec", "none found",
            "검색", "발견", "열", "읽", "확인", "없음",
        ),
    )
    names_source = has_any(
        text,
        (
            "prd", "spec", "ard", "requirements", "acceptance criteria",
            "design note", "issue", "source-of-truth", "source of truth",
            "product docs", "task doc", "planning doc",
            "adr", "rfc", "module readme", "api contract", "runbook",
            "migration note", "release note", "test plan", "skill card",
            "platform card", "workflow card", "agent instruction",
            "문서", "요구사항", "스펙", "기획",
        ),
    )
    before_work = has_any(
        text,
        (
            "before code", "before coding", "before implementation",
            "before edit", "before edits", "before work",
            "pre-code", "pre implementation",
            "구현 전", "수정 전", "작업 전",
        ),
    )
    applies_task_takeaway = has_any(
        text,
        (
            "applied takeaway", "takeaway:", "takeaway=", "rule applied",
            "applied", "used", "informed", "guided", "adopted",
            "반영", "적용", "핵심 규칙", "배운 점",
        ),
    )
    if empty_required_manifest and required_docs:
        return [
            "source docs evidence claims the required_docs manifest is empty, but "
            "the current route requires: " + ", ".join(required_docs)
        ]
    if required_docs == [] and not empty_required_manifest:
        return [
            "source docs evidence must record that the current required_docs manifest is empty "
            "for this document-free route"
        ]
    if required_docs:
        missing_docs = [doc for doc in required_docs if doc.lower() not in text]
        if missing_docs:
            return [
                "source docs evidence must include the current route required_docs "
                "manifest; missing: " + ", ".join(missing_docs)
            ]
    # A route with no required documents is a completed discovery outcome, not
    # a skipped source-docs gate. The caller supplies the actual route manifest
    # so an asserted empty state can never mask a non-empty manifest.
    if empty_required_manifest and has_discovery and before_work and applies_task_takeaway:
        return []
    if (
        reads_route_required_docs
        and has_discovery
        and names_source
        and before_work
        and applies_task_takeaway
    ):
        return []
    return [
        "source docs evidence must state that every route required_docs entry "
        "was opened/read directly before implementation or edits and name the "
        "task-specific takeaway that was applied. It must also identify the "
        "relevant source-of-truth docs searched, or state that none were found. "
        "Source docs can be PRD/spec/ARD, issue/design note, "
        "ADR/RFC, module README, API contract, runbook, migration note, release "
        "note, test plan, skill/platform/workflow card, or agent instruction"
    ]


def validate_documentation_impact_evidence(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    pre_edit = has_any(
        text,
        (
            "before code", "before implementation", "before edit",
            "before edits", "pre-code", "pre-edit", "구현 전", "수정 전",
        ),
    )
    selects_artifact = has_any(text, DOC_ARTIFACT_PHRASES)
    has_decision = has_any(
        text,
        (
            "impact", "affected", "documentation decision", "update",
            "create", "unchanged", "not applicable", "no doc", "no docs",
            "갱신", "생성", "영향", "변경 없음", "해당 없음",
        ),
    )
    has_reason = has_any(
        text,
        (
            "because", "reason", "why", "changed", "behavior",
            "workflow policy", "public contract", "acceptance criteria",
            "operator action", "이유", "왜", "변경",
        ),
    )
    no_doc_decision = documentation_decision_has_any(text, NO_DOC_DECISIONS)
    unchanged_decision = documentation_decision_has_any(text, UNCHANGED_DECISIONS)
    if no_doc_decision and _has_durable_doc_change_signal(text):
        return [
            "documentation impact evidence cannot use not-applicable/no-docs "
            "when it also names a durable planning, requirements, acceptance, "
            "workflow policy, public contract, operator, architecture, API, "
            "release, or test-plan change"
        ]
    if unchanged_decision and not _unchanged_evidence_is_grounded(text):
        return [
            "documentation impact evidence can use unchanged only when it names "
            "the existing doc path it opened/inspected and states why that "
            "already-read doc covers the planning, behavior, contract, or "
            "acceptance change; a bare coverage claim is not enough."
            + accepted(DOC_INSPECTION_PROOF_PHRASES).replace(
                "accepted wording includes", "inspection proof is recognised on"
            )
            + accepted(DOC_COVERAGE_STATE_PHRASES, limit=6).replace(
                "accepted wording includes", "and the coverage claim on"
            )
        ]
    if no_doc_decision and not has_any(text, NO_DURABLE_DOC_REASONS):
        return [
            "documentation impact evidence cannot use not-applicable/no-docs "
            "without a no-durable-doc reason such as answer-only, purely local, "
            "mechanical, no durable behavior, no public contract, no operator "
            "action, or no acceptance criteria"
        ]
    if pre_edit and selects_artifact and has_decision and has_reason:
        return []
    return [
        "documentation impact evidence must state the pre-code/pre-edit "
        "documentation artifact selection, the impact decision, and why "
        "behavior, workflow policy, public contract, operator action, or "
        "acceptance criteria do or do not require creating/updating that artifact"
    ]


def validate_documentation_source_to_artifact_evidence(
    source_evidence: str,
    impact_evidence: str,
) -> list[str]:
    source_text = source_evidence.lower()
    impact_text = impact_evidence.lower()
    if not source_text or not impact_text:
        return []
    no_source_found = has_any(
        source_text,
        (
            "none found", "no source", "no source docs",
            "no source-of-truth", "source not found", "not found", "없음",
        ),
    )
    non_creation = has_any(impact_text, NON_CREATION_DECISIONS)
    if no_source_found and non_creation and not has_any(impact_text, NO_DURABLE_DOC_REASONS):
        return [
            "when source docs are missing, documentation impact cannot choose "
            "unchanged/not-applicable/no-docs unless it states why the work has "
            "no durable documentation artifact. New durable behavior should "
            "create the smallest useful PRD/spec, ADR/RFC, module README, API "
            "contract, runbook, migration note, release note, test plan, skill "
            "card, platform card, workflow card, or agent instruction update"
        ]
    return []


def _has_existing_doc_coverage(text: str) -> bool:
    return has_any(text, UNCHANGED_COVERAGE_PHRASES)


def _names_doc_path(text: str) -> bool:
    """True when the evidence points at a concrete doc file, not just a class."""
    return ".md" in text or "docs/" in text or "/" in text


def _unchanged_evidence_is_grounded(text: str) -> bool:
    """An `unchanged` doc decision is grounded only when it names the doc path,
    proves the doc was opened/inspected, and states why it already covers the
    change. All three are required so the agent cannot self-except by asserting
    coverage without checking."""
    return (
        _names_doc_path(text)
        and has_any(text, DOC_INSPECTION_PROOF_PHRASES)
        and has_any(text, DOC_COVERAGE_STATE_PHRASES)
    )


# A change verb, used both to detect a durable claim and to spot the point
# where a coordinated list stops being part of a negated span.
_CHANGE_VERB = r"(?:changed?|updated?|added?|removed?|revised?|created?|new)"
# A negator governs everything up to the end of its clause, so the whole span
# it covers is masked before durable-change matching runs. Scrubbing the
# negated phrases as plain substrings instead was wrong twice over:
#   (a) it was order-dependent -- the shorter "no workflow policy" ran before
#       the longer "no workflow policy changed" and deleted its prefix, leaving
#       an orphaned " changed" that then paired with any unrelated noun later
#       in the sentence; and
#   (b) it only ever removed the first item of a coordinated list, so "no A, B,
#       or C changed" left B and C reading as positive assertions of change.
# Masking the negator's clause handles both, and the remaining substring scrub
# (longest phrase first, so no entry can shadow another) still covers the
# reasons that carry no leading negator, such as "mechanical" or "answer-only".
_DURABLE_NEGATOR_RE = re.compile(r"\b(?:no|without)\b")
# Punctuation and contrastive conjunctions end a negated clause. A comma or
# "and"/"or" normally continues a coordinated list inside the same negation,
# but when it introduces a change verb or a new determined subject it starts a
# fresh positive assertion ("not applicable, updated the public contract"),
# which must stay visible to the durable-change patterns.
_DURABLE_NEGATION_END_RE = re.compile(
    r"[.;()\[\]\n]"
    r"|\b(?:but|however|though|although|yet|except|whereas)\b"
    r"|(?:,|\band\b|\bor\b)\s+(?:" + _CHANGE_VERB + r"\b|(?:the|a|an|this|that|we|i)\b)"
)
# Korean negation is post-positional ("동작 변경 없음"), so its scope is masked
# backwards from the negator to the start of the clause.
_DURABLE_KOREAN_NEGATOR_RE = re.compile(r"없(?:음|이|는|다|었|습니다)?")
_DURABLE_KOREAN_CLAUSE_START_RE = re.compile(r"[.;:,()\[\]\n]")


def _mask_negated_spans(text: str) -> str:
    chars = list(text)

    def blank(start: int, end: int) -> None:
        for index in range(start, end):
            chars[index] = " "

    for match in _DURABLE_NEGATOR_RE.finditer(text):
        end_match = _DURABLE_NEGATION_END_RE.search(text, match.end())
        blank(match.start(), end_match.start() if end_match else len(text))
    for match in _DURABLE_KOREAN_NEGATOR_RE.finditer(text):
        clause_start = 0
        for boundary in _DURABLE_KOREAN_CLAUSE_START_RE.finditer(text, 0, match.start()):
            clause_start = boundary.end()
        blank(clause_start, match.end())
    return "".join(chars)


def _has_durable_doc_change_signal(text: str) -> bool:
    searchable = _mask_negated_spans(text)
    for phrase in sorted(NO_DURABLE_DOC_REASONS, key=len, reverse=True):
        searchable = searchable.replace(phrase, "")
    return any(re.search(pattern, searchable) for pattern in DURABLE_DOC_CHANGE_PATTERNS)


PRD_CONTENT_PHRASES = (
    "acceptance criteria", "given", "when", "then",
    "in scope", "out of scope", "actor", "outcome", "user story",
    "states", "open decisions", "desired outcome", "proposed behavior",
    "요구사항", "수용 기준", "범위", "액터", "결과", "수락 기준",
)


def validate_prd_draft_evidence(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_created = has_any(
        text,
        (
            "created", "drafted", "written", "saved", "wrote",
            "file", ".md", "doc path", "path:", "artifact", "document",
            "생성", "작성", "저장", "파일",
        ),
    )
    has_prd_content = has_any(text, PRD_CONTENT_PHRASES)
    if has_created and has_prd_content:
        return []
    return [
        "PRD draft evidence must confirm the PRD was created or drafted (name the file "
        "path or artifact) and include content evidence such as acceptance criteria, "
        "scope, actor/outcome, states, or open decisions"
    ]


IMPLEMENTATION_PROPOSAL_PHRASES = (
    "implementation", "implement", "build the", "roadmap", "backlog",
    "milestone", "phase 1", "phase 2", "next feature", "new feature",
    "task list", "epic", "user story", "deliver the", "build out",
    "구현", "로드맵", "백로그", "기능 추가", "마일스톤", "다음 기능",
)

NO_PROPOSAL_PHRASES = (
    "no implementation", "no new product", "no roadmap", "no backlog",
    "status only", "classification only", "recommendation only",
    "no product work", "triage only", "no feature proposed",
    "no implementation proposed", "no new work proposed",
    "구현 없음", "구현 제안 없음", "제안 없음", "현황만", "분류만", "추천만",
)

PRD_COVERAGE_PHRASES = (
    "accepted prd", "prd coverage", "prd link", "linked prd", "prd:",
    "product route", "product re-entry", "product reentry",
    "re-enter product", "reenter product", "coverage matrix",
    "product 재진입", "prd 커버리지", "prd 링크", "수락된 prd",
)


def validate_product_reentry_evidence(evidence: str) -> list[str]:
    """Force a triage/plan to declare product-route coverage before it can hand
    off implementation work. Either it states no new product/implementation work
    was proposed, or, when it proposes a roadmap/backlog/implementation ordering,
    it must name PRD coverage (an Accepted PRD link or an explicit product-route
    re-entry to create/accept the PRD, plus ARD when structure changes). The
    silent path — proposing implementation without PRD coverage — fails."""
    text = evidence.lower()
    if not text:
        return [
            "product route re-entry evidence is required and cannot be empty: "
            "state whether the triage/plan proposed any new product or "
            "implementation work, and if so name the PRD coverage or product-"
            "route re-entry that must precede implementation"
        ]
    disclaims = has_any(text, NO_PROPOSAL_PHRASES)
    # Strip the disclaimer phrases before scanning for proposal keywords so a
    # negated mention ("no implementation proposed") is not read as a proposal.
    searchable = text
    for phrase in NO_PROPOSAL_PHRASES:
        searchable = searchable.replace(phrase, " ")
    proposes = has_any(searchable, IMPLEMENTATION_PROPOSAL_PHRASES)
    if disclaims and not proposes:
        return []
    if proposes and has_any(text, PRD_COVERAGE_PHRASES):
        return []
    return [
        "product route re-entry evidence must either state that the triage/plan "
        "proposed no new product or implementation work, or, when it proposes "
        "implementation ordering/roadmap/backlog, name the PRD coverage (Accepted "
        "PRD link, or explicit product-route re-entry to create and accept the "
        "PRD, plus an ARD link when structure/module boundaries change) that must "
        "precede any implementation task or PR."
        + accepted(NO_PROPOSAL_PHRASES).replace(
            "accepted wording includes", "a no-proposal disclaimer is recognised on"
        )
    ]


def validate_platform_selection_evidence(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    if ("not applicable" in text or "no platform" in text) and has_any(
        text,
        (
            "because", "reason", "not affected", "docs-only",
            "workflow-only", "no ui", "no runtime", "no platform-specific",
        ),
    ):
        return []
    selected = has_any(
        text,
        (
            "selected platform", "platform:", "platforms:",
            "android", "ios", "swift", "web", "server", "application",
            "flutter", "kmp",
        ),
    )
    docs = has_any(
        text,
        (
            "platform card", "platform cards", "platforms/",
            "android-", "ios-", "swift-", "web-", "server-", "application-",
            "read", "loaded",
        ),
    )
    before_architecture = has_any(
        text,
        (
            "before prd", "before ard", "before architecture",
            "before implementation", "before code", "pre-code", "prd/ard",
        ),
    )
    if selected and docs and before_architecture:
        return []
    return [
        "platform selection evidence must name the selected platform(s) and "
        "platform card/docs read before PRD/ARD/architecture work, or state no "
        "platform is applicable with a reason"
    ]


def validate_review_readiness_evidence(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    if (
        has_any(
            text,
            (
                "review readiness", "readiness", "frontmatter", "status",
                "type", "human-reviewed-needed", "ai-generated", "review queue",
            ),
        )
        and has_any(
            text,
            (
                ".md", "markdown", "docs", "common/", "workflows/",
                "platforms/", "templates/", "product-patterns/",
                "agents.md", "readme", "index.md",
            ),
        )
        and has_any(text, ("count", "counts", "queue", "missing", "malformed", "none", "0", "stable", "review", "risk", "needs", "found"))
    ):
        return []
    return [
        "review readiness evidence must report markdown/frontmatter status/type "
        "readiness or human-review queue results for the reviewed doc scope"
    ]
