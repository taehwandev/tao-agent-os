"""Shared constants and helpers for workflow routing."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, TypeVar


ROOT = Path(__file__).resolve().parents[1]
QUESTION_ROUTE_COMMANDS = {"triage", "ambiguity"}
# Question routes do not claim work authority, while compact start already
# binds the exact request for a bounded small change. Neither needs a second
# human-authored request-intake ledger entry.
REQUEST_INTAKE_EXEMPT_COMMANDS = QUESTION_ROUTE_COMMANDS | {"small-change"}
ANSWER_ONLY_CLARITY = "direct-question"
REPAIR_CYCLE_LIMIT = 1
REPAIR_POLICY = "retrospective_repair_verify_resume"
RESUME_SCOPE = "first_failed_checkpoint"
REPAIR_STOP_CONDITION = "same_failure_after_repair_or_unsafe_repair"
SIGNAL_DISPLAY = {
    "SUCCESS": "\U0001f431\U0001f7e2 SUCCESS",
    "FAIL": "\U0001f431\U0001f534 FAIL",
}

T = TypeVar("T")


def unique(items: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    result: list[T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def display_signal(signal: object) -> str:
    return SIGNAL_DISPLAY.get(str(signal), str(signal))
