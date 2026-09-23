"""Work cards follow one work id across runs and worktrees, and never block a hook."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_work_cards as cards  # noqa: E402

WORK_A = "a" * 32
WORK_B = "b" * 32


class WorkCardTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        state_home = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(self.root / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.project = self.root / "project"
        self.project.mkdir()
        self._git("init", "-q")
        self._git("-c", "user.email=t@example.com", "-c", "user.name=t",
                  "commit", "-q", "--allow-empty", "-m", "base")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.project), *args], check=True)

    def _evidence(self, work_id: str) -> Path:
        path = self.root / f"{work_id[:4]}-preflight.json"
        path.write_text(json.dumps({"work": {"id": work_id, "schema_version": 1}}))
        return path

    def _register(self, project: Path, runs: dict[str, str]) -> None:
        registry = project / ".tao" / "run-registry.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps({"schema_version": 1, "runs": [
            {"run_id": run, "state": state} for run, state in runs.items()
        ]}))

    def test_continued_runs_update_one_card_and_linked_worktrees_share_it(self) -> None:
        cards.open_card(self.project, WORK_A, summary="first  target\nline", command="task")
        worktree = self.root / "linked"
        self._git("worktree", "add", "-q", str(worktree), "-b", "slice")
        cards.open_card(worktree, WORK_A, summary="refined target", command="bugfix")

        [card] = cards.list_cards(self.project)
        self.assertEqual(("refined target", "bugfix", "active"),
                         (card["summary"], card["command"], card["state"]))
        self.assertEqual(str(worktree.resolve()), card["project"])

    def test_settled_cards_leave_the_open_list_and_do_not_resettle(self) -> None:
        cards.open_card(self.project, WORK_A, summary="finished work", command="task")
        cards.open_card(self.project, WORK_B, summary="dropped work", command="task")
        self.assertTrue(cards.settle_card(self.project, WORK_A, "done"))
        self.assertTrue(cards.settle_card(self.project, WORK_B, "cancelled"))
        self.assertFalse(cards.settle_card(self.project, WORK_A, "cancelled"))

        self.assertEqual([], cards.list_cards(self.project))
        settled = {c["work_id"]: c["state"] for c in cards.list_cards(self.project, include_settled=True)}
        self.assertEqual({WORK_A: "done", WORK_B: "cancelled"}, settled)
        with self.assertRaises(ValueError):
            cards.settle_card(self.project, WORK_A, "active")

    def test_restart_reactivates_a_settled_card(self) -> None:
        cards.open_card(self.project, WORK_A, summary="work", command="task")
        cards.settle_card(self.project, WORK_A, "done")
        cards.open_card(self.project, WORK_A, summary="work, continued", command="commit")
        [card] = cards.list_cards(self.project)
        self.assertEqual("active", card["state"])

    def test_start_lines_open_this_card_and_name_only_the_others(self) -> None:
        cards.open_card(self.project, WORK_B, summary="other unfinished work", command="task")
        self._register(self.project, {WORK_B: "interrupted"})
        lines = cards.start_lines(self.project, self._evidence(WORK_A), summary="this work", command="task")

        self.assertEqual(2, len(lines))
        self.assertIn(WORK_B, lines[1])
        self.assertIn("other unfinished work", lines[1])
        self.assertNotIn(WORK_A, "\n".join(lines))
        self.assertEqual(2, len(cards.list_cards(self.project)))

    def test_start_lines_cap_the_listing_and_count_the_rest(self) -> None:
        for digit in "12345":
            cards.open_card(self.project, digit * 32, summary=f"work {digit}", command="task")
        self._register(self.project, {digit * 32: "running" for digit in "12345"})
        lines = cards.start_lines(self.project, self._evidence(WORK_A), summary="", command="task")
        self.assertEqual(1 + cards.MAX_RECALL_ITEMS + 1, len(lines))
        self.assertIn("2 more", lines[-1])
        self.assertEqual(5, len(cards.list_cards(self.project)), "an empty summary opens no card")

    def test_hook_entry_points_swallow_unusable_inputs(self) -> None:
        missing = self.root / "missing.json"
        self.assertEqual([], cards.start_lines(self.project, missing, summary="x", command="task"))
        cards.settle_from_evidence(self.project, missing, "done")
        bad_id = self._evidence("not-a-work-id" + "0" * 19)
        self.assertEqual([], cards.start_lines(self.project, bad_id, summary="x", command="task"))

        (self.root / "state-home").mkdir(exist_ok=True)
        (self.root / "state-home" / cards.STORE_NAME).mkdir()
        database = self.root / "state-home" / cards.STORE_NAME / cards.DATABASE_NAME
        database.write_text("not a database")
        self.assertEqual([], cards.start_lines(self.project, self._evidence(WORK_A),
                                               summary="x", command="task"))
        cards.settle_from_evidence(self.project, self._evidence(WORK_A), "done")

    def test_future_schema_is_refused_rather_than_rewritten(self) -> None:
        cards.open_card(self.project, WORK_A, summary="work", command="task")
        database = self.root / "state-home" / cards.STORE_NAME / cards.DATABASE_NAME
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(ValueError, "schema version 99"):
            cards.list_cards(self.project)

    def test_idle_cards_of_any_state_are_pruned_and_recent_ones_kept(self) -> None:
        cards.open_card(self.project, WORK_A, summary="old done", command="task")
        cards.open_card(self.project, WORK_B, summary="old active", command="task")
        cards.settle_card(self.project, WORK_A, "done")
        cards.open_card(self.project, "d" * 32, summary="recent", command="task")
        stale = (datetime.now(timezone.utc) - cards.IDLE_RETENTION - timedelta(days=1)).isoformat()
        database = self.root / "state-home" / cards.STORE_NAME / cards.DATABASE_NAME
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE cards SET updated_at = ? WHERE work_id != ?", (stale, "d" * 32))

        cards.open_card(self.project, "c" * 32, summary="new work", command="task")
        remaining = {c["work_id"] for c in cards.list_cards(self.project, include_settled=True)}
        self.assertEqual({"d" * 32, "c" * 32}, remaining)

    def test_cli_lists_and_closes_by_work_id(self) -> None:
        cards.open_card(self.project, WORK_A, summary="work", command="task")
        with mock.patch("sys.stdout") as stdout:
            self.assertEqual(0, cards._main(["--project", str(self.project), "close", WORK_A]))
        self.assertIn('"state": "done"', "".join(call.args[0] for call in stdout.write.call_args_list))
        with self.assertRaises(SystemExit) as exit_info, mock.patch("sys.stderr"):
            cards._main(["--project", str(self.project), "close", WORK_A])
        self.assertEqual(2, exit_info.exception.code)

    def test_a_lookup_creates_nothing_on_disk(self) -> None:
        state_home = self.root / "state-home"
        self.assertEqual([], cards.list_cards(self.project, include_settled=True))
        with mock.patch("sys.stdout"):
            self.assertEqual(0, cards._main(["--project", str(self.project), "list", "--all"]))
        self.assertFalse(state_home.exists(), "a lookup must not create the store")

        # An existing but empty database gains no table, pragma or journal.
        (state_home / cards.STORE_NAME).mkdir(parents=True)
        database = state_home / cards.STORE_NAME / cards.DATABASE_NAME
        sqlite3.connect(database).close()
        self.assertEqual([], cards.list_cards(self.project))
        with sqlite3.connect(database) as connection:
            self.assertEqual([], connection.execute("SELECT name FROM sqlite_master").fetchall())
            self.assertEqual(0, connection.execute("PRAGMA user_version").fetchone()[0])

    def test_start_skips_and_settles_cards_whose_run_cannot_finish(self) -> None:
        removed = self.root / "removed-worktree"
        self._git("worktree", "add", "-q", str(removed), "-b", "gone")
        live, finished, vanished, unknown = "1" * 32, "2" * 32, "3" * 32, "4" * 32
        cards.open_card(self.project, live, summary="still running", command="task")
        cards.open_card(self.project, finished, summary="completed elsewhere", command="task")
        cards.open_card(self.project, unknown, summary="never registered", command="task")
        cards.open_card(removed, vanished, summary="worktree removed", command="task")
        self._register(self.project, {live: "running", finished: "completed"})
        self._git("worktree", "remove", "--force", str(removed))

        lines = cards.start_lines(self.project, self._evidence(WORK_A), summary="", command="task")

        self.assertEqual(2, len(lines), lines)
        self.assertIn(live, lines[1])
        states = {c["work_id"]: c["state"] for c in cards.list_cards(self.project, include_settled=True)}
        self.assertEqual(
            {live: "active", finished: "done", vanished: "cancelled", unknown: "cancelled"}, states
        )

    def test_start_records_the_run_id_the_registry_is_asked_about(self) -> None:
        run = "e" * 32
        evidence = self.root / ".tao" / "runs" / run / "preflight.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({"work": {"id": WORK_A, "schema_version": 1}}))
        cards.start_lines(self.project, evidence, summary="continued work", command="task")
        [card] = cards.list_cards(self.project)
        self.assertEqual(run, card["run_id"])

    def test_a_version_one_store_is_read_then_upgraded_on_write(self) -> None:
        directory = self.root / "state-home" / cards.STORE_NAME
        directory.mkdir(parents=True)
        with closing(sqlite3.connect(directory / cards.DATABASE_NAME)) as connection, connection:
            connection.execute(cards._SCHEMA.replace("    run_id TEXT NOT NULL DEFAULT '',\n", ""))
            connection.execute(
                "INSERT INTO cards VALUES (?, ?, 'old', 'task', ?, 'active', 't', 't')",
                (cards.repository_key(self.project), WORK_B, str(self.project)),
            )
            connection.execute("PRAGMA user_version = 1")
        self.assertEqual("", cards.list_cards(self.project)[0]["run_id"])
        cards.open_card(self.project, WORK_A, summary="new", command="task")
        self.assertEqual({WORK_A: WORK_A, WORK_B: ""},
                         {c["work_id"]: c["run_id"] for c in cards.list_cards(self.project)})


if __name__ == "__main__":
    unittest.main()
