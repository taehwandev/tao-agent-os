"""Install Claude continuation hooks without disturbing user-owned hooks."""

from __future__ import annotations

from pathlib import Path

from support.setup_config_files import quote, read_json, write_json


CONTINUATION_ALIAS = "claude-continuation-hook"
SESSION_START_MATCHER = "startup|resume|fork"


def configure_claude_continuation(
    target: Path,
    *,
    dry_run: bool,
    launcher_path: Path,
    matcher: str,
) -> list[dict]:
    command = (
        f"TAO_HOOK_SOFT_FAIL=1 {quote(str(launcher_path))} {CONTINUATION_ALIAS}"
    )
    events = (
        ("SessionStart", SESSION_START_MATCHER),
        ("PostToolUse", matcher),
        ("PostToolUseFailure", matcher),
    )
    results = []
    for event, event_matcher in events:
        status = _merge_event(target, event, event_matcher, command, dry_run)
        results.append(
            {
                "tool": "claude",
                "hook": f"{event}_continuation",
                "status": status,
                "path": str(target),
            }
        )
    return results


def _merge_event(
    target: Path,
    event: str,
    matcher: str,
    command: str,
    dry_run: bool,
) -> str:
    config = read_json(target)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    groups = hooks.get(event, [])
    if not isinstance(groups, list):
        groups = []
    current = False
    stale = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            hook_command = str(hook.get("command", ""))
            if hook_command == command and group.get("matcher") == matcher:
                current = True
            elif CONTINUATION_ALIAS in hook_command:
                stale = True
    if current and not stale:
        return "ok"
    if dry_run:
        return "would_update" if current or stale else "missing"
    cleaned = _remove_managed(groups)
    cleaned.append(
        {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command, "timeout": 10}],
        }
    )
    hooks[event] = cleaned
    config["hooks"] = hooks
    write_json(target, config)
    return "installed"


def _remove_managed(groups: list) -> list:
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
                and CONTINUATION_ALIAS in str(hook.get("command", ""))
            )
        ]
        if remaining:
            updated = dict(group)
            updated["hooks"] = remaining
            cleaned.append(updated)
    return cleaned
