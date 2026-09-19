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
    project_root: Path | None = None,
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
        name = str(rule.get("name", ""))
        # One reading for both kinds. A change rule used to ask only whether the
        # clause contained an exclusion, which cannot tell whose: "fix only the
        # DTO parser without touching WorkManager" silenced the data-contract
        # rule that describes the work being asked for.
        if rule.get("subject_exclusion") or name.endswith("_change"):
            clause_ids = [i for i in clause_ids
                          if not _excluded_subject(clauses[i], rule)]
            if not clause_ids:
                continue
        docs.extend(_append_request_match(rules, rule, command, matches))
        matches[-1]["request_clauses"] = clause_ids

    paths = unique(
        normalize_path(path)
        for path in (surface_paths or [])
        if normalize_path(path)
    )
    swift_evidence: dict[str, tuple[set[str], bool, bool] | None] = {}
    for rule in rule_list(rules, "path_surfaces"):
        patterns = string_list(rule.get("patterns"))
        excluded_patterns = string_list(rule.get("exclude_patterns"))
        matched_paths = [
            path
            for path in paths
            if path_matches(path, patterns)
            and not path_matches(path, excluded_patterns)
        ]
        framework = rule.get("swift_framework")
        if framework:
            for path in matched_paths:
                if path not in swift_evidence:
                    swift_evidence[path] = _swift_owner_evidence(project_root, path)
            matched_paths = [path for path in matched_paths
                             if _matches_swift_framework(framework, swift_evidence[path], platform)]
        if not matched_paths:
            continue
        docs.extend(_append_path_match(rules, rule, matched_paths, matches))

    return unique(docs), matches


def _swift_owner_evidence(project_root: Path | None, path: str) -> tuple[set[str], bool, bool] | None:
    """Inspect only an existing verified Swift owner, bounded to the target repo."""
    if project_root is None or not path.endswith(".swift"):
        return None
    try:
        root = project_root.resolve()
        owner = (root / path).resolve()
        if not owner.is_relative_to(root) or not owner.is_file():
            return None
        with owner.open("rb") as stream:
            raw = stream.read(131073)
        if len(raw) > 131072:
            return None
        source = raw.decode("utf-8")
    except (OSError, UnicodeError, RuntimeError):
        return None
    # Imports in examples or comments are not framework evidence. Unhandled
    # nested block comments conservatively leave the owner unclassified.
    source = re.sub(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*', "", source)
    if "/*" in source or "*/" in source:
        return None
    imports = set(re.findall(r"(?m)^\s*(?:@\w+\s+)*(?:public\s+|internal\s+)?import\s+(\w+)\b", source))
    macos = "AppKit" in imports or bool(re.search(r"\bos\s*\(\s*macOS\s*\)", source))
    ios = "UIKit" in imports or bool(re.search(r"\bos\s*\(\s*iOS\s*\)", source))
    return imports, macos, ios


def _matches_swift_framework(framework: object, evidence: tuple[set[str], bool, bool] | None,
                             platform: str | None) -> bool:
    if evidence is None:
        return False
    imports, macos, ios = evidence
    if framework == "native":
        return True
    if framework == "UIKit":
        return "UIKit" in imports and (not macos or platform == "ios")
    if framework == "iOSSwiftUI":
        return ("SwiftUI" in imports and (not macos or (platform == "ios" and ios))
                and (platform == "ios" or "UIKit" in imports))
    return False


# Where one part of a sentence ends and the next begins. Listing joints is not
# the same as listing subjects: a joint is a closed class, while the things a
# request can forbid are not, which is why the subject itself is never
# enumerated here -- it is whatever the rule's own patterns match.
_CLAUSE_JOINT = (
    r"(?=\s*(?:[,.;!?]|$)|\s+(?:while|whilst|and|but|then|so|before|after|"
    r"when|unless|though|although|instead|yet)\b)"
)

_KOREAN_ACTION_JOINT = r"(?:하되|되|면서|하고|고)"
_KOREAN_NEGATED_CHANGE = (
    r"\s*(?:은|는|을|를)?\s*"
    r"(?:수정|변경|편집|건드리|손대)(?:하)?지\s*"
    r"(?:말고|말아줘|마세요|마|않고|않은\s*채|않으면서|않인\s*채)"
)

# A prohibition and the subject it governs. Read as spans inside the clause
# rather than as the whole clause: "fix only the DTO parser without touching
# WorkManager" is a prohibition too, and requiring the clause to *be* one meant
# every exclusion written as a modifier was invisible.
_PROHIBITION_SPANS = (
    r"\bwithout\s+(?:touching|changing|modifying|editing|altering|"
    r"breaking|affecting)\s+(?P<subject>[^,.;]+?)" + _CLAUSE_JOINT,
    r"\b(?:do\s+not|don't|must\s+not|never)\s+"
    r"(?:change|modify|edit|fix|touch|alter)\s+(?P<subject>[^,.;]+?)"
    + _CLAUSE_JOINT,
    # An affirmative action before a Korean prohibition is not part of the
    # prohibited subject.  Start after a connective when one exists.  The
    # start-of-clause fallback refuses to cross such a connective, so it cannot
    # swallow the requested action while searching for a later negation.
    r"(?:(?<=하되)|(?<=되)|(?<=면서)|(?<=하고)|(?<=고))\s*"
    r"(?P<subject>[^,.;]+?)" + _KOREAN_NEGATED_CHANGE,
    r"^(?P<subject>(?:(?!" + _KOREAN_ACTION_JOINT + r"\s).)+?)"
    + _KOREAN_NEGATED_CHANGE,
)


def _excluded_subject(clause: str, rule: dict[str, Any]) -> bool:
    """True when this clause forbids this rule's subject and asks nothing of it.

    The prohibition is found wherever it sits, and what it governs is compared
    against the rule. Excluding on that alone would be wrong: "API는 보존하면서
    WorkManager 수정" forbids one thing and asks for another, and the rule's
    subject is in the part being asked for. So the clause with its prohibitions
    removed has to *stop* matching before the guidance is dropped.

    Phrasing this does not recognise keeps the guidance, which is the safe
    direction: an unread exclusion costs a document, an unread request costs the
    rules for the change being made.
    """

    removals: list[tuple[int, int]] = []
    forbidden = False
    for pattern in _PROHIBITION_SPANS:
        for match in re.finditer(pattern, clause, re.IGNORECASE):
            if rule_matches_request(rule, match.group("subject")):
                forbidden = True
            removals.append((match.start(), match.end()))
    if not forbidden:
        return False
    remainder = clause
    # Patterns are grouped by language, not by source position.  Apply spans
    # from right to left so removing one prohibition never invalidates the
    # offsets of another prohibition in the same clause.
    for start, end in sorted(removals, reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]
    return not rule_matches_request(rule, remainder)


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
            # A command-only rule keeps its documents discoverable but does
            # not prove that every invocation needs the full bundle up front.
            # Request patterns are direct evidence for this specific intake.
            "request_specific": bool(
                string_list(rule.get("request_any"))
                or rule.get("request_all")
            ),
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
    removes documents from the current manifest when a more specific rule owns
    the decision. The broader card remains discoverable through its own rule or
    an unresolved lookup; it is not listed beside a request that excluded it.
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
