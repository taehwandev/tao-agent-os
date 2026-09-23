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
from agent_run_registry import REGISTRY_FILENAME, SETTLED_RUN_STATES
from support.global_state import global_state_dir, user_store_write_error


# Version 2 adds the run id, so a listing can ask the run's own registry
# whether the work is still unfinished.
SCHEMA_VERSION = 2
STORE_NAME = "work-cards"
DATABASE_NAME = "cards.sqlite3"
WORK_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
STATES = ("active", "done", "cancelled")
MAX_SUMMARY_CHARS = 200
MAX_RECALL_ITEMS = 3
# How many other open cards one start examines against their run registries.
MAX_LIVENESS_CHECKS = 20
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
    run_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (repo, work_id)
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_version(connection: sqlite3.Connection) -> int:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, SCHEMA_VERSION):
        connection.close()
        raise ValueError(f"unsupported work-card schema version {version}")
    return version


def _connect() -> sqlite3.Connection:
    """The write path: creates the store and brings its schema current."""
    refusal = user_store_write_error()
    if refusal:
        raise ValueError(refusal)
    directory = global_state_dir() / STORE_NAME
    if directory.is_symlink():
        raise ValueError("work-card directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(directory / DATABASE_NAME, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    _check_version(connection)
    connection.execute(_SCHEMA)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(cards)")}
    if "run_id" not in columns:
        connection.execute("ALTER TABLE cards ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return connection


def _connect_readonly() -> sqlite3.Connection | None:
    """The lookup path: never creates a directory, database, table or pragma.

    None means there is nothing to read yet, which a lookup reports as empty.
    """
    path = global_state_dir() / STORE_NAME / DATABASE_NAME
    if path.parent.is_symlink() or not path.is_file():
        return None
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        _check_version(connection)
    except sqlite3.OperationalError:
        # Some SQLite builds cannot open a WAL store read-only once the last
        # writer removed its shared-memory file. Without that file no WAL
        # content is pending, so the main file alone is the whole store.
        connection.close()
        connection = sqlite3.connect(f"{uri}&immutable=1", uri=True, timeout=2)
        _check_version(connection)
    connection.row_factory = sqlite3.Row
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cards'"
    ).fetchone()
    if table is None:
        connection.close()
        return None
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


def open_card(
    project: Path, work_id: str, *, summary: str, command: str, run_id: str = ""
) -> None:
    """Create the work's card, or reactivate it when a continued run starts."""
    now = _now()
    run_id = _work_id(run_id) if run_id else work_id
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO cards (repo, work_id, summary, command, project, state, "
            "created_at, updated_at, run_id) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?) "
            "ON CONFLICT (repo, work_id) DO UPDATE SET summary = excluded.summary, "
            "command = excluded.command, project = excluded.project, "
            "state = 'active', updated_at = excluded.updated_at, run_id = excluded.run_id",
            (repository_key(project), _work_id(work_id), _summary(summary), command,
             str(project.resolve()), now.isoformat(), now.isoformat(), run_id),
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
    """Read cards without writing anything; a missing store lists nothing."""
    states = STATES if include_settled else ("active",)
    connection = _connect_readonly()
    if connection is None:
        return []
    with closing(connection):
        rows = connection.execute(
            f"SELECT * FROM cards WHERE repo = ? AND state IN ({','.join('?' * len(states))}) "
            "ORDER BY updated_at DESC",
            (repository_key(project), *states),
        ).fetchall()
    cards = []
    for row in rows:
        card = dict(row)
        card.pop("repo", None)
        card.setdefault("run_id", "")  # a version 1 store has no run ids yet
        cards.append(card)
    return cards


def _registry_runs(project: Path, cache: dict[Path, dict[str, str]]) -> dict[str, str]:
    """Run id -> state from a project's registry; read only, empty when absent."""
    if project not in cache:
        runs: dict[str, str] = {}
        try:
            payload = json.loads((project / ".tao" / REGISTRY_FILENAME).read_text(encoding="utf-8"))
            for run in payload.get("runs", []) if isinstance(payload, dict) else []:
                if isinstance(run, dict) and isinstance(run.get("run_id"), str):
                    runs[run["run_id"]] = str(run.get("state") or "")
        except (OSError, ValueError, AttributeError):
            pass
        cache[project] = runs
    return cache[project]


def _stale_state(card: dict[str, Any], cache: dict[Path, dict[str, str]]) -> str:
    """"" for unfinished work, else the state an abandoned card settles to.

    A card is unfinished only while its project still exists and that
    project's registry holds its run in an unsettled state. A removed
    worktree, a missing registry or an unknown run all mean nobody can finish
    it any more; a run the registry already settled means its card missed the
    closeout that would have settled it.
    """
    project = Path(card["project"])
    if not project.is_dir():
        return "cancelled"
    state = _registry_runs(project, cache).get(card.get("run_id") or card["work_id"], "")
    if not state:
        return "cancelled"
    if state in SETTLED_RUN_STATES:
        return "done" if state == "completed" else "cancelled"
    return ""


def open_card_lines(project: Path, current_work_id: str, *, settle_stale: bool = False) -> list[str]:
    """Name other unfinished work in this repository as reference context.

    At most MAX_LIVENESS_CHECKS cards are checked; the rest are only counted.
    `settle_stale` (the start path) also settles the abandoned ones it found.
    """
    others = [card for card in list_cards(project) if card["work_id"] != current_work_id]
    if not others:
        return []
    cache: dict[Path, dict[str, str]] = {}
    live, stale = [], []
    for card in others[:MAX_LIVENESS_CHECKS]:
        settled = _stale_state(card, cache)
        (stale if settled else live).append((card, settled))
    try:
        for card, settled in stale if settle_stale else ():
            settle_card(project, card["work_id"], settled)
    except (OSError, ValueError, sqlite3.Error):
        pass  # Settling is housekeeping; the listing already excludes them.
    unchecked = max(0, len(others) - MAX_LIVENESS_CHECKS)
    if not live and not unchecked:
        return []
    lines = [
        f"- {card['work_id']} [{card['command']}, {card['updated_at'][:10]}] {card['summary']}"
        for card, _settled in live[:MAX_RECALL_ITEMS]
    ]
    hidden = len(live) - len(lines) + unchecked
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
        # Run evidence lives at `.tao/runs/<run id>/preflight.json`.
        run_id = evidence.parent.name if WORK_ID_RE.fullmatch(evidence.parent.name) else ""
        if summary.strip():
            try:
                open_card(project, work_id, summary=summary, command=command, run_id=run_id)
            except (OSError, ValueError, sqlite3.Error):
                pass  # An unwritable store still lets the other cards be named.
        return open_card_lines(project, work_id, settle_stale=True)
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
