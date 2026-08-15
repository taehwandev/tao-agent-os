"""Route docs from semantic intent and repository-verified owner paths."""

from __future__ import annotations

import json
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

    request_rules = list(enumerate(rule_list(rules, "request_intents")))
    request_rules.sort(key=lambda item: (-_required_priority(item[1]), item[0]))
    for _, rule in request_rules:
        if not rule_matches_command(rule, command):
            continue
        if not rule_matches_platform(rule, platform):
            continue
        if not rule_matches_request(rule, request_text):
            continue
        docs.extend(_append_request_match(rules, rule, command, matches))

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
        }
    )
    return docs


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
        }
    )
    return docs
