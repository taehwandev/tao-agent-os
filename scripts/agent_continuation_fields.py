"""Bounded field vocabulary shared by every continuation packet object.

The continuation packet is the one Tao record that may legitimately hold a
project fact, so the primitives that decide what a field may contain are
separated from the schema shape that says where those fields appear.  Each
returns stable rule ids and JSON pointers and never echoes the rejected value:
a validation channel that quotes the value would move that fact into logs the
packet's local-only boundary does not cover.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Callable

from agent_execution_capsule_state import is_sha256


MAX_TEXT = 280
MAX_SHORT_TEXT = 160
MAX_PATH_LENGTH = 240
MAX_DEPTH = 5
MAX_PROSE_BYTES = 4 * 1024

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# A gate name is an exact catalog entry and may contain spaces; a checkpoint
# that is not a gate is a safe slug.  Nothing else is a checkpoint.
CHECKPOINT_RE = re.compile(r"^[a-z0-9][a-z0-9 _.-]*$")
FORBIDDEN_PATH_SEGMENTS = frozenset({"", ".", "..", ".git", ".tao"})
# High-confidence credential shapes only.  No validator can prove a
# 280-character sentence holds no secret; pretending otherwise is exactly why
# the packet stays local-only and its prose fields stay few and short.
SECRET_RES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)


def failure(rule: str, pointer: str) -> dict[str, str]:
    return {"rule": rule, "pointer": pointer}


def closed_object(value: dict[str, Any], fields: tuple[str, ...], pointer: str, failures: list) -> None:
    """Reject unknown keys and demand every declared key of a closed object."""

    for key in sorted(set(value) - set(fields)):
        failures.append(failure("unknown_field", f"{pointer}/{key}"))
    for key in fields:
        if key not in value:
            failures.append(failure("missing_field", f"{pointer}/{key}"))


def enum_value(value: Any, allowed: tuple[str, ...], pointer: str, failures: list) -> None:
    if value not in allowed:
        failures.append(failure("invalid_enum", pointer))


def count(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2 ** 53 - 1:
        failures.append(failure("invalid_count", pointer))


def run_id(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, str) or not RUN_ID_RE.match(value):
        failures.append(failure("invalid_run_id", pointer))


def filename(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or not FILENAME_RE.match(value):
        failures.append(failure("invalid_filename", pointer))


def sha256_value(value: Any, pointer: str, failures: list, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not is_sha256(value):
        failures.append(failure("invalid_sha256", pointer))


def timestamp(value: Any, pointer: str, failures: list, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str):
        failures.append(failure("invalid_timestamp", pointer))
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        failures.append(failure("invalid_timestamp", pointer))
        return
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        failures.append(failure("invalid_timestamp", pointer))


def prose(value: Any, pointer: str, failures: list, limit: int) -> None:
    """Accept one short, single-line, NFC sentence, or reject it outright.

    Over-length prose is refused rather than truncated: truncation hides the
    violation the cap exists to catch and quietly changes the meaning of a
    recorded conclusion.
    """

    if not isinstance(value, str):
        failures.append(failure("invalid_type", pointer))
        return
    if not value:
        failures.append(failure("prose_empty", pointer))
        return
    if len(value) > limit:
        failures.append(failure("prose_too_long", pointer))
    if unicodedata.normalize("NFC", value) != value:
        failures.append(failure("prose_not_normalized", pointer))
    if any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in value):
        failures.append(failure("prose_not_single_line", pointer))
    if any(pattern.search(value) for pattern in SECRET_RES):
        failures.append(failure("prose_secret_shaped", pointer))


def slug(value: Any, pointer: str, failures: list, limit: int, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value or len(value) > limit or not SLUG_RE.match(value):
        failures.append(failure("invalid_slug", pointer))


def checkpoint_name(value: Any, pointer: str, failures: list, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not CHECKPOINT_RE.match(value):
        failures.append(failure("invalid_checkpoint", pointer))


def relative_path(value: Any, pointer: str, failures: list) -> None:
    """Reject anything that is not a normalized repo-relative POSIX path."""

    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        failures.append(failure("invalid_path", pointer))
        return
    if (
        value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or ":" in value
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
        or any(segment in FORBIDDEN_PATH_SEGMENTS for segment in value.split("/"))
    ):
        failures.append(failure("invalid_path", pointer))


def items(value: Any, pointer: str, failures: list, limit: int, check: Callable[[Any, str], None]) -> None:
    if not isinstance(value, list):
        failures.append(failure("invalid_type", pointer))
        return
    if len(value) > limit:
        failures.append(failure("too_many_items", pointer))
    for index, item in enumerate(value[:limit]):
        check(item, f"{pointer}/{index}")


def depth(value: Any, level: int = 1) -> int:
    if isinstance(value, dict):
        return max((depth(item, level + 1) for item in value.values()), default=level)
    if isinstance(value, list):
        return max((depth(item, level + 1) for item in value), default=level)
    return level
