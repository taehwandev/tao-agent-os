"""Route docs from semantic intent and repository-verified owner paths."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from workflow_common import ROOT, unique
from workflow_doc_surface_rules import (
    # Re-export candidate extractors for launchers and compatibility callers.
    extract_request_surface_paths,
    git_status_surface_paths,
    normalize_path,
    path_matches,
    rule_docs,
    rule_list,
    rule_matches_command,
    rule_matches_platform,
    rule_matches_request,
    string_list,
    surface_rule_doc_refs,
)


RULES_FILE = "workflow-doc-surfaces.json"


def load_doc_surface_rules(root: Path = ROOT) -> dict[str, Any]:
    """Load the root document surface routing map."""
    path = root / RULES_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "request_intents": [], "path_surfaces": []}
    if not isinstance(payload, dict):
        raise ValueError(f"{RULES_FILE} must contain a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError(f"{RULES_FILE} has an unsupported schema_version")
    return payload


def infer_surface_docs(
    *,
    command: str,
    platform: str | None = None,
    request_text: str = "",
    surface_paths: Iterable[str] | None = None,
    root: Path = ROOT,
) -> tuple[list[str], list[dict[str, object]]]:
    """Return docs from semantic intent and explicitly verified owner paths."""
    rules = load_doc_surface_rules(root)
    docs: list[str] = []
    matches: list[dict[str, object]] = []
    # Keep independent requests separate: a narrow data edit must not erase a
    # UI edit in another clause. Retain clause indexes, not another prompt copy.
    clauses = re.split(r"[;\n.!?]|\b(?:and|but|then)\b|(?<=하고)|(?<=말고)",
                       request_text, flags=re.IGNORECASE)

    request_rules = list(enumerate(rule_list(rules, "request_intents")))
    request_rules.sort(key=lambda item: (-_required_priority(item[1]), item[0]))
    for _, rule in request_rules:
        if not rule_matches_command(rule, command):
            continue
        if not rule_matches_platform(rule, platform):
            continue
        if not rule_matches_request(rule, request_text):
            continue
        clause_ids = [i for i, clause in enumerate(clauses)
                      if rule_matches_request(rule, clause)]
        if str(rule.get("name", "")).endswith("_change"):
            clause_ids = [i for i in clause_ids if not _negated_change(clauses[i])]
            if not clause_ids:
                continue
        docs.extend(_append_request_match(rules, rule, command, matches))
        matches[-1]["request_clauses"] = clause_ids

    paths = unique(
        normalize_path(path)
        for path in (surface_paths or [])
        if normalize_path(path)
    )
    for rule in rule_list(rules, "path_surfaces"):
        patterns = string_list(rule.get("patterns"))
        excluded_patterns = string_list(rule.get("exclude_patterns"))
        matched_paths = [
            path
            for path in paths
            if path_matches(path, patterns)
            and not path_matches(path, excluded_patterns)
        ]
        if not matched_paths:
            continue
        docs.extend(_append_path_match(rules, rule, matched_paths, matches))

    return unique(docs), matches


def _negated_change(clause: str) -> bool:
    """Recognize explicit change exclusions, not arbitrary uses of 'not'.

    This filters change-specific discovery only; required safety concerns and
    owner-path rules are not removed by a request's negative wording.
    """
    return bool(re.search(
        r"\b(?:do\s+not|don't|must\s+not|never)\s+(?:change|modify|edit|fix|touch)\b"
        r"|\bwithout\s+(?:changing|modifying|editing|fixing|touching)\b"
        r"|(?:수정|변경|편집|건드리)(?:하)?지\s*(?:말|마|않)",
        clause, re.IGNORECASE,
    ))


def _append_request_match(
    rules: dict[str, Any],
    rule: dict[str, Any],
    command: str,
    matches: list[dict[str, object]],
) -> list[str]:
    docs = rule_docs(rules, rule)
    matches.append(
        {
            "type": "request_intent",
            "name": str(rule.get("name") or command),
            "docs": docs,
            "platforms": string_list(rule.get("platforms")),
            "reason": str(rule.get("reason") or ""),
            "required_priority": _required_priority(rule),
            "narrows": string_list(rule.get("narrows")),
            # Carried for the same reason a path rule carries it. Reading the
            # flag only there made it a silent no-op on a request rule: the
            # documents were routed as candidates *and* required, which is
            # exactly what the flag exists to prevent.
            "reference_only": bool(rule.get("reference_only")),
        }
    )
    return docs


def required_surface_docs(matches: list[dict[str, object]]) -> list[str]:
    """Separate retrieval matches from evidence that permits required reading.

    A rule may name broader rules it `narrows`. Moving one button matches both
    "this is Compose UI work" and "this is a layout change"; the second is the
    truer description, and without this the wider rule still required the state,
    module and lifecycle cards that placing a control does not decide. Narrowing
    only removes documents from the required set -- they stay reachable as
    reference docs, so nothing becomes unreadable.
    """
    selected: list[str] = []
    narrowed: set[str] = set()
    for match in matches:
        for name in match.get("narrows") or ():
            # A separately matched request for the broad domain is independent
            # work, even if its owner path also matches a narrowed path rule.
            sibling_names = set(match.get("narrows") or ())
            independent = []
            for other in matches:
                if (other.get("type") == "request_intent"
                        and other.get("name") in sibling_names
                        and set(other.get("request_clauses") or ())
                            - set(match.get("request_clauses") or ())):
                    independent.append(other)
                    other["independent_change"] = True
            if not independent:
                narrowed.add(str(name))
    has_owner = any(
        m.get("type") == "path_surface" and m.get("paths") and not m.get("reference_only")
        for m in matches
    )
    for match in matches:
        if match.get("reference_only"):
            # Routed as a candidate, never required: the touched file says this
            # ecosystem is nearby, not that this change reads it.
            match["required_eligible"] = False
            match["selection_reason"] = "reference_only_surface"
            continue
        if str(match.get("name")) in narrowed:
            match["required_eligible"] = False
            match["selection_reason"] = "narrowed_by_a_more_specific_rule"
            continue
        owner = match.get("type") == "path_surface" and bool(match.get("paths"))
        priority = match.get("required_priority", 0)
        explicit = isinstance(priority, int) and not isinstance(priority, bool) and priority > 0
        intent_fallback = not has_owner and match.get("type") == "request_intent"
        independent = bool(match.get("independent_change"))
        eligible = owner or explicit or independent or intent_fallback
        match["required_eligible"] = eligible
        match["selection_reason"] = (
            "verified_owner_path" if owner else
            "explicit_required_priority" if explicit else
            "independent_change" if independent else
            "request_intent_without_resolved_owner" if intent_fallback else
            "keyword_candidate_without_owner_evidence"
        )
        if eligible:
            selected.extend(str(doc) for doc in match.get("docs", []))
    return unique(selected)


def _required_priority(rule: dict[str, Any]) -> int:
    value = rule.get("required_priority", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _append_path_match(
    rules: dict[str, Any],
    rule: dict[str, Any],
    matched_paths: list[str],
    matches: list[dict[str, object]],
) -> list[str]:
    docs = rule_docs(rules, rule)
    matches.append(
        {
            "type": "path_surface",
            "name": str(rule.get("name") or ""),
            "paths": matched_paths,
            "docs": docs,
            "reason": str(rule.get("reason") or ""),
            "narrows": string_list(rule.get("narrows")),
            "reference_only": bool(rule.get("reference_only")),
        }
    )
    return docs
