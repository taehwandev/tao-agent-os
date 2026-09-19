"""Conservative document-platform hints, never intake or action authority."""

from __future__ import annotations

import re


_NAMES = {
    "android": r"(?<![\w/])(?:android|안드로이드)(?![a-z_/])",
    "ios": r"(?<![\w/])ios(?![a-z_/])",
    "swift": r"(?<![\w/])(?:swift|macos|mac os|맥os)(?![a-z_/])",
    "kmp": r"(?<![\w/])(?:kmp|kotlin multiplatform)(?![a-z_/])",
    "flutter": r"(?<![\w/])(?:flutter|플러터)(?![a-z_/])",
    "web": r"(?<![\w/])(?:web|웹)(?![a-z_/])",
}
_SCOPE = r"\s*(?:의\s*)?(?:앱|코드|모듈|프로젝트|서비스|app\b|code\b|module\b|project\b|service\b)"
_UNCERTAIN = r"\b(?:maybe|perhaps|possibly|whether)\b|일지도|인지\s*(?:모르|불명)|아마"
_NEGATIVE = (
    r"\b(?:not|no|never|don't|unrelated|exclude|excluding|except|without)\b|"
    r"아니|제외|무관|관련\s*없|말고|않|금지|하지\s*마|건드리지\s*마"
)
_BEHAVIOR_PRESERVATION = (
    r"\bwithout\s+changing\s+(?:the\s+)?(?:existing\s+)?behaviou?r\b|"
    r"(?:기존\s*)?동작(?:은|을)?\s*바꾸지\s*않고"
)


def infer_platform(request: str, continuation_scope: str = "") -> str | None:
    """Select only one explicitly scoped platform, abstaining on mixed targets.

    This does not inspect repository names, paths, or classification evidence.
    Continuation can supply a document topic only; the caller must validate
    current intake independently before using this hint.
    """
    text = f"{request}\n{continuation_scope}".lower()
    mentions = {
        platform for platform, name in _NAMES.items() if re.search(name, text)
    }
    if len(mentions) != 1:
        return None
    platform = next(iter(mentions))
    name = _NAMES[platform]
    for clause in re.split(r"[.!?;\n]", text):
        if not re.search(name, clause):
            continue
        # A behavior-preservation constraint does not exclude its platform.
        # Remove only that bounded phrase; other exclusions still veto the hint.
        scope_clause = re.sub(_BEHAVIOR_PRESERVATION, "", clause)
        if re.search(_NEGATIVE, scope_clause) or re.search(_UNCERTAIN, scope_clause):
            return None
    return platform if re.search(name + _SCOPE, text) else None
