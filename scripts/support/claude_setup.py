"""Claude Code hook and permission setup."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from support.permission_entries import (
    claude_legacy_permission_entries,
    claude_permission_entries,
)
from support.claude_continuation_setup import configure_claude_continuation
from support.runtime_bridge import (
    merge_runtime_bridge,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.setup_config_files import merge_permissions_allow, quote, read_json, write_json

# Identify the managed hook by the command it runs, not by the launcher's
# filename. Keying on the launcher name means a renamed launcher stops matching
# the entry installed under the old name, so the stale hook survives and the
# runtime ends up invoking both.
# Matches both the current advisory command and the retired --request-classified
# spelling, so an install that predates the advisory route is replaced instead of
# left running beside it.
_BASELINE_COMMAND_RE = re.compile(
    r"(?:workflow\.py.*route|workflow\s+route).*triage.*(?:--advisory|--request-classified)"
)
_PRETOOL_GATE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
_PRETOOL_GATE_ALIAS = "claude-pretool-gate"
_STOP_GATE_ALIAS = "claude-stop-gate"


def configure_claude(
    dry_run: bool,
    *,
    root: Path,
    scripts_dir: Path,
    launcher_path: Path,
    spill_available: bool = True,
) -> list[dict]:
    target = Path.home() / ".claude" / "settings.json"
    # This hook fires on every prompt and never sees the prompt text, so it has
    # no request to classify and nothing to assert about intake. It used to say
    # --request-classified, which claimed the request was already resolved and
    # was exactly the self-asserting bypass that flag no longer allows. The
    # advisory route emits the same listing and label context while satisfying
    # no downstream gate.
    baseline_cmd = (
        f"TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL=claude {quote(str(launcher_path))}"
        " workflow"
        " route triage --advisory"
    )
    results = []

    bridge_target = Path.home() / ".claude" / "CLAUDE.md"
    status = merge_runtime_bridge(
        bridge_target,
        dry_run,
        block=runtime_bridge_block(root, "Claude", "CLAUDE.md"),
        required_phrases=runtime_bridge_required_phrases("Claude", "CLAUDE.md"),
    )
    results.append({
        "tool": "claude",
        "hook": "runtime_bridge.CLAUDE",
        "status": status,
        "path": str(bridge_target),
    })

    if spill_available:
        status = _merge_claude_user_prompt_submit(target, baseline_cmd, dry_run)
    else:
        status = _remove_claude_user_prompt_submit(target, dry_run)
    results.append({"tool": "claude", "hook": "UserPromptSubmit_spill_bridge", "status": status, "path": str(target)})

    gate_cmd = (
        f"TAO_HOOK_SOFT_FAIL=1 {quote(str(launcher_path))} {_PRETOOL_GATE_ALIAS}"
    )
    status = _merge_claude_pre_tool_gate(target, gate_cmd, dry_run)
    results.append({"tool": "claude", "hook": "PreToolUse_workflow_gate", "status": status, "path": str(target)})

    results.extend(
        configure_claude_continuation(
            target,
            dry_run=dry_run,
            launcher_path=launcher_path,
            matcher=_PRETOOL_GATE_MATCHER,
        )
    )

    stop_cmd = (
        f"TAO_HOOK_SOFT_FAIL=1 {quote(str(launcher_path))} {_STOP_GATE_ALIAS}"
    )
    status = _merge_claude_stop_gate(target, stop_cmd, dry_run)
    results.append({"tool": "claude", "hook": "Stop_finish_gate", "status": status, "path": str(target)})

    cleanup_entries = claude_legacy_permission_entries(scripts_dir)
    if not spill_available:
        cleanup_entries += claude_permission_entries(scripts_dir, spill_available=True)
    status = merge_permissions_allow(
        target,
        claude_permission_entries(scripts_dir, spill_available=spill_available),
        dry_run,
        cleanup_entries=cleanup_entries,
    )
    results.append({"tool": "claude", "hook": "permissions.TaoAgentOSPython", "status": status, "path": str(target)})

    status = _set_claude_env(target, dry_run) if spill_available else _remove_claude_env(target, dry_run)
    results.append({"tool": "claude", "hook": "env.SPILL_AI_TOOL", "status": status, "path": str(target)})
    return results


def _merge_claude_user_prompt_submit(target: Path, command: str, dry_run: bool) -> str:
    config = read_json(target)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get("UserPromptSubmit", [])
    if not isinstance(groups, list):
        groups = []

    # Scan every entry before deciding. Returning as soon as the current command
    # turns up would leave a managed entry installed under an earlier launcher
    # name in place beside it, and the runtime would run both.
    has_current_command = False
    has_stale_managed_command = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            hook_command = hook.get("command", "")
            if hook_command == command and group.get("matcher") == ".*":
                has_current_command = True
                continue
            if _is_managed_claude_spill_bridge_command(hook_command):
                has_stale_managed_command = True

    if has_current_command and not has_stale_managed_command:
        return "ok"
    if dry_run:
        return "would_update" if has_current_command or has_stale_managed_command else "missing"

    cleaned = _remove_managed_hook_objects(
        groups,
        _is_managed_claude_spill_bridge_command,
    )
    cleaned.append({
        "matcher": ".*",
        "hooks": [{"type": "command", "command": command, "timeout": 5}],
    })
    hooks["UserPromptSubmit"] = cleaned
    config["hooks"] = hooks
    write_json(target, config)
    return "installed"


def _is_managed_claude_pre_tool_gate_command(command: str) -> bool:
    return _PRETOOL_GATE_ALIAS in command


def _is_managed_claude_stop_gate_command(command: str) -> bool:
    return _STOP_GATE_ALIAS in command


def _merge_claude_stop_gate(target: Path, command: str, dry_run: bool) -> str:
    """Install the Stop gate without disturbing unrelated user Stop hooks."""
    config = read_json(target)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get("Stop", [])
    if not isinstance(groups, list):
        groups = []

    has_current_command = False
    has_stale_managed_command = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            hook_command = hook.get("command", "")
            if hook_command == command:
                has_current_command = True
                continue
            if _is_managed_claude_stop_gate_command(hook_command):
                has_stale_managed_command = True

    if has_current_command and not has_stale_managed_command:
        return "ok"
    if dry_run:
        return "would_update" if has_current_command or has_stale_managed_command else "missing"

    cleaned = _remove_managed_hook_objects(groups, _is_managed_claude_stop_gate_command)
    cleaned.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command, "timeout": 10}],
    })
    hooks["Stop"] = cleaned
    config["hooks"] = hooks
    write_json(target, config)
    return "installed"


def _merge_claude_pre_tool_gate(target: Path, command: str, dry_run: bool) -> str:
    config = read_json(target)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get("PreToolUse", [])
    if not isinstance(groups, list):
        groups = []

    has_current_command = False
    has_stale_managed_command = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            hook_command = hook.get("command", "")
            if hook_command == command and group.get("matcher") == _PRETOOL_GATE_MATCHER:
                has_current_command = True
                continue
            if _is_managed_claude_pre_tool_gate_command(hook_command):
                has_stale_managed_command = True

    if has_current_command and not has_stale_managed_command:
        return "ok"
    if dry_run:
        return "would_update" if has_current_command or has_stale_managed_command else "missing"

    cleaned = _remove_managed_hook_objects(
        groups,
        _is_managed_claude_pre_tool_gate_command,
    )
    cleaned.append({
        "matcher": _PRETOOL_GATE_MATCHER,
        "hooks": [{"type": "command", "command": command, "timeout": 10}],
    })
    hooks["PreToolUse"] = cleaned
    config["hooks"] = hooks
    write_json(target, config)
    return "installed"


def _remove_managed_hook_objects(
    groups: list,
    predicate: Callable[[str], bool],
) -> list:
    """Remove managed command objects without deleting neighboring user hooks."""
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
                and predicate(str(hook.get("command", "")))
            )
        ]
        if remaining:
            updated = dict(group)
            updated["hooks"] = remaining
            cleaned.append(updated)
    return cleaned


def _remove_claude_user_prompt_submit(target: Path, dry_run: bool) -> str:
    config = read_json(target)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get("UserPromptSubmit", [])
    if not isinstance(groups, list):
        groups = []
    changed = False
    cleaned_groups = []

    for group in groups:
        group_hooks = group.get("hooks", [])
        if not isinstance(group_hooks, list):
            cleaned_groups.append(group)
            continue
        filtered_hooks = [
            hook for hook in group_hooks
            if not _is_managed_claude_spill_bridge_command(hook.get("command", ""))
        ]
        if len(filtered_hooks) != len(group_hooks):
            changed = True
        if filtered_hooks:
            updated_group = dict(group)
            updated_group["hooks"] = filtered_hooks
            cleaned_groups.append(updated_group)

    if not changed:
        return "ok"
    if dry_run:
        return "would_remove"

    hooks["UserPromptSubmit"] = cleaned_groups
    config["hooks"] = hooks
    write_json(target, config)
    return "removed"


def _is_managed_claude_spill_bridge_command(command: str) -> bool:
    return bool(
        _BASELINE_COMMAND_RE.search(command)
        and "SPILL_AI_TOOL=claude" in command
    )


def _set_claude_env(target: Path, dry_run: bool) -> str:
    config = read_json(target)
    env = config.get("env", {})
    if env.get("SPILL_AI_TOOL") == "claude":
        return "ok"
    if dry_run:
        return "missing"
    env["SPILL_AI_TOOL"] = "claude"
    env["SPILL_TOKEN_USAGE_AI_TOOL"] = "claude"
    config["env"] = env
    write_json(target, config)
    return "installed"


def _remove_claude_env(target: Path, dry_run: bool) -> str:
    config = read_json(target)
    env = config.get("env", {})
    if not isinstance(env, dict):
        return "ok"

    changed = False
    for key, expected in (
        ("SPILL_AI_TOOL", "claude"),
        ("SPILL_TOKEN_USAGE_AI_TOOL", "claude"),
    ):
        if env.get(key) == expected:
            env.pop(key)
            changed = True
    if not changed:
        return "ok"
    if dry_run:
        return "would_remove"
    if env:
        config["env"] = env
    else:
        config.pop("env", None)
    write_json(target, config)
    return "removed"
