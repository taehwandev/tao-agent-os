"""Task-local VibeGuard audit cache keyed by current git state."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
VibeGuardCommand = Callable[[Path, Path], list[str]]
OverallParser = Callable[[str], Any]
# Bumped when the key gains an input: a cache written by the previous scheme
# was keyed on git status alone and cannot be trusted to describe the bytes it
# audited, so every entry from it is discarded rather than read.
CACHE_SCHEMA_VERSION = 2


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
    result = _retry_with_changed_only_when_blocked_paths_are_ignored(
        project=project,
        command=command,
        result=result,
        run_command=run_command,
        parse_overall=parse_overall,
    )
    result["cached"] = False
    result["cache"] = {"hit": False, "path": str(_cache_path(project))}
    if signature and result.get("returncode") == 0:
        try:
            _write_cache(project, signature, _cacheable_result(result))
        except OSError as error:
            result["cache"]["write_error"] = type(error).__name__
    return result


def _retry_with_changed_only_when_blocked_paths_are_ignored(
    *,
    project: Path,
    command: list[str],
    result: dict[str, Any],
    run_command: CommandRunner,
    parse_overall: OverallParser,
) -> dict[str, Any]:
    if result.get("returncode") == 0 or "--changed-only" in command:
        return result

    blocking_paths = _blocking_finding_paths(result)
    if not blocking_paths:
        return result
    if any(
        run_command(["git", "check-ignore", "--quiet", "--", relative], project).get("returncode") != 0
        for relative in blocking_paths
    ):
        return result

    fallback = run_command([*command, "--changed-only"], project)
    fallback["overall"] = parse_overall(fallback["stdout"] + "\n" + fallback["stderr"])
    if fallback.get("returncode") != 0:
        return result
    fallback["fallback"] = {
        "reason": "full audit blocked only on Git-ignored paths",
        "ignored_path_count": len(blocking_paths),
        "full_audit_returncode": result.get("returncode"),
        "full_audit_overall": result.get("overall"),
    }
    return fallback


def _blocking_finding_paths(result: dict[str, Any]) -> list[str]:
    output = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
    blocking_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("- 🛑 ")
    ]
    if not blocking_lines:
        return []

    paths: list[str] = []
    for line in blocking_lines:
        match = re.match(r"^- 🛑 (?P<path>.+?):\d+\s", line)
        if match is None:
            return []
        paths.append(match.group("path"))
    return paths


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
    status_text = str(status.get("stdout", ""))
    return {
        "head": str(head.get("stdout", "")).strip(),
        "status": status_text,
        "dirty_content": _dirty_content_digest(path, status_text),
    }


def _dirty_content_digest(path: Path, status_text: str) -> str:
    """Digest the bytes of every path git reports as changed.

    HEAD covers what is committed and the status text covers *which* paths
    differ from it, but not what they now contain: `git status --short` prints
    ` M app.py` for every edit of that file, so a second edit produced the same
    key as the first and reused its verdict. An audit that never saw the current
    bytes must not be able to speak for them.

    Only the changed paths are read, so the cost is the size of the edit rather
    than the size of the project -- which is what makes the cache still worth
    having. A path that cannot be read is recorded as unreadable rather than
    skipped, because a file the digest cannot account for must still change the
    key when it appears or disappears.
    """

    digest = hashlib.sha256()
    for line in status_text.splitlines():
        # Porcelain v1: two status columns, a space, then the path. A rename
        # prints `old -> new`; the destination is what now holds the bytes.
        entry = line[3:] if len(line) > 3 else ""
        if not entry:
            continue
        target = entry.split(" -> ")[-1].strip().strip('"')
        digest.update(target.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        candidate = path / target
        try:
            if candidate.is_dir():
                # An untracked directory is reported as one entry. Its contents
                # are what the audit reads, so they are what the key measures.
                for child in sorted(candidate.rglob("*")):
                    if child.is_file():
                        digest.update(str(child.relative_to(path)).encode("utf-8", "surrogateescape"))
                        digest.update(hashlib.sha256(child.read_bytes()).digest())
            else:
                digest.update(hashlib.sha256(candidate.read_bytes()).digest())
        except OSError:
            digest.update(b"\0unreadable\0")
    return digest.hexdigest()


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
