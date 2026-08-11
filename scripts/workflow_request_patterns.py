"""Patterns for question handling and explicit Grill-Me requests only."""

from __future__ import annotations


DIRECT_QUESTION_PATTERNS = (
    r"\?",
    r"\b(what|when|where|why|how|which|who|should|do i|does|is|are|can i)\b",
    "언제", "무엇", "뭐", "어떻게", "왜", "어디", "어느", "누가",
    "인가", "맞아", "거야", "건가", "나요", "합니까", "할까",
)

QUESTION_ACTION_PATTERNS = (
    r"\b(can you|could you|would you|please|go ahead and)\b",
    "해줘", "해주세요", "해줄래", "바꿔줘", "고쳐줘", "수정해줘",
    "적용해줘", "추가해줘", "명시해줘", "넣어줘", "담아줘", "작성하자",
    r"작성\s*다시\s*하자", r"다시\s*(작성|쓰|정리)하자", "정리하자",
    "적용", "다시 적용", "커밋해줘", "푸쉬해줘", "실행해줘", "만들어줘",
    "구성해줘", r"(해보자|진행해줘|파악해줘|파악좀)",
)

IMPERATIVE_CORRECTION_ACTION_PATTERNS = (
    r"(?:^|[.!?;,]\s*)(?:please\s+|just\s+)?"
    r"(?:fix|correct|redo|revise|repair|rework)\b",
)

_CORRECTION_VERB = r"(?:fix|correct|redo|revise|repair|rework|rewrite|refactor)"
_CORRECTION_META_NOUN = r"(?:behavior|word|term|label|concept|name|phrase)"
_CORRECTION_NAMING_VERB = (
    r"(?:is|are|was|were|mean(?:s|ing)?|denot(?:es?|ing)|signif(?:ies|ying)|"
    r"impl(?:ies|ying)|refer(?:s|ring)?\s+to|stand(?:s|ing)?\s+for|"
    r"sound(?:s|ing)?|read(?:s|ing)?)"
)

CORRECTION_WORD_SENSE_QUESTION_PATTERNS = (
    r"^correct\s+me\s+if\s+i(?:(?:'|’)m|\s+am)\s+wrong\b",
    r"^correct\s+or\s+incorrect\b",
    r"^" + _CORRECTION_VERB + r"\b"
    r"(?:\s+" + _CORRECTION_META_NOUN + r")?"
    r"(?:\s*,[^,]{0,40},|\s+(?:as|in)\b[^,?!]{0,40})?"
    r"\s*,?\s+" + _CORRECTION_NAMING_VERB + r"\b",
    r"^" + _CORRECTION_VERB + r"\b"
    r"(?:\s+" + _CORRECTION_META_NOUN + r")?"
    r"\s*,?\s*(?:as|in)\b[^,?!]{0,40},\s*"
    r"(?:what|which|how)\b[^?]{0,40}?\b"
    r"(?:it|that|this|the\s+(?:behavior|word|term|label|concept|name|phrase))\s+"
    + _CORRECTION_NAMING_VERB + r"\b[^?]*\?",
    r"^" + _CORRECTION_VERB + r"\s*(?:/|and|or|vs\.?|versus)\s*"
    + _CORRECTION_VERB + r"\b",
    r"^" + _CORRECTION_VERB + r"\s*[:;?!—–-]+\s*"
    r"(?:what|which|how|why|when|is|are|was|were|does|do|did|should|would|can)\b"
    r"[^.]{0,60}?(?:\b" + _CORRECTION_NAMING_VERB + r"\b|\b"
    + _CORRECTION_META_NOUN + r"\b)[^.]*\?",
)

GRILL_ME_REQUEST_PATTERNS = (
    r"\bgrill me\b",
    r"\b(run|use|invoke|start|do)\s+(the\s+)?grill[- ]?me\b",
    r"\bgrill[- ]?me\s+(this|me|my|us|please)\b",
    r"\bask me questions\b",
    r"\bhelp define requirements\b",
    r"\bquestion drill\b",
    r"그릴미\s*(해줘|해주세요|해|하자|돌려|실행|써|질문)",
)

DRILL_PHRASES = GRILL_ME_REQUEST_PATTERNS


PRIOR_COMPLETION_REFERENCE_PATTERNS = (
    r"\b(?:previously|earlier|just)\s+(?:completed|finished|reported|delivered)"
    r"\s+(?:result|work|change|implementation|answer|output)\b",
    r"\b(?:result|work|change|implementation|answer|output)\s+"
    r"(?:you|we|the\s+agent)\s+(?:just\s+)?"
    r"(?:completed|finished|reported|delivered)\b",
    r"\b(?:completed|finished|reported|delivered)\s+"
    r"(?:result|work|change|implementation|answer|output)\b",
    r"(?:방금|아까|이전(?:에)?|저번(?:에)?|지난번(?:에)?)\s*"
    r"(?:완료한|완료했던|끝낸|끝냈던|마친|마쳤던)\s*"
    r"(?:작업|결과|수정|구현|답변)",
    r"(?:완료한|완료했던|끝낸|끝냈던|마친|마쳤던)\s*"
    r"(?:작업|결과|수정|구현|답변)",
)

