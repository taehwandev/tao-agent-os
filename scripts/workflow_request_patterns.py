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
