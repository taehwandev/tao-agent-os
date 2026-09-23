#!/usr/bin/env python3
"""User-local work cards that carry one line of unfinished work across sessions.

Owner: work-card storage. Allowed: one SQLite file under the global Tao state
directory. Forbidden: prompts, transcripts, logs, sync, or any authority.
Callers: agent-hook start/finish/cancel; tests: test_agent_work_cards.

A card is keyed by repository and work id, so every continued run of the same
work updates one card and every worktree of a repository shares one board. The
content-free delegation queue in agent_scheduler is a separate concern.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_project_memory import repository_key
from support.global_state import global_state_dir


SCHEMA_VERSION = 1
STORE_NAME = "work-cards"
DATABASE_NAME = "cards.sqlite3"
WORK_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
STATES = ("active", "done", "cancelled")
MAX_SUMMARY_CHARS = 200
MAX_RECALL_ITEMS = 3
# Any card idle this long is dropped, active ones included: an abandoned
# session's card, or one left by a test run in a throwaway repository, would
# otherwise stay forever.
IDLE_RETENTION = timedelta(days=90)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS cards (
    repo TEXT NOT NULL,
    work_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    command TEXT NOT NULL,
    project TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN {STATES}),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (repo, work_id)
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    directory = global_state_dir() / STORE_NAME
    if directory.is_symlink():
        raise ValueError("work-card directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(directory / DATABASE_NAME, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, SCHEMA_VERSION):
        connection.close()
        raise ValueError(f"unsupported work-card schema version {version}")
    connection.execute(_SCHEMA)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return connection


def _summary(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text or not text.isprintable():
        raise ValueError("card summary must be one printable line")
    return text[:MAX_SUMMARY_CHARS]


def _work_id(work_id: str) -> str:
    if not WORK_ID_RE.fullmatch(str(work_id or "")):
        raise ValueError("invalid work id")
    return work_id


def open_card(project: Path, work_id: str, *, summary: str, command: str) -> None:
    """Create the work's card, or reactivate it when a continued run starts."""
    now = _now()
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO cards VALUES (?, ?, ?, ?, ?, 'active', ?, ?) "
            "ON CONFLICT (repo, work_id) DO UPDATE SET summary = excluded.summary, "
            "command = excluded.command, project = excluded.project, "
            "state = 'active', updated_at = excluded.updated_at",
            (repository_key(project), _work_id(work_id), _summary(summary), command,
             str(project.resolve()), now.isoformat(), now.isoformat()),
        )
        connection.execute(
            "DELETE FROM cards WHERE updated_at < ?", ((now - IDLE_RETENTION).isoformat(),)
        )


def settle_card(project: Path, work_id: str, state: str) -> bool:
    """Move an active card to a settled state; True when a card changed."""
    if state not in STATES[1:]:
        raise ValueError(f"cards settle only to {STATES[1:]}")
    with closing(_connect()) as connection, connection:
        changed = connection.execute(
            "UPDATE cards SET state = ?, updated_at = ? "
            "WHERE repo = ? AND work_id = ? AND state = 'active'",
            (state, _now().isoformat(), repository_key(project), _work_id(work_id)),
        ).rowcount
    return bool(changed)


def list_cards(project: Path, *, include_settled: bool = False) -> list[dict[str, Any]]:
    states = STATES if include_settled else ("active",)
    with closing(_connect()) as connection:
        rows = connection.execute(
            f"SELECT work_id, summary, command, project, state, created_at, updated_at "
            f"FROM cards WHERE repo = ? AND state IN ({','.join('?' * len(states))}) "
            "ORDER BY updated_at DESC",
            (repository_key(project), *states),
        ).fetchall()
    return [dict(row) for row in rows]


def open_card_lines(project: Path, current_work_id: str) -> list[str]:
    """Name other unfinished work in this repository as reference context."""
    others = [card for card in list_cards(project) if card["work_id"] != current_work_id]
    if not others:
        return []
    lines = [
        f"- {card['work_id']} [{card['command']}, {card['updated_at'][:10]}] {card['summary']}"
        for card in others[:MAX_RECALL_ITEMS]
    ]
    hidden = len(others) - len(lines)
    if hidden:
        lines.append(f"- {hidden} more: `work-cards list`")
    return [
        "Open work cards in this repository (reference only; close finished ones with "
        "`work-cards close <work id>`):",
        *lines,
    ]


def _evidence_work_id(evidence: Path) -> str:
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    return _work_id(str((payload.get("work") or {}).get("id") or ""))


def start_lines(project: Path, evidence: Path, *, summary: str, command: str) -> list[str]:
    """Open this run's card and name the repository's other open cards.

    Cards are optional reference state, so a missing summary or an unusable
    store leaves the admitted run untouched instead of failing start.
    """
    try:
        work_id = _evidence_work_id(evidence)
        if summary.strip():
            open_card(project, work_id, summary=summary, command=command)
        return open_card_lines(project, work_id)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return []


def settle_from_evidence(project: Path, evidence: Path, state: str) -> None:
    """Settle the card of the run this evidence records; never fails its hook."""
    try:
        settle_card(project, _evidence_work_id(evidence), state)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("list")
    list_parser.add_argument("--all", action="store_true", help="include done and cancelled cards")
    close_parser = commands.add_parser("close")
    close_parser.add_argument("work_id")
    close_parser.add_argument("--state", choices=STATES[1:], default="done")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    try:
        if args.command == "list":
            result: Any = list_cards(project, include_settled=args.all)
        elif not settle_card(project, args.work_id, args.state):
            parser.exit(2, "work cards: no active card with that work id in this repository\n")
        else:
            result = {"work_id": args.work_id, "state": args.state}
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, f"work cards: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
