"""Runtime hook checks for Tao Agent OS preflight."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from workflow_spill import has_spill_setup_helper
from support.permission_entries import (
    agy_permission_entries,
    claude_permission_entries,
    codex_prefix_rule_entries,
)
from support.runtime_bridge import runtime_bridge_required_phrases
from support.stable_launcher import stable_launcher_issue


MANAGED_HOOK_RE = re.compile(
    r"(?:workflow\.py.*route|tao-hook.*workflow.*route).*triage.*(?:--advisory|--request-classified)"
)
ADVISORY_HOOK_RE = re.compile(
    r"(?:workflow\.py.*route|tao-hook.*workflow.*route).*triage.*--advisory"
)
AGY_RUNTIME_BRIDGE_PATH = Path.home() / ".antigravity" / "AGENTS.md"
AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES = runtime_bridge_required_phrases("Antigravity", "AGENTS.md")


def check_agent_hooks(tao_root: Path) -> tuple[list[str], list[str]]:
    """Return warning and failure strings for missing runtime registrations."""
    warnings: list[str] = []
    failures: list[str] = []
    spill_available = has_spill_setup_helper()

    warnings.extend(_codex_warnings(tao_root))
    warnings.extend(_claude_warnings(tao_root, spill_available=spill_available))
    agy_warnings = _agy_warnings(tao_root, spill_available=spill_available)
    warnings.extend(agy_warnings)

    agy_bridge_issue = agy_runtime_bridge_issue(tao_root)
    if agy_bridge_issue and active_runtime_label() == "antigravity":
        failures.append(agy_bridge_issue)
    elif agy_bridge_issue and agy_warnings:
        warnings.append(agy_bridge_issue)

    return warnings, failures


def active_runtime_label() -> str:
    for key in ("TAO_AI_TOOL", "SPILL_AI_TOOL", "SPILL_TOKEN_USAGE_AI_TOOL"):
        value = os.environ.get(key, "").strip().lower()
        if value in {"agy", "antigravity"}:
            return "antigravity"
        if value in {"codex", "claude", "openai"}:
            return value
    return ""


def agy_runtime_bridge_issue(tao_root: Path) -> str:
    try:
        text = AGY_RUNTIME_BRIDGE_PATH.read_text()
    except OSError:
        return (
            "AGY runtime bridge is missing required fail-closed instructions at "
            f"{AGY_RUNTIME_BRIDGE_PATH}. Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    missing = [phrase for phrase in AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES if phrase not in text]
    if not missing:
        return ""
    return (
        "AGY runtime bridge is missing required fail-closed instructions at "
        f"{AGY_RUNTIME_BRIDGE_PATH}. Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
    )


def _codex_warnings(tao_root: Path) -> list[str]:
    target = Path.home() / ".codex" / "rules" / "default.rules"
    if not target.exists():
        return []
    try:
        missing_permissions = _missing_text_entries(
            target.read_text(),
            codex_prefix_rule_entries(tao_root / "scripts"),
        )
    except OSError:
        return []
    if not missing_permissions:
        return []
    return [
        "Codex Tao Agent OS Python prefix rules are missing. "
        f"Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
    ]


def _claude_warnings(tao_root: Path, *, spill_available: bool) -> list[str]:
    target = Path.home() / ".claude" / "settings.json"
    if not target.exists():
        return []
    try:
        config = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    warnings: list[str] = []
    launcher_issue = stable_launcher_issue(tao_root)
    if launcher_issue:
        warnings.append(launcher_issue)
    if spill_available:
        warnings.extend(_claude_spill_warnings(config, tao_root))
    missing_permissions = _missing_allow_entries(
        config,
        claude_permission_entries(tao_root / "scripts", spill_available=spill_available),
    )
    if missing_permissions:
        warnings.append(
            "Claude Code Tao Agent OS Python permissions are missing. "
            f"Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    return warnings


def _claude_spill_warnings(config: dict[str, Any], tao_root: Path) -> list[str]:
    warnings: list[str] = []
    groups = config.get("hooks", {}).get("UserPromptSubmit", [])
    managed_commands = [
        h.get("command", "")
        for g in groups
        for h in g.get("hooks", [])
        if MANAGED_HOOK_RE.search(h.get("command", ""))
        and "SPILL_AI_TOOL=claude" in h.get("command", "")
    ]
    has_advisory_route = any(
        ADVISORY_HOOK_RE.search(command)
        for command in managed_commands
    )
    if not managed_commands:
        warnings.append(
            "Claude Code UserPromptSubmit Spill workflow label hook is missing. "
            f"Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    elif not has_advisory_route:
        warnings.append(
            "Claude Code UserPromptSubmit Spill workflow label hook is missing "
            "--advisory. Run: "
            f"python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    spill_tool = config.get("env", {}).get("SPILL_AI_TOOL", "")
    if spill_tool != "claude":
        warnings.append(
            "env.SPILL_AI_TOOL is not set to 'claude' in ~/.claude/settings.json. "
            f"Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    return warnings


def _agy_warnings(tao_root: Path, *, spill_available: bool) -> list[str]:
    targets = [
        Path.home() / ".gemini" / "config" / "config.json",
        Path.home() / ".gemini" / "antigravity-cli" / "settings.json",
    ]
    entries = agy_permission_entries(tao_root / "scripts", spill_available=spill_available)
    configs: list[dict[str, Any]] = []
    for target in targets:
        config = _read_json_object(target)
        if config is not None:
            configs.append(config)
    if configs and not any(not _missing_allow_entries(config, entries) for config in configs):
        return [
            "AGY Tao Agent OS Python permissions are missing from AGY config. "
            f"Run: python3 {tao_root / 'scripts' / 'setup-agent-hooks.py'}"
        ]
    return []


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _missing_allow_entries(config: dict[str, Any], entries: list[str]) -> list[str]:
    permissions = config.get("permissions")
    if not isinstance(permissions, dict):
        return entries
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        return entries
    # Some runtime config files (e.g. an AGY config with tens of thousands of
    # accumulated allow entries) make a per-entry `in` scan over the raw list
    # O(len(entries) * len(allow)); a real one measured ~0.16s per call from
    # this alone. Hashing once first drops it to a negligible O(len(allow) +
    # len(entries)).
    # Runtime configuration is an external JSON boundary.  Ignore malformed
    # elements instead of letting one object/list make every preflight crash;
    # only string entries can satisfy a string permission requirement.
    allow_set = {item for item in allow if isinstance(item, str)}
    return [entry for entry in entries if entry not in allow_set]


def _missing_text_entries(text: str, entries: list[str]) -> list[str]:
    return [entry for entry in entries if entry not in text]
