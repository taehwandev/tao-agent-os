"""Read, merge, and report runtime setup configuration files."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
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
    generated_entries = set(entries) | set(cleanup_entries or [])
    # Codex appends approvals after this block. Keep the first block in place
    # so a valid file stays ready without moving unrelated user rules.
    unmanaged_parts = [
        "".join(
            line for line in part.splitlines(keepends=True)
            if line.strip() not in generated_entries
        )
        for part in pattern.split(original)
    ]
    before = unmanaged_parts[0]
    if before and not before.endswith("\n"):
        before += "\n"
    updated = before + block + "".join(unmanaged_parts[1:])
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


class SetupConfigError(RuntimeError):
    """A runtime config file exists but cannot be merged without losing its content."""


BACKUP_SUFFIX = ".tao-backup"
_backed_up: set[Path] = set()


def read_json(path: Path) -> dict:
    """Return a config object; only a missing file means an empty config.

    A malformed or unreadable file is the user's data, not an empty config:
    merging into {} and writing back would wipe it, so setup stops instead.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as error:
        raise SetupConfigError(f"cannot read {path}: {error}; setup left it unchanged") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SetupConfigError(
            f"{path} is not valid JSON ({error}); fix or move it, then rerun setup. "
            "Setup left it unchanged."
        ) from error
    if not isinstance(data, dict):
        raise SetupConfigError(
            f"{path} does not contain a JSON object; fix or move it, then rerun setup. "
            "Setup left it unchanged."
        )
    return data


def write_json(path: Path, data: dict) -> None:
    """Replace a config atomically, keeping the pre-run content as one backup."""
    # A dotfile manager may link the config; replace the file it points at,
    # never the link itself.
    path = path.resolve() if path.is_symlink() else path
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    key = path.absolute()
    if key not in _backed_up and path.is_file():
        _atomic_write_bytes(path.with_name(path.name + BACKUP_SUFFIX), path.read_bytes(), path)
    _backed_up.add(key)
    _atomic_write_bytes(path, encoded, path)


def _atomic_write_bytes(path: Path, payload: bytes, mode_source: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        try:
            os.chmod(temporary, stat.S_IMODE(mode_source.stat().st_mode))
        except OSError:
            pass
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


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
