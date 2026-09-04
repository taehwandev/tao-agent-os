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
from support.global_state import global_state_dir
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
_EDIT_TOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
_PRETOOL_GATE_MATCHER = f"{_EDIT_TOOL_MATCHER}|Bash"
_PRETOOL_GATE_ALIAS = "claude-pretool-gate"
_STOP_GATE_ALIAS = "claude-stop-gate"
_STATUSLINE_ALIAS = "claude-statusline"
# Identify the managed status line by a token nothing else would open with.
# The alias alone is not that token: the terminal integration that already held
# this slot chains a script named `claude-statusline.sh`, so searching for the
# alias matched a command Tao does not own and replaced it -- which is exactly
# the eviction the chain exists to prevent.
_STATUSLINE_MARKER = "TAO_STATUSLINE=1"


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
    # --hook-stdin lets that same listing be delivered once per session instead
    # of on every turn. The listing is identical for every prompt, so repeating
    # it spent thousands of tokens a turn restating what the session already
    # held; the label context this hook exists for is written either way.
    baseline_cmd = (
        f"TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL=claude {quote(str(launcher_path))}"
        " workflow"
        " route triage --advisory --hook-stdin"
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
            matcher=_EDIT_TOOL_MATCHER,
        )
    )

    stop_cmd = (
        f"TAO_HOOK_SOFT_FAIL=1 {quote(str(launcher_path))} {_STOP_GATE_ALIAS}"
    )
    status = _merge_claude_stop_gate(target, stop_cmd, dry_run)
    results.append({"tool": "claude", "hook": "Stop_finish_gate", "status": status, "path": str(target)})

    statusline_cmd = (
        f"{_STATUSLINE_MARKER} {quote(str(launcher_path))} {_STATUSLINE_ALIAS}"
    )
    status = _merge_claude_statusline(target, statusline_cmd, dry_run)
    results.append({"tool": "claude", "hook": "statusLine", "status": status, "path": str(target)})

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


def _merge_claude_statusline(target: Path, command: str, dry_run: bool) -> str:
    """Put Tao in the status line without evicting whoever already holds it.

    Claude Code has one status-line slot, and other tools install into it -- a
    token meter, a terminal integration. Taking it would silently switch those
    off, so Tao inserts itself in front of what is there and hands the same
    payload on through `--chain`, keeping that output beside its own.

    Reinstalling must not nest a second copy of the chain, so an existing
    managed entry is replaced whole and the chain it already carried is what
    gets preserved.
    """

    config = read_json(target)
    existing = config.get("statusLine")
    existing_command = ""
    if isinstance(existing, dict) and str(existing.get("type") or "") == "command":
        existing_command = str(existing.get("command") or "")

    if existing_command.startswith(f"{_STATUSLINE_MARKER} "):
        # Already managed: keep whatever it was chaining to rather than reading
        # the whole command back out, and rewrite it from the current launcher
        # path so a moved installation is repaired.
        chained = _chained_command(existing_command)
    else:
        chained = existing_command

    desired = command
    if chained.strip():
        desired = f"{command} --chain {quote(chained)}"

    # These three words are the installer's vocabulary, and the report reads
    # them literally: anything it does not recognise prints as MISSING. Saying
    # "unchanged" for an entry that is already correct therefore told the
    # operator to reinstall something that was in place, on every check.
    if existing_command == desired:
        return "ok"
    if dry_run:
        return "would_update"
    config["statusLine"] = {"type": "command", "command": desired}
    write_json(target, config)
    return "installed"


def _chained_command(command: str) -> str:
    """The command a managed status-line entry was already chaining to."""

    marker = " --chain "
    index = command.find(marker)
    if index < 0:
        return ""
    return _unquote(command[index + len(marker):].strip())


def _unquote(value: str) -> str:
    """Undo one layer of the shell quoting `quote` applies."""

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("'\\''", "'")
    return value


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


_RUNTIME_ENV_KEYS = ("SPILL_AI_TOOL", "SPILL_TOKEN_USAGE_AI_TOOL")


def _managed_env_record_path() -> Path:
    """Where this installer records the env keys it actually wrote.

    A hook command carries its own provenance -- the Tao alias is in the command
    string -- so ownership is readable from the config itself. An environment
    entry cannot: `SPILL_AI_TOOL=claude` looks identical whether this installer
    wrote it, another tool did, or the user did by hand. Value equality is a
    resemblance, and removing on resemblance is how one product deletes
    another's configuration. Keep the proof in Tao's own state directory
    instead, and remove only what it names.
    """
    return global_state_dir() / "managed-runtime-env.json"


def _managed_env_keys(target: Path) -> list[str]:
    record = read_json(_managed_env_record_path())
    entry = record.get(str(target))
    return [key for key in entry if isinstance(key, str)] if isinstance(entry, list) else []


def _record_managed_env_keys(target: Path, keys: list[str]) -> None:
    path = _managed_env_record_path()
    record = read_json(path)
    if keys:
        record[str(target)] = sorted(set(_managed_env_keys(target)) | set(keys))
    else:
        record.pop(str(target), None)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)


def _set_claude_env(target: Path, dry_run: bool) -> str:
    config = read_json(target)
    env = config.get("env", {})
    if env.get("SPILL_AI_TOOL") == "claude":
        return "ok"
    if dry_run:
        return "missing"
    written = [key for key in _RUNTIME_ENV_KEYS if key not in env]
    for key in _RUNTIME_ENV_KEYS:
        env[key] = "claude"
    config["env"] = env
    write_json(target, config)
    _record_managed_env_keys(target, written)
    return "installed"


def _remove_claude_env(target: Path, dry_run: bool) -> str:
    """Remove only the env keys this installer recorded writing.

    The trigger for this path is the Spill setup helper being absent, which is
    weaker than "Spill is gone": a moved, renamed, or restructured install looks
    the same. Without a record, leaving a stale key behind is the cheap failure
    and deleting a live one is not.
    """
    config = read_json(target)
    env = config.get("env", {})
    if not isinstance(env, dict):
        return "ok"

    owned = [key for key in _managed_env_keys(target) if key in env]
    if not owned:
        return "ok"
    if dry_run:
        return "would_remove"
    for key in owned:
        env.pop(key)
    if env:
        config["env"] = env
    else:
        config.pop("env", None)
    write_json(target, config)
    _record_managed_env_keys(target, [])
    return "removed"
