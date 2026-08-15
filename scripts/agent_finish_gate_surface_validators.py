"""Finish validation for evidence-first work-surface resolution."""

from __future__ import annotations

import re


_LABELS = (
    "result=",
    "owner=",
    "anchors=",
    "evidence chain=",
    "verified surface paths=",
    "concerns=",
    "search hops=",
    "nearest falsifying verification=",
)
_EMPTY_VALUES = {"", "none", "n/a", "not applicable", "unknown"}


def validate_work_surface_resolution(evidence: str) -> list[str]:
    """Accept only a bounded, repository-backed resolved owner claim."""

    values, missing = _labeled_values(evidence)
    if missing:
        return [
            "work surface resolution evidence must contain structured status for "
            + ", ".join(label.rstrip("=") for label in missing)
        ]

    failures: list[str] = []
    if values["result="].lower() != "resolved":
        failures.append(
            "work surface resolution result must be resolved; ambiguous and not_found are terminal failed results"
        )

    hops = values["search hops="]
    if not re.fullmatch(r"[1-4]", hops):
        failures.append("work surface resolution search hops must be one to four")

    for label, description in (
        ("owner=", "owner"),
        ("anchors=", "anchors"),
        ("verified surface paths=", "verified surface paths"),
    ):
        if _is_empty(values[label]):
            failures.append(f"work surface resolution requires a non-empty {description}")

    chain = values["evidence chain="]
    if _is_empty(chain) or "->" not in chain:
        failures.append(
            "work surface resolution evidence chain must trace an anchor to the verified owner"
        )

    verification = values["nearest falsifying verification="]
    if _is_empty(verification):
        failures.append(
            "work surface resolution requires the nearest falsifying verification"
        )
    return failures


def _labeled_values(evidence: str) -> tuple[dict[str, str], list[str]]:
    text = evidence.strip()
    normalized = text.lower()
    positions = {label: normalized.find(label) for label in _LABELS}
    missing = [label for label, position in positions.items() if position < 0]
    if missing:
        return {}, missing

    values: dict[str, str] = {}
    for index, label in enumerate(_LABELS):
        start = positions[label] + len(label)
        later = [
            positions[next_label]
            for next_label in _LABELS[index + 1 :]
            if positions[next_label] >= start
        ]
        finish = min(later) if later else len(text)
        values[label] = text[start:finish].strip(" ;")
    return values, []


def _is_empty(value: str) -> bool:
    return value.lower() in _EMPTY_VALUES
