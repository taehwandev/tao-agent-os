"""Find Claude ask rules that override the Tao gate's Git approvals.

The Claude PreToolUse gate approves ordinary Git inside an isolated linked
worktree, but Claude still evaluates settings `ask` rules after a hook returns
`allow`. A rule such as `Bash(git -C * rebase *)` therefore re-prompts every
rebase the gate already judged, and installing an allow rule does not help.

Setup only reports these rules. They belong to the user, so it never edits
them and never fails because of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _rule_git_subcommand(rule: str) -> str | None:
    """The Git subcommand a `Bash(git ...)` rule names, `*` for any, else None."""

    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return None
    pattern = rule[len("Bash(") : -1].strip()
    if pattern.endswith(":*"):
        pattern = pattern[: -len(":*")]
    tokens = pattern.split()
    if not tokens or tokens[0] != "git":
        return None
    index = 1
    while index < len(tokens) and tokens[index] == "-C":
        index += 2
    if index >= len(tokens):
        return None
    return tokens[index]


def gate_overriding_ask_rules(settings: dict) -> list[str]:
    """Ask rules that match a Git subcommand the gate approves as ordinary."""

    from claude_pretool_gate import ORDINARY_GIT_SUBCOMMANDS

    permissions = settings.get("permissions")
    rules = permissions.get("ask") if isinstance(permissions, dict) else None
    if not isinstance(rules, list):
        return []
    found = []
    for rule in rules:
        if not isinstance(rule, str):
            continue
        subcommand = _rule_git_subcommand(rule)
        if subcommand == "*" or subcommand in ORDINARY_GIT_SUBCOMMANDS:
            found.append(rule)
    return found


def notice_claude_ask_overrides(settings_path: Path) -> list[str]:
    """Print a stderr notice for overriding ask rules; return the rules found."""

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(settings, dict):
        return []
    rules = gate_overriding_ask_rules(settings)
    if rules:
        print(
            f"Claude notice: {settings_path} permissions.ask has "
            f"{len(rules)} Git rule(s) that override Tao's approval of ordinary Git "
            "inside a linked task worktree, so each matching command prompts again: "
            + ", ".join(rules)
            + ". Claude evaluates ask rules even after a hook allows a call; an allow "
            "rule cannot cancel them. Tao already asks for the hazardous forms "
            "(hard reset, stash drop/clear, forced worktree removal), so remove these "
            "rules if the prompts are unwanted. Setup leaves them unchanged.",
            file=sys.stderr,
        )
    return rules
