"""Start guidance and the review hook's accepted argument shape.

A runtime session can outlive a model's context, and workers can share its
session identifier. Start therefore prints its guidance on every invocation:
the presence of an earlier output file does not prove this agent saw it.
"""

from __future__ import annotations

from typing import Iterable

REVIEW_SCOPE_CHOICES: tuple[str, ...] = (
    "working-tree", "pathspec", "repo-hygiene", "local-config", "commit-range",
)
REVIEW_SCOPES_NEEDING_PATH = frozenset({"pathspec", "local-config"})
REVIEW_RANGE_SCOPE = "commit-range"
STRUCTURE_FLAG = "--structure-review-evidence"


def review_shape_line(required_flags: Iterable[str]) -> str:
    """One line naming the review hook's accepted argument shape."""

    scopes = []
    for scope in REVIEW_SCOPE_CHOICES:
        if scope in REVIEW_SCOPES_NEEDING_PATH:
            scope += " (+--review-path)"
        elif scope == REVIEW_RANGE_SCOPE:
            scope += " (+--review-base/--review-head)"
        scopes.append(scope)
    flags = list(required_flags)
    required = " ".join(f'{flag} "<text>"' for flag in flags)
    structure = "" if STRUCTURE_FLAG in flags else (
        f" [{STRUCTURE_FLAG} \"owner: ...; allowed imports: ...; forbidden imports: ...; "
        "callers/tests: ...; verification: ...\" if changed dev files exceed size limits "
        "or a multi-role package changes]"
    )
    return (
        f"Review shape: review --review-outcome pass|findings {required}{structure} "
        "(evidence text, not a file path); --review-scope "
        + "|".join(scopes) + " (default working-tree)."
    )
