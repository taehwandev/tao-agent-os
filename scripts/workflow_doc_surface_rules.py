"""Helpers for workflow document surface rule matching."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Iterable

from workflow_common import ROOT, unique

# A Latin keyword glued to a Korean particle leaves `\b` nothing to find:
# in "jank\uB97C" Python sees `k` and `\uB97C` as two word characters, so a
# request pattern like `\b(jank|stutter)\b` silently misses the request.
# Splitting that one junction before matching repairs every such pattern at
# once; `workflow_request` normalizes concern hints with the same regex.
from workflow_request import _LATIN_HANGUL_JUNCTION


REQUEST_PATH_PATTERNS = (
    r"`([^`]+)`",
    r"(?:^|\s)((?:~/|\.{1,2}/|/)[^\s`'\",)]+)",
    r"\b([A-Za-z0-9_./-]+\.(?:py|md|json|ya?ml|toml|js|jsx|ts|tsx|go|rs|java|kt|swift|sh))(?::\d+)?\b",
)


def extract_request_surface_paths(text: str) -> list[str]:
    """Extract path-like references from a user request."""
    if not text:
        return []
    paths: list[str] = []
    for pattern in REQUEST_PATH_PATTERNS:
        for match in re.finditer(pattern, text):
            path = normalize_path(match.group(1))
            if path:
                paths.append(path)
    return unique(paths)


def git_status_surface_paths(output: str) -> list[str]:
    """Parse path names from `git status --short --untracked-files=all`."""
    paths: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip("\n")
        if not line or len(line) < 4:
            continue
        payload = line[3:].strip()
        candidates = payload.split(" -> ") if " -> " in payload else [payload]
        for candidate in candidates:
            path = normalize_path(candidate.strip('"'))
            if path:
                paths.append(path)
    return unique(paths)


def rule_list(rules: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = rules.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def surface_rule_doc_refs(rules: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return all document references and invalid doc-set references."""
    docs: list[str] = []
    invalid_refs: list[str] = []
    doc_sets = _doc_sets(rules)
    for items in doc_sets.values():
        docs.extend(items)
    for key in ("request_intents", "path_surfaces"):
        for rule in rule_list(rules, key):
            docs.extend(string_list(rule.get("docs")))
            for name in string_list(rule.get("doc_sets")):
                if name in doc_sets:
                    docs.extend(doc_sets[name])
                else:
                    invalid_refs.append(f"{str(rule.get('name') or key)} references unknown doc_set `{name}`")
    return unique(docs), invalid_refs


def rule_docs(rules: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    docs: list[str] = []
    doc_sets = _doc_sets(rules)
    for name in string_list(rule.get("doc_sets")):
        docs.extend(doc_sets.get(name, []))
    docs.extend(string_list(rule.get("docs")))
    return unique(docs)


def rule_matches_command(rule: dict[str, Any], command: str) -> bool:
    commands = string_list(rule.get("commands"))
    return not commands or command in set(commands)


def rule_matches_platform(rule: dict[str, Any], platform: str | None) -> bool:
    platforms = string_list(rule.get("platforms"))
    return not platforms or bool(platform and platform in set(platforms))


def rule_matches_request(rule: dict[str, Any], request_text: str) -> bool:
    any_patterns = string_list(rule.get("request_any"))
    all_groups = _pattern_groups(rule.get("request_all"))
    if not any_patterns and not all_groups:
        return True
    if not request_text:
        return False
    if any_patterns and not any(_request_pattern_matches(pattern, request_text) for pattern in any_patterns):
        return False
    return all(any(_request_pattern_matches(pattern, request_text) for pattern in group) for group in all_groups)


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern) or Path(normalized).match(pattern):
            return True
    return False


def normalize_path(path: str) -> str:
    normalized = path.strip().strip("'\"`.,;:!?)]}")
    normalized = re.sub(r":\d+(?:-\d+)?$", "", normalized)
    if not normalized or "://" in normalized:
        return ""
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith(ROOT.as_posix() + "/"):
        normalized = normalized[len(ROOT.as_posix()) + 1 :]
    return normalized


def _doc_sets(rules: dict[str, Any]) -> dict[str, list[str]]:
    raw_sets = rules.get("doc_sets")
    if not isinstance(raw_sets, dict):
        return {}
    return {
        str(name): string_list(value)
        for name, value in raw_sets.items()
        if isinstance(name, str)
    }


def _pattern_groups(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    groups: list[list[str]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            groups.append([item])
        elif isinstance(item, list):
            group = [str(pattern) for pattern in item if isinstance(pattern, str) and pattern.strip()]
            if group:
                groups.append(group)
    return groups


def _request_pattern_matches(pattern: str, text: str) -> bool:
    normalized = _LATIN_HANGUL_JUNCTION.sub(" ", text)
    return re.search(pattern, normalized, re.IGNORECASE) is not None
