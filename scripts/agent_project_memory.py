#!/usr/bin/env python3
"""Operator-reviewed, project-local guidance for later Tao tasks."""

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
from support.global_state import global_state_dir


SCHEMA_VERSION = 1
ID_RE = re.compile(r"[0-9a-f]{16}\Z")
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]{1,40}\Z")
STORE_NAME = "project-memory"
MAX_RECALL_ITEMS = 3
MAX_RECALL_CHARS = 1200


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(record: dict[str, Any]) -> str:
    reviewed = {key: record[key] for key in ("body", "source", "scope", "review_on")}
    return hashlib.sha256(
        json.dumps(reviewed, ensure_ascii=False, sort_keys=True).encode("utf-8")
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
            and record["status"] in {"pending", "approved", "retired"}
            and SCOPE_RE.fullmatch(record["scope"]) is not None
            and isinstance(record["body"], str)
            and 1 <= len(record["body"]) <= 500
            and record["body"].isprintable()
            and isinstance(record["source"], str)
            and 1 <= len(record["source"]) <= 200
            and record["source"].isprintable()
            and date.fromisoformat(record["review_on"]) >= date(2000, 1, 1)
            and record["digest"] == _digest(record)
            and (record["status"] != "approved" or bool(datetime.fromisoformat(record["approved_at"])))
        )
    except (KeyError, TypeError, ValueError):
        return None
    return record if valid else None


def _capture(project: Path, *, body: str, source: str, scope: str, review_on: str) -> dict[str, Any]:
    body, source = body.strip(), source.strip()
    if not (1 <= len(body) <= 500 and body.isprintable()):
        raise ValueError("memory body must be one line of 1–500 characters")
    if not (1 <= len(source) <= 200 and source.isprintable()):
        raise ValueError("source must be one line of 1–200 characters")
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("scope must be a reusable workflow slug")
    if date.fromisoformat(review_on) <= date.today():
        raise ValueError("review date must be in the future")
    _store(project).mkdir(parents=True, exist_ok=True, mode=0o700)
    record_id = secrets.token_hex(8)
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "status": "pending",
        "scope": scope,
        "body": body,
        "source": source,
        "review_on": review_on,
        "created_at": _timestamp(),
    }
    record["digest"] = _digest(record)
    atomic_write_json(_record_path(project, record_id), record)
    return record


def _decide(project: Path, record_id: str, *, decision: str, digest: str = "") -> dict[str, Any]:
    path = _record_path(project, record_id)
    record = _read(path)
    if record is None:
        raise ValueError("memory record is missing or invalid")
    if decision == "approve":
        if record["status"] != "pending" or digest != record["digest"]:
            raise ValueError("approval requires the current pending digest")
        if date.fromisoformat(record["review_on"]) <= date.today():
            raise ValueError("review date has passed")
        record["status"] = "approved"
        record["approved_at"] = _timestamp()
    elif decision == "retire":
        if record["status"] == "retired":
            return record
        record["status"] = "retired"
        record["retired_at"] = _timestamp()
    else:
        raise ValueError("unknown decision")
    atomic_write_json(path, record)
    return record


def _recall(project: Path, scope: str, *, today: date | None = None) -> list[dict[str, Any]]:
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("invalid recall scope")
    today = today or date.today()
    directory = _store(project)
    if not directory.is_dir() or directory.is_symlink():
        return []
    eligible = []
    for path in directory.glob("*.json"):
        record = _read(path)
        if (
            record is not None
            and record["status"] == "approved"
            and record["scope"] in {scope, "all"}
            and date.fromisoformat(record["review_on"]) > today
        ):
            eligible.append(record)
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
    return ["Project memory (reviewed reference only; current instructions and source evidence prevail):", *lines]


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--source", required=True)
    capture_parser.add_argument("--scope", default="all")
    capture_parser.add_argument("--review-on", required=True)
    approve_parser = commands.add_parser("approve")
    approve_parser.add_argument("id")
    approve_parser.add_argument("--digest", required=True)
    retire_parser = commands.add_parser("retire")
    retire_parser.add_argument("id")
    recall_parser = commands.add_parser("recall")
    recall_parser.add_argument("--scope", default="all")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    try:
        if args.command == "capture":
            result = _capture(project, body=sys.stdin.read(), source=args.source,
                             scope=args.scope, review_on=args.review_on)
        elif args.command in {"approve", "retire"}:
            result = _decide(project, args.id, decision=args.command,
                            digest=getattr(args, "digest", ""))
        else:
            result = _recall(project, args.scope)
    except (OSError, ValueError) as error:
        parser.exit(2, f"project memory: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
