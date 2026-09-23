#!/usr/bin/env python3
"""Agent-written, source-attributed project memory recalled by later Tao tasks.

A capture is active at once and later starts recall it without an approval
step. Memory is reference, never authority: the current request, repository
rules and source evidence prevail. Wrong records are corrected by replacing
(`capture --replaces`) or retiring them, and every record expires on its
`--review-on` date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from support.global_state import global_state_dir, user_store_write_error


SCHEMA_VERSION = 1
ID_RE = re.compile(r"[0-9a-f]{16}\Z")
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]{1,40}\Z")
STORE_NAME = "project-memory"
MAX_RECALL_ITEMS = 3
MAX_RECALL_CHARS = 1200
# `pending` and `approved` are the former review states; both are recallable.
RECALLABLE_STATUSES = frozenset({"active", "pending", "approved"})
STATUSES = RECALLABLE_STATUSES | {"retired"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(record: dict[str, Any]) -> str:
    content = {key: record[key] for key in ("body", "source", "scope", "review_on")}
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def repository_key(project: Path) -> str:
    """Name one repository the same way from every one of its worktrees."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        identity = result.stdout.strip() if result.returncode == 0 else str(project.resolve())
    except (OSError, subprocess.TimeoutExpired):
        identity = str(project.resolve())
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _store(project: Path) -> Path:
    """Use one local store across every worktree of the same Git repository."""
    root = global_state_dir() / STORE_NAME
    directory = root / repository_key(project)
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("memory directory must not be a symlink")
    return directory


def _writable_store(project: Path) -> Path:
    refusal = user_store_write_error()
    if refusal:
        raise ValueError(refusal)
    return _store(project)


def _record_path(project: Path, record_id: str) -> Path:
    if not ID_RE.fullmatch(record_id):
        raise ValueError("invalid memory id")
    return _store(project) / f"{record_id}.json"


def _read(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        valid = (
            ID_RE.fullmatch(record["id"]) is not None
            and path.name == f'{record["id"]}.json'
            and record["status"] in STATUSES
            and SCOPE_RE.fullmatch(record["scope"]) is not None
            and isinstance(record["body"], str)
            and 1 <= len(record["body"]) <= 500
            and record["body"].isprintable()
            and isinstance(record["source"], str)
            and 1 <= len(record["source"]) <= 200
            and record["source"].isprintable()
            and date.fromisoformat(record["review_on"]) >= date(2000, 1, 1)
            and record["digest"] == _digest(record)
            and ID_RE.fullmatch(record.get("replaces") or "0" * 16) is not None
        )
    except (KeyError, TypeError, ValueError):
        return None
    return record if valid else None


def _existing(project: Path, record_id: str) -> tuple[Path, dict[str, Any]]:
    path = _record_path(project, record_id)
    record = _read(path)
    if record is None:
        raise ValueError("memory record is missing or invalid")
    return path, record


def _retire(project: Path, record_id: str, *, replaced_by: str = "") -> dict[str, Any]:
    path, record = _existing(project, record_id)
    if record["status"] == "retired":
        return record
    record["status"] = "retired"
    record["retired_at"] = _timestamp()
    if replaced_by:
        record["replaced_by"] = replaced_by
    _writable_store(project)
    atomic_write_json(path, record)
    return record


def _capture(project: Path, *, body: str, source: str, scope: str, review_on: str,
             replaces: str = "") -> dict[str, Any]:
    body, source = body.strip(), source.strip()
    if not (1 <= len(body) <= 500 and body.isprintable()):
        raise ValueError("memory body must be one line of 1–500 characters")
    if not (1 <= len(source) <= 200 and source.isprintable()):
        raise ValueError("source must be one line of 1–200 characters")
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("scope must be a reusable workflow slug")
    if date.fromisoformat(review_on) <= date.today():
        raise ValueError("review date must be in the future")
    if replaces:
        _existing(project, replaces)
    _writable_store(project).mkdir(parents=True, exist_ok=True, mode=0o700)
    record_id = secrets.token_hex(8)
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "status": "active",
        "scope": scope,
        "body": body,
        "source": source,
        "review_on": review_on,
        "created_at": _timestamp(),
    }
    if replaces:
        record["replaces"] = replaces
    record["digest"] = _digest(record)
    # The new record is the commit point: recall already hides the record it
    # replaces, so an interrupted retire below never shows both.
    atomic_write_json(_record_path(project, record_id), record)
    if replaces:
        _retire(project, replaces, replaced_by=record_id)
    return record


def _recall(project: Path, scope: str, *, today: date | None = None) -> list[dict[str, Any]]:
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("invalid recall scope")
    today = today or date.today()
    directory = _store(project)
    if not directory.is_dir() or directory.is_symlink():
        return []
    live = [
        record for record in (_read(path) for path in directory.glob("*.json"))
        if record is not None and record["status"] in RECALLABLE_STATUSES
    ]
    replaced = {record.get("replaces") for record in live}
    eligible = [
        record for record in live
        if record["id"] not in replaced
        and record["scope"] in {scope, "all"}
        and date.fromisoformat(record["review_on"]) > today
    ]
    eligible.sort(key=lambda item: (item["review_on"], item["id"]))
    return eligible


def recall_lines(project: Path, scope: str) -> list[str]:
    """Render bounded, explicitly non-authoritative context for a start result."""
    lines = []
    size = 0
    for record in _recall(project, scope):
        payload = json.dumps(
            {key: record[key] for key in ("id", "body", "source", "review_on")},
            ensure_ascii=False,
        )
        if len(lines) >= MAX_RECALL_ITEMS or size + len(payload) > MAX_RECALL_CHARS:
            break
        lines.append(f"- {payload}")
        size += len(payload)
    if not lines:
        return []
    return ["Project memory (agent-written reference; the current request, repo rules "
            "and source evidence prevail):", *lines]


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--source", required=True)
    capture_parser.add_argument("--scope", default="all")
    capture_parser.add_argument("--review-on", required=True)
    capture_parser.add_argument("--replaces", default="")
    # Former review step, kept so older instructions still run; it changes nothing.
    approve_parser = commands.add_parser("approve")
    approve_parser.add_argument("id")
    approve_parser.add_argument("--digest", default="")
    retire_parser = commands.add_parser("retire")
    retire_parser.add_argument("id")
    recall_parser = commands.add_parser("recall")
    recall_parser.add_argument("--scope", default="all")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    try:
        if args.command == "capture":
            result = _capture(project, body=sys.stdin.read(), source=args.source,
                              scope=args.scope, review_on=args.review_on,
                              replaces=args.replaces)
        elif args.command == "approve":
            result = _existing(project, args.id)[1]
        elif args.command == "retire":
            result = _retire(project, args.id)
        else:
            result = _recall(project, args.scope)
    except (OSError, ValueError) as error:
        parser.exit(2, f"project memory: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
