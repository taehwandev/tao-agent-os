"""Antigravity/AGY runtime bridge and permission setup."""

from __future__ import annotations

from pathlib import Path

from support.permission_entries import agy_legacy_permission_entries, agy_permission_entries
from support.runtime_bridge import (
    merge_runtime_bridge,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.setup_config_files import merge_permissions_allow, quote, read_json, write_json
from support.stable_launcher import stable_launcher_path

AGY_RUNTIME_BRIDGE_PATH = Path.home() / ".antigravity" / "AGENTS.md"
AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES = runtime_bridge_required_phrases("Antigravity", "AGENTS.md")
_STATUSLINE_ALIAS = "agy-statusline"
_STATUSLINE_MARKER = "TAO_STATUSLINE=1"


def configure_agy(
    dry_run: bool,
    *,
    root: Path,
    scripts_dir: Path,
    launcher_path: Path | None = None,
    spill_available: bool = True,
) -> list[dict]:
    results = []
    status = _merge_agy_runtime_bridge(AGY_RUNTIME_BRIDGE_PATH, dry_run, root=root)
    results.append({
        "tool": "agy",
        "hook": "runtime_bridge.AGENTS",
        "status": status,
        "path": str(AGY_RUNTIME_BRIDGE_PATH),
    })

    if launcher_path is None:
        launcher_path = stable_launcher_path()

    cli_settings = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    statusline_cmd = (
        f"{_STATUSLINE_MARKER} {quote(str(launcher_path))} {_STATUSLINE_ALIAS}"
    )
    status = _merge_agy_statusline(cli_settings, statusline_cmd, dry_run)
    results.append({
        "tool": "agy",
        "hook": "statusLine",
        "status": status,
        "path": str(cli_settings),
    })

    entries = agy_permission_entries(scripts_dir, spill_available=spill_available)
    # Antigravity uses literal prefix matching inside command(prefix)
    entries.extend([
        "command(git)",
        "command(git remote)",
        "command(git fetch)",
        "command(git pull)",
        "command(git push)",
        "command(git merge)",
        "command(git rebase)",
        "command(git tag)",
        "command(git reset)",
        "command(git switch)",
        "command(git rev-parse)",
        "command(python3)",
        "command(python)",
        "command(swift)",
        "command(node)",
        "command(npm)",
        "command(npx)",
        "command(pytest)",
    ])
    cleanup_entries = agy_legacy_permission_entries(scripts_dir)
    if not spill_available:
        cleanup_entries += agy_permission_entries(scripts_dir, spill_available=True)
    targets = [
        cli_settings,
        Path.home() / ".gemini" / "config" / "config.json",
    ]

    for target in targets:
        status = merge_permissions_allow(
            target,
            entries,
            dry_run,
            cleanup_entries=cleanup_entries,
        )
        results.append({
            "tool": "agy",
            "hook": "permissions.TaoAgentOSPython",
            "status": status,
            "path": str(target),
        })

    hooks_path = Path.home() / ".gemini" / "config" / "hooks.json"
    status = "ok" if hooks_path.exists() else "ok (no hooks file; permissions use config.json/settings.json)"
    results.append({
        "tool": "agy",
        "hook": "config.hooks",
        "status": status,
        "path": str(hooks_path),
    })
    return results


def _merge_agy_statusline(target: Path, command: str, dry_run: bool) -> str:
    """Put Tao in the status line without evicting whoever already holds it.

    Antigravity CLI settings have one statusLine slot. Taking it would silently
    switch other tools off, so Tao inserts itself in front of what is there and
    hands the same payload on through `--chain`, keeping that output beside its own.

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
        chained = _chained_command(existing_command)
    else:
        chained = existing_command

    desired = command
    if chained.strip():
        desired = f"{command} --chain {quote(chained)}"

    # The installer's report reads these words literally and prints anything it
    # does not recognise as MISSING, so an entry that is already correct has to
    # say "ok". This copy inherited "unchanged" from the Claude installer along
    # with the rest of the shape.
    if existing_command == desired:
        return "ok"
    if dry_run:
        return "would_update"
    config["statusLine"] = {"type": "command", "command": desired, "enabled": True}
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


def _merge_agy_runtime_bridge(target: Path, dry_run: bool, *, root: Path) -> str:
    return merge_runtime_bridge(
        target,
        dry_run,
        block=_agy_runtime_bridge_block(root),
        required_phrases=AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES,
    )


def _agy_runtime_bridge_block(root: Path) -> str:
    return runtime_bridge_block(root, "Antigravity", "AGENTS.md")