COMPLETION_FAILURE_PATTERNS = (
    r"\b(?:wrong|incorrect|mistake|broken|failed|incomplete|missing|omitted)\b",
    r"(?:잘못|틀렸|실수|오류|깨졌|빠졌|누락|미완성)",
)

CORRECTION_ACTION_PATTERNS = (
    r"\b(?:fix|correct|redo|revise|repair|rework)\b",
    r"(?:고쳐|수정|바로잡|재작업|다시\s*(?:해|하|고쳐|수정|작성|구현))",
)

EXACT_PATTERNS = (
    r"`[^`]+`",
    r"(?:^|\s)(?:~/|\.{1,2}/|/)[A-Za-z0-9_./-]+",
    r"\b[\w./-]+\.(kt|swift|tsx|ts|jsx|js|py|go|rs|java|md|json|yml|yaml|toml)\b",
    r":\d+\b",
    r"\b(error|exception|traceback|stack trace|compiler|lint|test failed|failing test)\b",
    r"\b(nullpointer|typeerror|referenceerror|syntaxerror|segmentation fault)\b",
)

SCOPED_PATTERNS = (
    r"\b[A-Z][A-Za-z0-9]*(Screen|View|ViewModel|Controller|Route|Page|Component|Service|Repository|UseCase)",
    r"\b(home|settings|profile|checkout|billing|invite|member|login|signup)\b.*\b(button|form|screen|page|modal|dialog|tab)\b",
)

INSPECTION_PATTERNS = (
    r"\b(audit|review|inspect|check|verify|status|summarize|report)\b",
    "상태",
    "점검",
    "검토",
    "확인",
    "체크",
    "파악",
    "정리",
)

REFACTOR_ACTION_PATTERNS = (
    r"\b(refactor|cleanup|clean up|clean-up|simplify)\b",
    r"\bcode\b.*\b(clean|cleanup|simplify)\b",
    "코드.*정리",
    "리팩터",
    "단순화",
)

REVIEW_ACTION_PATTERNS = (
    r"\b(review|inspect|check|verify)\b.*\b(diff|changes?|patch|working tree|worktree)\b",
    r"\b(diff|changes?|patch|working tree|worktree)\b.*\b(review|inspect|check|verify)\b",
    "변경사항.*(검토|확인|체크)",
    "작업.*(검토|확인|체크)",
)

RELEASE_ACTION_PATTERNS = (
    r"\b(deploy|deployment|release|publish|ship|tag|push)\b",
    r"\bgithub release\b",
    r"\bappcast\b",
    "배포",
    "릴리스",
    "푸쉬",
    "태그",
)

TEST_ACTION_PATTERNS = (
    r"\b(run|execute)\s+(tests?|checks?)\b",
    r"\bverification\s+only\b",
    r"\bverify\b.*\b(tests?|checks?)\b",
    "테스트.*(실행|검증|확인)",
    "검증만",
)

WORKFLOW_SETUP_ACTION_PATTERNS = (
    r"\b(natural language|semantic)\b.*\b(search|routing|retrieval|docs?|documents?|skills?)\b",
    r"\b(doc routing|document routing|doc-route|route docs|required docs)\b",
    r"\b(hook|hooks?)\b.*\b(docs?|documents?|search|read|routing)\b",
    r"\b(planning|requirements?|acceptance criteria)\b.*\b(docs?|documentation)\b.*\b(missing|omitted|skipped|forgotten|enforce|gate|guard)\b",
    r"\b(docs?|documentation)\b.*\b(missing|omitted|skipped|forgotten|enforce|gate|guard)\b.*\b(planning|requirements?|acceptance criteria)\b",
    r"(자연어|의미).*(검색|문서|라우팅)",
    r"(문서|스킬).*(검색|라우팅|불러|읽)",
    r"(훅|hook).*(문서|검색|읽|라우팅)",
    r"(기획|요구사항|요건|수용\s*기준).*(문서).*(빠지|누락|생략|막|강제)",
    r"(문서).*(빠지|누락|생략|막|강제).*(기획|요구사항|요건|수용\s*기준)",
)

UI_FEATURE_ACTION_PATTERNS = (
    r"\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b.*\b(build|create|implement|compose|design|add|make)\b",
    r"\b(build|create|implement|compose|design|add|make)\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b",
    r"\b(android|ios|web|app)\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b",
    "(안드로이드|android).*(화면|목록|리스트|즐겨찾기|탭|네비|내비)",
    "(화면|목록|리스트|즐겨찾기|탭|네비|내비).*(구성|구현|만들|작성|추가|짜줘)",
    "(첫|1|one).*화면.*(두|2|two).*화면",
    "(compose|컴포즈).*(screen|ui|화면|작성|구성|구현)",
)

