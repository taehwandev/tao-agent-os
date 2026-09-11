"""Read, merge, and report runtime setup configuration files."""

from __future__ import annotations

import json
import re
from pathlib import Path


def merge_codex_prefix_rules(
    target: Path,
    entries: list[str],
    dry_run: bool,
    *,
    cleanup_entries: list[str] | None = None,
) -> str:
    original = target.read_text() if target.exists() else ""
    block = "\n".join([
        "# tao-hooks:begin",
        "# Managed by Tao Agent OS setup. Keep narrow; do not replace with broad python3 rules.",
        *entries,
        "# tao-hooks:end",
        "",
    ])
    pattern = re.compile(
        r"# tao-hooks:begin[\s\S]*?# tao-hooks:end\n?",
        re.MULTILINE,
    )
    unmanaged = pattern.sub("", original)
    generated_entries = set(entries) | set(cleanup_entries or [])
    unmanaged = "".join(
        line
        for line in unmanaged.splitlines(keepends=True)
        if line.strip() not in generated_entries
    )
    if unmanaged and not unmanaged.endswith("\n"):
        unmanaged += "\n"
    updated = unmanaged + block
    if updated == original:
        return "ok"
    if dry_run:
        return "missing"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated)
    return "installed"


def merge_permissions_allow(
    target: Path,
    entries: list[str],
    dry_run: bool,
    *,
    cleanup_entries: list[str] | None = None,
) -> str:
    config = read_json(target)
    permissions = config.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        allow = []

    entry_set = set(entries)
    cleanup_set = set(cleanup_entries or [])
    stale = [
        entry for entry in allow
        if isinstance(entry, str)
        if entry not in entry_set
        and entry in cleanup_set
    ]
    missing = [entry for entry in entries if entry not in allow]
    # Matching is set-like, so a repeated entry grants nothing. Appending only
    # what was absent left any copy another tool added in place for good, which
    # is how an entry setup already owns came to sit in the list twice.
    duplicated = len(allow) != len({entry for entry in allow})
    if not missing and not stale and not duplicated:
        return "ok"
    if dry_run:
        if stale and not missing:
            return "would_remove"
        if stale or duplicated:
            return "would_update"
        return "missing"

    cleaned = _first_of_each(entry for entry in allow if entry not in stale)
    permissions["allow"] = cleaned + missing
    config["permissions"] = permissions
    write_json(target, config)
    return "installed"


def _first_of_each(entries) -> list:
    """Drop later copies, because position is how a reader finds an entry."""
    seen = set()
    kept = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        kept.append(entry)
    return kept


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def print_results(results: list[dict], dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    for result in results:
        print(f"{prefix}{_status_marker(result['status'])} {result['tool']} / {result['hook']}: {result['status']} ({result['path']})")


def _status_marker(status: str) -> str:
    if status.startswith("ok"):
        return "OK"
    if status == "installed":
        return "INSTALLED"
    if status == "removed":
        return "REMOVED"
    if status == "would_remove":
        return "WOULD REMOVE"
    if status == "would_update":
        return "WOULD UPDATE"
    return "MISSING"
