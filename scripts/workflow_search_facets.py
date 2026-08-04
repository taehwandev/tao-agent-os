"""Natural-language query facets for Tao Agent OS document search."""

from __future__ import annotations

import re
from typing import Iterable, Sequence


FACET_BOOST = 30

QUERY_FACETS: tuple[dict[str, object], ...] = (
    {
        "name": "code_cleanup",
        "patterns": (
            r"\b(refactor|cleanup|clean up|clean-up|simplify)\b",
            r"\bcode\b.*\b(clean|cleanup|simplify)\b",
            r"코드.*정리", r"리팩터", r"단순화",
        ),
        "terms": ("refactor", "cleanup", "simplification", "behavior-preserving", "ownership", "equivalence", "verification", "testing"),
        "docs": ("workflows/skills/refactor-cleanup/SKILL.md", "common/skills/refactoring/SKILL.md", "common/skills/code-structure-ownership/SKILL.md", "common/skills/testing/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    },
    {
        "name": "change_review",
        "patterns": (
            r"\b(review|inspect|check|verify)\b.*\b(diff|changes?|patch|working tree|worktree|work)\b",
            r"\b(diff|changes?|patch|working tree|worktree)\b.*\b(review|inspect|check|verify)\b",
            r"변경사항.*(검토|확인|체크)", r"작업.*(검토|확인|체크)",
        ),
        "terms": ("review", "diff", "risk", "verification", "worktree", "commit readiness"),
        "docs": ("workflows/skills/review-and-commit/SKILL.md", "workflows/skills/multi-perspective-review/SKILL.md", "common/skills/code-review/SKILL.md", "common/skills/worktree-hygiene/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    },
    {
        "name": "verification",
        "patterns": (r"\b(run|execute)\s+(tests?|checks?)\b", r"\bverify\b.*\b(tests?|checks?)\b", r"\bverification\b", r"테스트.*(실행|검증|확인)", r"검증"),
        "terms": ("testing", "scenario", "verification", "evidence", "definition of done"),
        "docs": ("common/skills/testing/SKILL.md", "common/skills/scenario-driven-testing/SKILL.md", "common/skills/verification-policy/SKILL.md", "common/skills/definition-of-done/SKILL.md"),
    },
    {
        "name": "android_compose_ui",
        "patterns": (
            r"\bandroid\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab|compose)\b",
            r"\bcompose\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites)\b",
            r"(안드로이드|android).*(화면|목록|리스트|즐겨찾기|탭|네비|내비|컴포즈)",
            r"(compose|컴포즈).*(screen|ui|화면|작성|구성|구현)",
        ),
        "terms": ("android", "compose", "screen", "state", "viewmodel", "ui", "preview", "performance"),
        "docs": (
            "platforms/android/skills/android-compose-ui/SKILL.md", "platforms/android/skills/android-module-structure/SKILL.md",
            "platforms/android/skills/android-viewmodel-state/SKILL.md", "platforms/android/skills/android-state-data/SKILL.md",
            "platforms/android/skills/android-review/SKILL.md", "platforms/android/skills/android-external-skill-source-coverage/SKILL.md",
            "platforms/android/skills/source-coverage/references/compose-performance-source-map.md",
        ),
    },
    {
        "name": "web_service_rn_python",
        "patterns": (
            r"\bweb\s*service\b.*\b(react native|rn|python|fastapi|react)\b",
            r"\b(react native|rn|python|fastapi|react)\b.*\bweb\s*service\b",
            r"(?=.*\b(react native|rn|expo)\b)(?=.*\breact\b)(?=.*\b(python|fastapi)\b)(?=.*\b(skill|skills|pack|card)\b)",
            r"\breact native\b", r"\bfastapi\b",
            r"(웹\s*서비스|웹서비스).*(리액트\s*네이티브|파이썬|패스트api|react|리액트)",
            r"(리액트\s*네이티브|파이썬|패스트api|react|리액트).*(웹\s*서비스|웹서비스)",
            r"(?=.*(리액트\s*네이티브|리액트네이티브|RN|Expo))(?=.*(파이썬|패스트api|Python|FastAPI))(?=.*(스킬|카드|팩|pack))",
        ),
        "terms": ("react", "react native", "python", "fastapi", "web service", "api", "branch router", "source map"),
        "docs": (
            "common/skills/web-service-rn-python/SKILL.md",
            "platforms/react-native/skills/react-native-app/SKILL.md",
            "platforms/python/skills/python-web-service/SKILL.md",
            "platforms/web/skills/web-react-ui/SKILL.md",
            "platforms/server/skills/server-api-implementation/SKILL.md",
        ),
    },
    {
        "name": "ui_feature",
        "patterns": (
            r"\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab|page|component)\b.*\b(build|create|implement|design|add|make)\b",
            r"\b(build|create|implement|design|add|make)\b.*\b(screen|screens|ui|layout|list|lists|favorite|favorites|navigation|tab|page|component)\b",
            r"(화면|목록|리스트|즐겨찾기|탭|네비|내비).*(구성|구현|만들|작성|추가|짜줘)",
            r"(첫|1|one).*화면.*(두|2|two).*화면",
        ),
        "terms": ("ui", "screen", "state", "structure", "review", "visual verification", "performance"),
        "docs": ("common/skills/ui-visual-verification/SKILL.md", "common/skills/performance-verification/SKILL.md", "platforms/web/skills/web-react-ui/SKILL.md", "platforms/web/skills/web-state-data/SKILL.md", "platforms/flutter/skills/flutter-widget-ui/SKILL.md", "platforms/ios/skills/ios-swiftui-ui/SKILL.md", "platforms/kmp/skills/kmp-compose-ui/SKILL.md", "platforms/application/skills/application-command-ui/SKILL.md"),
    },
    {
        "name": "skill_docs",
        "patterns": (
            r"\b(skill cards?|skill docs?|skill anatomy|agent skills?|skill bundles?|SKILL\.md|references?)\b",
            r"\b(source[- ]of[- ]truth|duplicate|dedupe|fragmented|misplaced|canonical)\b.*\b(skills?|docs?|documents?|references?)\b",
            r"스킬\s*문서",
            r"스킬\s*카드",
            r"(스킬|references?|레퍼런스).*(구조|폴더|중복|파편|위치|source-of-truth)",
        ),
        "terms": ("skill", "card", "bundle", "references", "canonical", "duplicate", "anatomy", "progressive disclosure", "source"),
        "docs": (
            "common/skills/agent-skill-card-anatomy/SKILL.md",
            "docs/skills/tao-skill-bundle-migration/SKILL.md",
            "workflows/skills/documentation-update/SKILL.md",
            "common/skills/source-driven-development/SKILL.md",
        ),
    },
    {
        "name": "natural_language_doc_routing",
        "patterns": (
            r"\b(natural language|semantic|document routing|doc routing|doc-route|route docs|required docs|hook|hooks?)\b",
            r"\b(search|retrieval)\b.*\b(docs?|documents?|skills?)\b",
            r"(자연어|의미).*(검색|문서|라우팅)",
            r"(문서|스킬).*(검색|라우팅|불러|읽)",
            r"(훅|hook).*(문서|검색|읽)",
        ),
        "terms": ("workflow", "routing", "required docs", "reference docs", "source-driven", "task intake", "skill card"),
        "docs": ("workflows/skills/scripted-agent-workflow/SKILL.md", "workflows/skills/agent-task-lifecycle/SKILL.md", "common/skills/task-intake-effort-routing/SKILL.md", "common/skills/source-driven-development/SKILL.md", "common/skills/agent-skill-card-anatomy/SKILL.md", "common/skills/tool-failure-recovery/SKILL.md"),
    },
)


def query_terms(query: str) -> tuple[list[str], list[str], list[str], dict[str, int]]:
    normalized = " ".join(query.strip().split())
    raw_terms = tokenize(normalized)
    expanded_terms: list[str] = []
    matched_facets: list[str] = []
    doc_boosts: dict[str, int] = {}

    for facet in QUERY_FACETS:
        patterns = tuple(str(pattern) for pattern in facet.get("patterns", ()))
        if not any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            continue
        name = str(facet["name"])
        matched_facets.append(name)
        expanded_terms.extend(tokenize(" ".join(str(term) for term in facet.get("terms", ()))))
        for doc in facet_docs(name):
            doc_boosts[doc] = doc_boosts.get(doc, 0) + FACET_BOOST

    return raw_terms, dedupe(expanded_terms), matched_facets, doc_boosts


def facet_docs(name: str) -> set[str]:
    for facet in QUERY_FACETS:
        if facet.get("name") == name:
            return {str(doc) for doc in facet.get("docs", ())}
    return set()


def tokenize(text: str) -> list[str]:
    return dedupe(t.lower() for t in re.split(r"[\s,/|()]+", text.strip()) if t)


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