BROAD_PATTERNS = (
    r"\b(build|implement|design|create|add|plan)\b.*\b(feature|flow|system|architecture|prd|ard|product)\b",
    r"\b(auth|rbac|permission|billing|entitlement|invite|tenant|migration|release|deployment)\b",
    r"(앱|기능|화면|제품|플로우|서비스).{0,10}(만들|만드|구현|설계|추가|작업|진행)|prd|ard|요구사항|아키텍처",
)

RISKY_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|deploy|release|publish|payment|billing|secret|token|credential|permission|security|tenant)\b",
)

VAGUE_PATTERNS = (
    r"\b(fix|improve|clean up|make better|change|update|adjust|modify)\b",
    r"\b(rewrite|rework|revise|redraft|rephrase|polish|tighten)\b",
    r"\b(button|home|screen|ui|layout|style)\b",
    r"다시\s*(작성|쓰|정리)",
    r"작성\s*다시",
    "재작성",
    "문체",
    "말투",
    "어투",
    "스타일",
    "내 스타일",
    "존대",
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

MUTATION_ACTION_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|does not|doesn't|never|won't|will not|should not|"
    r"shouldn't|must not|mustn't|cannot|can't)\s+(?:\w+\s+){0,2}"
    r"(?:commit|push|merge|release|deploy|publish|tag)\b",
    r"\b(?:commit|push|merge|release|deploy|publish|tag)"
    r"(?:\s*(?:/|,|·|\band\b)\s*"
    r"(?:commit|push|merge|release|deploy|publish|tag))*"
    r"(?:은|는|을|를)?\s*"
    r"(?:하지\s*(?:않|마)|안\s*(?:하|해|함|한다|합니다)|"
    r"(?:하면|해서는)\s*안|금지)",
)

COMMIT_RELEASE_SUBSTEP_PATTERNS = (
    r"\b(first|before|current|pending|staged|working tree|worktree|warning cleanup)\b",
    r"\bbefore\s+(?:continuing|release|deploy|publishing|tagging)\b",
    r"\bcommit\b.*\b(?:then|next|after)\b",
    r"\b(?:release|deploy|publish|tag)\b.*\b(?:after|once)\b.*\bcommit\b",
    r"\b(먼저|우선|현재|순서대로)\b",
)

COMMIT_BLOCKING_RISK_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|payment|billing|secret|token|credential|permission|security|tenant)\b",
    r"\b(force[- ]?push|reset|rebase|amend)\b",
    r"\b(삭제|마이그레이션|비밀|secret|token|credential|권한|보안)\b",
)

RELEASE_BLOCKING_RISK_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|payment|billing|secret|token|credential|permission|security|tenant)\b",
    r"\b(삭제|마이그레이션|비밀|secret|token|credential|권한|보안)\b",
)

RELEASE_SCOPE_SIGNAL_PATTERNS = (
    (
        r"\b(?:v)?\d{2,4}\.\d{1,2}\.\d+(?:[-+][A-Za-z0-9.-]+)?\b",
        r"\bversion\b",
        r"\brelease candidate\b",
        "버전",
    ),
    (
        r"\b(?:source revision|commit|sha|head|main|branch|develop|tag target|peeled target)\b",
        r"\b[0-9a-f]{7,40}\b",
        "커밋",
        "소스",
        "발송분",
    ),
    (
        r"\b(?:artifact|package|build|app|apk|aab|ipa|binary|dmg|zip|installer|bundle|appcast)\b",
        "산출물",
        "패키지",
        "앱",
    ),
    (
        # The destination of a release. Korean sat only in RELEASE_ACTION_PATTERNS,
        # so a Korean request named the action but could never name where it went,
        # and the two-signal rule then read a real deploy as an unclear ask.
        r"\b(?:push|publish|github release|remote|origin|tag|deploy|distribution|app distribution|firebase|testflight|play console|release workflow)\b",
        "원경",
        "푸쉬",
        "태그",
        "게시",
        "배포",
        "테스터",
    ),
    (
        r"\b(?:verify|verification|test|build|smoke|package|sign|signed|notary|notarize|rollback|forward-fix)\b",
        "검증",
        "테스트",
        "바일드",
        "롤백",
        "무새집",
    ),
)

# A short approval can be a valid continuation of an already settled discussion.
# Keep this deliberately narrow: it must contain a referential cue ("then/that/this"
# or the Korean equivalent) and an explicit action approval. Bare "do it" requests
# remain vague and continue to require triage.
FOLLOW_UP_APPROVAL_PATTERNS = (
    r"^(?:then|so|in that case|that|this)\b.{0,120}\b(?:fix|change|edit|apply|implement|proceed|continue|go ahead)\b",
    r"^(?:아하\s*)?(?:그럼|그러면|그렇다면|그 부분|그건|이건|이렇게)\s*.{0,120}(?:수정|변경|적용|반영|구현|진행|해줘|해주세요|할게)",
)
