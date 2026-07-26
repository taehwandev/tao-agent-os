"""Task-local VibeGuard audit cache keyed by current git state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
VibeGuardCommand = Callable[[Path, Path], list[str]]
OverallParser = Callable[[str], Any]
CACHE_SCHEMA_VERSION = 1


def skipped_vibeguard(project: Path) -> dict[str, Any]:
    """Return explicit evidence when a declared read-only run skips VibeGuard."""

    return {
        "command": [],
        "cwd": str(project.resolve()),
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "skipped": True,
        "overall": {"status": "Skipped", "line": ""},
    }


def cached_vibeguard(
    *,
    project: Path,
    rules: Path,
    run_command: CommandRunner,
    vibeguard_command: VibeGuardCommand,
    parse_overall: OverallParser,
    git_status_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command = vibeguard_command(project, rules)
    signature = _signature(project, rules, command, run_command, git_status_result)
    if signature:
        cached = _read_cache(project)
        cached_result = cached.get("result")
        if (
            cached.get("signature") == signature
            and isinstance(cached_result, dict)
            and cached_result.get("returncode") == 0
        ):
            result = _result_with_overall(cached_result, parse_overall)
            result["cached"] = True
            result["cache"] = {"hit": True, "path": str(_cache_path(project))}
            return result

    result = run_command(command, project)
    result["overall"] = parse_overall(result["stdout"] + "\n" + result["stderr"])
    result["cached"] = False
    result["cache"] = {"hit": False, "path": str(_cache_path(project))}
    if signature and result.get("returncode") == 0:
        _write_cache(project, signature, _cacheable_result(result))
    return result


def _signature(
    project: Path,
    rules: Path,
    command: list[str],
    run_command: CommandRunner,
    git_status_result: dict[str, Any] | None,
) -> str | None:
    project_state = _git_state(project, run_command, git_status_result)
    if not project_state:
        return None
    if rules.resolve() == project.resolve():
        rules_state = project_state
    else:
        rules_state = _git_state(rules, run_command, None)
    if not rules_state:
        return None
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "project": str(project.resolve()),
        "rules": str(rules.resolve()),
        "command": command,
        "project_git": project_state,
        "rules_git": rules_state,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _git_state(
    path: Path,
    run_command: CommandRunner,
    git_status_result: dict[str, Any] | None,
) -> dict[str, str] | None:
    head = run_command(["git", "rev-parse", "--verify", "HEAD"], path)
    status = git_status_result or run_command(["git", "status", "--short", "--untracked-files=all"], path)
    if head.get("returncode") != 0 or status.get("returncode") != 0:
        return None
    return {
        "head": str(head.get("stdout", "")).strip(),
        "status": str(status.get("stdout", "")),
    }


def _cache_path(project: Path) -> Path:
    return project / ".tao" / "vibeguard-cache.json"


def _read_cache(project: Path) -> dict[str, Any]:
    path = _cache_path(project)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return {}
    return payload


def _write_cache(project: Path, signature: str, result: dict[str, Any]) -> None:
    path = _cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signature": signature,
        "result": result,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cacheable_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"overall", "cached", "cache"}
    }


def _result_with_overall(result: dict[str, Any], parse_overall: OverallParser) -> dict[str, Any]:
    copied = dict(result)
    copied["overall"] = parse_overall(copied.get("stdout", "") + "\n" + copied.get("stderr", ""))
    return copied
