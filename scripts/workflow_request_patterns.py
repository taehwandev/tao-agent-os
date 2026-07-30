"""Regex patterns used by workflow request classification."""

from __future__ import annotations


DIRECT_QUESTION_PATTERNS = (
    r"\?",
    r"\b(what|when|where|why|how|which|who|should|do i|does|is|are|can i)\b",
    "\uc5b8\uc81c",
    "\ubb34\uc5c7",
    "\ubb50",
    "\uc5b4\ub5bb\uac8c",
    "\uc65c",
    "\uc5b4\ub514",
    "\uc5b4\ub290",
    "\ub204\uac00",
    "\uc778\uac00",
    "\ub9de\uc544",
    "\uac70\uc57c",
    "\uac74\uac00",
    "\ub098\uc694",
    "\ud569\ub2c8\uae4c",
    "\ud560\uae4c",
)
QUESTION_ACTION_PATTERNS = (
    r"\b(can you|could you|would you|please|go ahead and)\b",
    "\ud574\uc918",
    "\ud574\uc8fc\uc138\uc694",
    "\ud574\uc904\ub798",
    "\ubc14\uafd4\uc918",
    "\uace0\uccd0\uc918",
    "\uc218\uc815\ud574\uc918",
    "\uc801\uc6a9\ud574\uc918",
    "\ucd94\uac00\ud574\uc918",
    "\uba85\uc2dc\ud574\uc918",
    "\ub123\uc5b4\uc918",
    "\ub2f4\uc544\uc918",
    "\uc791\uc131\ud558\uc790",
    r"\uc791\uc131\s*\ub2e4\uc2dc\s*\ud558\uc790",
    r"\ub2e4\uc2dc\s*(\uc791\uc131|\uc4f0|\uc815\ub9ac)\ud558\uc790",
    "\uc815\ub9ac\ud558\uc790",
    "\uc801\uc6a9",
    "\ub2e4\uc2dc \uc801\uc6a9",
    "\ucee4\ubc0b\ud574\uc918",
    "\ud478\uc26c\ud574\uc918",
    "\uc2e4\ud589\ud574\uc918",
    "\ub9cc\ub4e4\uc5b4\uc918",
    "\uad6c\uc131\ud574\uc918",
    r"(\ud574\ubcf4\uc790|\uc9c4\ud589\ud574\uc918|\ud30c\uc545\ud574\uc918|\ud30c\uc545\uc880)",
)
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
IMPERATIVE_CORRECTION_ACTION_PATTERNS = (
    r"(?:^|[.!?;,]\s*)(?:please\s+|just\s+)?"
    r"(?:fix|correct|redo|revise|repair|rework)\b",
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
    "\uc0c1\ud0dc",
    "\uc810\uac80",
    "\uac80\ud1a0",
    "\ud655\uc778",
    "\uccb4\ud06c",
    "\ud30c\uc545",
    "\uc815\ub9ac",
)
REFACTOR_ACTION_PATTERNS = (
    r"\b(refactor|cleanup|clean up|clean-up|simplify)\b",
    r"\bcode\b.*\b(clean|cleanup|simplify)\b",
    "\ucf54\ub4dc.*\uc815\ub9ac",
    "\ub9ac\ud329\ud130",
    "\ub2e8\uc21c\ud654",
)
REVIEW_ACTION_PATTERNS = (
    r"\b(review|inspect|check|verify)\b.*\b(diff|changes?|patch|working tree|worktree)\b",
    r"\b(diff|changes?|patch|working tree|worktree)\b.*\b(review|inspect|check|verify)\b",
    "\ubcc0\uacbd\uc0ac\ud56d.*(\uac80\ud1a0|\ud655\uc778|\uccb4\ud06c)",
    "\uc791\uc5c5.*(\uac80\ud1a0|\ud655\uc778|\uccb4\ud06c)",
)
RELEASE_ACTION_PATTERNS = (
    r"\b(deploy|deployment|release|publish|ship|tag|push)\b",
    r"\bgithub release\b",
    r"\bappcast\b",
    "\ubc30\ud3ec",
    "\ub9b4\ub9ac\uc2a4",
    "\ud478\uc26c",
    "\ud0dc\uadf8",
)
TEST_ACTION_PATTERNS = (
    r"\b(run|execute)\s+(tests?|checks?)\b",
    r"\bverification\s+only\b",
    r"\bverify\b.*\b(tests?|checks?)\b",
    "\ud14c\uc2a4\ud2b8.*(\uc2e4\ud589|\uac80\uc99d|\ud655\uc778)",
    "\uac80\uc99d\ub9cc",
)
WORKFLOW_SETUP_ACTION_PATTERNS = (
    r"\b(natural language|semantic)\b.*\b(search|routing|retrieval|docs?|documents?|skills?)\b",
    r"\b(doc routing|document routing|doc-route|route docs|required docs)\b",
    r"\b(hook|hooks?)\b.*\b(docs?|documents?|search|read|routing)\b",
    r"\b(planning|requirements?|acceptance criteria)\b.*\b(docs?|documentation)\b.*\b(missing|omitted|skipped|forgotten|enforce|gate|guard)\b",
    r"\b(docs?|documentation)\b.*\b(missing|omitted|skipped|forgotten|enforce|gate|guard)\b.*\b(planning|requirements?|acceptance criteria)\b",
    r"(\uc790\uc5f0\uc5b4|\uc758\ubbf8).*(\uac80\uc0c9|\ubb38\uc11c|\ub77c\uc6b0\ud305)",
    r"(\ubb38\uc11c|\uc2a4\ud0ac).*(\uac80\uc0c9|\ub77c\uc6b0\ud305|\ubd88\ub7ec|\uc77d)",
    r"(\ud6c5|hook).*(\ubb38\uc11c|\uac80\uc0c9|\uc77d|\ub77c\uc6b0\ud305)",
    r"(\uae30\ud68d|\uc694\uad6c\uc0ac\ud56d|\uc694\uac74|\uc218\uc6a9\s*\uae30\uc900).*(\ubb38\uc11c).*(\ube60\uc9c0|\ub204\ub77d|\uc0dd\ub7b5|\ub9c9|\uac15\uc81c)",
    r"(\ubb38\uc11c).*(\ube60\uc9c0|\ub204\ub77d|\uc0dd\ub7b5|\ub9c9|\uac15\uc81c).*(\uae30\ud68d|\uc694\uad6c\uc0ac\ud56d|\uc694\uac74|\uc218\uc6a9\s*\uae30\uc900)",
)
UI_FEATURE_ACTION_PATTERNS = (
    r"\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b.*\b(build|create|implement|compose|design|add|make)\b",
    r"\b(build|create|implement|compose|design|add|make)\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b",
    r"\b(android|ios|web|app)\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab)\b",
    "(\uc548\ub4dc\ub85c\uc774\ub4dc|android).*(\ud654\uba74|\ubaa9\ub85d|\ub9ac\uc2a4\ud2b8|\uc990\uaca8\ucc3e\uae30|\ud0ed|\ub124\ube44|\ub0b4\ube44)",
    "(\ud654\uba74|\ubaa9\ub85d|\ub9ac\uc2a4\ud2b8|\uc990\uaca8\ucc3e\uae30|\ud0ed|\ub124\ube44|\ub0b4\ube44).*(\uad6c\uc131|\uad6c\ud604|\ub9cc\ub4e4|\uc791\uc131|\ucd94\uac00|\uc9dc\uc918)",
    "(\uccab|1|one).*\ud654\uba74.*(\ub450|2|two).*\ud654\uba74",
    "(compose|\ucef4\ud3ec\uc988).*(screen|ui|\ud654\uba74|\uc791\uc131|\uad6c\uc131|\uad6c\ud604)",
)
BROAD_PATTERNS = (
    r"\b(build|implement|design|create|add|plan)\b.*\b(feature|flow|system|architecture|prd|ard|product)\b",
    r"\b(auth|rbac|permission|billing|entitlement|invite|tenant|migration|release|deployment)\b",
    r"(\uc571|\uae30\ub2a5|\ud654\uba74|\uc81c\ud488|\ud50c\ub85c\uc6b0|\uc11c\ube44\uc2a4).{0,10}(\ub9cc\ub4e4|\ub9cc\ub4dc|\uad6c\ud604|\uc124\uacc4|\ucd94\uac00|\uc791\uc5c5|\uc9c4\ud589)|prd|ard|\uc694\uad6c\uc0ac\ud56d|\uc544\ud0a4\ud14d\ucc98",
)
RISKY_PATTERNS = (
    r"\b(delete|drop|destroy|migrate|deploy|release|publish|payment|billing|secret|token|credential|permission|security|tenant)\b",
)
VAGUE_PATTERNS = (
    r"\b(fix|improve|clean up|make better|change|update|adjust|modify)\b",
    r"\b(rewrite|rework|revise|redraft|rephrase|polish|tighten)\b",
    r"\b(button|home|screen|ui|layout|style)\b",
    r"\ub2e4\uc2dc\s*(\uc791\uc131|\uc4f0|\uc815\ub9ac)",
    r"\uc791\uc131\s*\ub2e4\uc2dc",
    "\uc7ac\uc791\uc131",
    "\ubb38\uccb4",
    "\ub9d0\ud22c",
    "\uc5b4\ud22c",
    "\uc2a4\ud0c0\uc77c",
    "\ub0b4 \uc2a4\ud0c0\uc77c",
    "\uc874\ub300",
)
GRILL_ME_REQUEST_PATTERNS = (
    r"\bgrill me\b",
    r"\b(run|use|invoke|start|do)\s+(the\s+)?grill[- ]?me\b",
    r"\bgrill[- ]?me\s+(this|me|my|us|please)\b",
    r"\bask me questions\b",
    r"\bhelp define requirements\b",
    r"\bquestion drill\b",
    r"\uadf8\ub9b4\ubbf8\s*(\ud574\uc918|\ud574\uc8fc\uc138\uc694|\ud574|\ud558\uc790|\ub3cc\ub824|\uc2e4\ud589|\uc368|\uc9c8\ubb38)",
)

DRILL_PHRASES = GRILL_ME_REQUEST_PATTERNS
