"""Read-only review of a project-memory store: records that need an agent decision.

Every rule here is a deterministic function of validated records and a date.
Nothing is merged, retired or renewed automatically: deciding which record is
right needs the agent to check its `source` against live evidence, and the
existing `capture --replaces` and `retire` mutations apply that decision.
"""

from __future__ import annotations

import re
import shlex
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agent_project_memory import RECALLABLE_STATUSES, scan_records


DEFAULT_WITHIN_DAYS = 14
DUPLICATE_JACCARD = 0.8
_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_DECISION_FIELDS = ("id", "scope", "body", "source", "review_on")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and fold whitespace runs."""
    return " ".join(_PUNCTUATION_RE.sub("", text.lower()).split())


def _tokens(text: str) -> frozenset[str]:
    return frozenset(normalize(text).split())


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _scopes_overlap(left: str, right: str) -> bool:
    return left == right or "all" in {left, right}


def _entry(record: dict[str, Any], reason: str = "") -> dict[str, Any]:
    entry = {key: record[key] for key in _DECISION_FIELDS}
    if reason:
        entry["reason"] = reason
    return entry


def _group(records: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: item["id"])
    return {
        "ids": [record["id"] for record in ordered],
        "reason": reason,
        "records": [_entry(record) for record in ordered],
    }


def _duplicate_groups(live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Connected components over near-identical pairs, so a chain of close
    # copies is reported once. `live` is id-sorted, which keeps it stable.
    tokens = [_tokens(record["body"]) for record in live]
    parent = list(range(len(live)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(live)):
        for right in range(left + 1, len(live)):
            if (_scopes_overlap(live[left]["scope"], live[right]["scope"])
                    and _jaccard(tokens[left], tokens[right]) >= DUPLICATE_JACCARD):
                parent[root(right)] = root(left)
    components: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(live):
        components.setdefault(root(index), []).append(record)
    groups = [members for members in components.values() if len(members) > 1]
    reason = (f"bodies share at least {DUPLICATE_JACCARD:.0%} of their words in overlapping "
              "scopes; merge with `capture --replaces <one>`, then retire the others")
    return sorted((_group(members, reason) for members in groups), key=lambda item: item["ids"])


def _shared_source_groups(live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in live:
        by_source.setdefault(normalize(record["source"]), []).append(record)
    reason = "records cite the same source; open it and keep, merge or retire the ones that disagree"
    groups = [_group(members, reason) for members in by_source.values() if len(members) > 1]
    return sorted(groups, key=lambda item: item["ids"])


def _unfinished_replacements(live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replaced_by: dict[str, list[str]] = {}
    for record in live:
        if record.get("replaces"):
            replaced_by.setdefault(record["replaces"], []).append(record["id"])
    findings = []
    for record in live:
        if record["id"] in replaced_by:
            entry = _entry(record, "a live record replaces this one; `retire` it to finish "
                                   "the interrupted replacement")
            entry["replaced_by"] = sorted(replaced_by[record["id"]])
            findings.append(entry)
    return findings


def findings(records: list[dict[str, Any]], unreadable: int, *, today: date,
             within_days: int = DEFAULT_WITHIN_DAYS) -> dict[str, Any]:
    """Classify validated records; the result carries bodies for the agent only."""
    if within_days < 0:
        raise ValueError("--within-days must not be negative")
    live = sorted((record for record in records if record["status"] in RECALLABLE_STATUSES),
                  key=lambda item: item["id"])
    horizon = today + timedelta(days=within_days)
    review_on = {record["id"]: date.fromisoformat(record["review_on"]) for record in live}
    return {
        "today": today.isoformat(),
        "within_days": within_days,
        "expired": [
            _entry(record, "review date reached; recheck the source, then renew with "
                           "`capture --replaces` and a new date, or `retire`")
            for record in live if review_on[record["id"]] <= today
        ],
        "expiring": [
            _entry(record, f"review date within {within_days} days; renew or retire ahead of time")
            for record in live if today < review_on[record["id"]] <= horizon
        ],
        "duplicate_groups": _duplicate_groups(live),
        "shared_source_groups": _shared_source_groups(live),
        "unfinished_replacements": _unfinished_replacements(live),
        "unreadable": unreadable,
    }


def consolidate(project: Path, *, today: date | None = None,
                within_days: int = DEFAULT_WITHIN_DAYS) -> dict[str, Any]:
    """Scan one repository's store and report what needs a decision."""
    records, unreadable = scan_records(project)
    return findings(records, unreadable, today=today or date.today(), within_days=within_days)


def summary_line(report: dict[str, Any], project: Path, launcher: str) -> str:
    """One content-free start notice, or "" when nothing needs a decision."""
    counts = {
        "expired": len(report["expired"]),
        "expiring": len(report["expiring"]),
        "duplicates": len(report["duplicate_groups"]),
        "shared_source": len(report["shared_source_groups"]),
        "unfinished": len(report["unfinished_replacements"]),
    }
    if not any(counts.values()):
        return ""
    command = shlex.join([launcher, "project-memory", "--project", str(project), "consolidate"])
    rendered = " ".join(f"{name}={count}" for name, count in counts.items())
    return f"Project memory upkeep: {rendered} -> {command}"
