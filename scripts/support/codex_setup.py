"""Codex lifecycle-hook setup owned by Tao Agent OS."""

from __future__ import annotations

from pathlib import Path

from support.setup_config_files import read_json, write_json


MANAGED_STOP_ALIAS = "codex-stop-gate"


def merge_codex_stop_gate(target: Path, command: str, dry_run: bool) -> str:
    """Install one managed Stop hook while preserving every unrelated hook."""

    config = read_json(target)
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get("Stop")
    if not isinstance(groups, list):
        groups = []

    current = False
    stale = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_hooks = group.get("hooks")
        if not isinstance(group_hooks, list):
            continue
        for hook in group_hooks:
            if not isinstance(hook, dict):
                continue
            hook_command = str(hook.get("command") or "")
            if hook_command == command:
                current = True
            elif MANAGED_STOP_ALIAS in hook_command:
                stale = True

    if current and not stale:
        return "ok"
    if dry_run:
        return "would_update" if current or stale else "missing"

    cleaned = _without_managed_stop_hooks(groups)
    cleaned.append(
        {
            "hooks": [
                {"type": "command", "command": command, "timeout": 10}
            ]
        }
    )
    hooks["Stop"] = cleaned
    config["hooks"] = hooks
    write_json(target, config)
    return "installed"


def _without_managed_stop_hooks(groups: list) -> list:
    cleaned: list = []
    for group in groups:
        if not isinstance(group, dict):
            cleaned.append(group)
            continue
        group_hooks = group.get("hooks")
        if not isinstance(group_hooks, list):
            cleaned.append(group)
            continue
        remaining = [
            hook
            for hook in group_hooks
            if not (
                isinstance(hook, dict)
                and MANAGED_STOP_ALIAS in str(hook.get("command") or "")
            )
        ]
        if remaining:
            updated = dict(group)
            updated["hooks"] = remaining
            cleaned.append(updated)
    return cleaned
