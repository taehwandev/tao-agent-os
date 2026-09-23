"""Blocks before finish are learned from, surfaced when recurring, and retired.

The lesson store only ever heard about finish failures, so a denied edit or a
refused start could recur without limit and nobody saw it. These tests pin the
recording (content-free, rate limited, never changing a verdict), the start and
retrospective surfacing, the resolution paths, and the compaction pass.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_block_lessons as blocks
import claude_pretool_gate
from agent_global_lessons import _inbox_summary
from agent_lesson_store import promote_fixed_candidate, promote_repaired_candidates


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compact = _load("lessons_compact_blocks_test", "lessons-compact.py")
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class _StateHome(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.inbox = self.state / "lessons" / "inbox"
        environment = patch.dict(os.environ, {"TAO_STATE_HOME": str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)

    def records(self) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in self.inbox.glob("*.json")]


class PretoolDenialRecordingTests(_StateHome):
    def _deny(self, reason: str, code: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, claude_pretool_gate.deny(reason, code))
        return output.getvalue()

    def test_a_denial_records_one_content_free_candidate(self) -> None:
        claude_pretool_gate._BLOCK_SESSION["session_id"] = "session-secret-id"
        self._deny(
            "Tao: `git push --force origin main` from /Users/someone/private/repo was denied",
            "worktree_isolation",
        )

        records = self.records()
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("pretool_gate", record["source"])
        self.assertEqual("worktree_isolation", record["root_cause"])
        self.assertEqual("safe_slugs_only", record["privacy"])
        self.assertEqual(1, record["occurrence_count"])
        stored = json.dumps(record) + json.dumps(json.loads((self.state / "index.json").read_text()))
        for fragment in ("git push", "/Users/someone", "private", "session-secret-id", "denied"):
            self.assertNotIn(fragment, stored)

    def test_an_unknown_code_is_not_recorded(self) -> None:
        self._deny("anything", "not_a_known_code")
        self.assertEqual([], self.records())

    def test_the_verdict_is_unchanged_when_the_store_is_unwritable(self) -> None:
        expected = self._deny("reason", "worktree_isolation")
        blocker = self.state / "not-a-directory"
        blocker.write_text("file", encoding="utf-8")
        with patch.dict(os.environ, {"TAO_STATE_HOME": str(blocker)}):
            actual = self._deny("reason", "worktree_isolation")
        self.assertEqual(expected, actual)
        self.assertEqual("deny", json.loads(actual)["hookSpecificOutput"]["permissionDecision"])

    def test_decide_binds_the_session_for_the_recorder(self) -> None:
        with patch.object(claude_pretool_gate, "gate_enabled", return_value=True):
            with contextlib.redirect_stdout(io.StringIO()):
                claude_pretool_gate.decide({"tool_name": "Read", "session_id": "abc"})
        self.assertEqual("abc", claude_pretool_gate._BLOCK_SESSION["session_id"])


class RateLimitTests(_StateHome):
    def test_same_session_within_the_window_counts_once(self) -> None:
        first = blocks.record_block("pretool_gate", "file_sprawl_budget", session_id="s1", now=NOW)
        second = blocks.record_block(
            "pretool_gate", "file_sprawl_budget", session_id="s1", now=NOW + timedelta(seconds=30)
        )
        self.assertTrue(first["created"])
        self.assertEqual("rate_limited", second["reason"])
        self.assertEqual(1, self.records()[0]["occurrence_count"])

    def test_another_session_or_a_later_window_counts_again(self) -> None:
        blocks.record_block("pretool_gate", "file_sprawl_budget", session_id="s1", now=NOW)
        blocks.record_block("pretool_gate", "file_sprawl_budget", session_id="s2", now=NOW)
        later = NOW + timedelta(seconds=blocks.RATE_LIMIT_SECONDS + 1)
        blocks.record_block("pretool_gate", "file_sprawl_budget", session_id="s1", now=later)
        self.assertEqual(3, self.records()[0]["occurrence_count"])

    def test_a_test_run_without_a_state_home_writes_nothing(self) -> None:
        with patch.dict(os.environ, {"TAO_STATE_HOME": ""}):
            result = blocks.record_block("pretool_gate", "file_sprawl_budget", session_id="s1")
        self.assertEqual("store_not_writable_here", result["reason"])


def _record(lesson_id: str, count: int, seen: datetime, **extra) -> dict:
    record = {
        "lesson_id": lesson_id,
        "occurrence_count": count,
        "last_seen_at": seen.isoformat(),
        "status": "candidate",
        "source": "pretool_gate",
        "block_signature": "pretool_gate/worktree_isolation",
        "root_cause": "worktree_isolation",
        "failure_type": "prefinish_block",
        "next_action": "work_in_a_linked_worktree",
        "promotion_status": "repair_required",
    }
    record.update(extra)
    return record


class SurfacingTests(_StateHome):
    def setUp(self) -> None:
        super().setUp()
        self.inbox.mkdir(parents=True)

    def _write(self, record: dict) -> None:
        (self.inbox / f"{record['lesson_id']}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_start_shows_recurring_and_hides_below_threshold_stale_and_old(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        self._write(_record("a" * 16, 5, recent))
        self._write(_record("b" * 16, 2, recent))
        self._write(_record("c" * 16, 9, recent - timedelta(days=15)))
        self._write(_record("d" * 16, 7, recent, status="stale"))
        self._write(_record("e" * 16, 8, recent - timedelta(days=8)))

        summary = _inbox_summary(self.inbox)
        self.assertEqual(["a" * 16], [item["lesson_id"] for item in summary["recurring"]])
        # The older single-signature notice skips stale records too.
        self.assertEqual("e" * 16, summary["top_recurrence"]["lesson_id"])
        lines = blocks.recurring_lines(summary["recurring"])
        self.assertEqual(
            [f"Recurring block: pretool_gate/worktree_isolation x5 (7d) "
             f"-> work_in_a_linked_worktree [lesson {'a' * 16}]"],
            lines,
        )
        guidance = blocks.retrospective_guidance_line(summary)
        self.assertIn("fixed_lesson=<lesson id>", guidance)
        self.assertIn("a" * 16, guidance)

    def test_nothing_recurring_prints_nothing(self) -> None:
        self._write(_record("b" * 16, 2, datetime.now(timezone.utc)))
        summary = _inbox_summary(self.inbox)
        self.assertEqual([], blocks.recurring_lines(summary["recurring"]))
        self.assertEqual("", blocks.retrospective_guidance_line(summary))

    def test_at_most_three_are_shown_highest_first(self) -> None:
        recent = datetime.now(timezone.utc)
        for index, count in enumerate((3, 9, 4, 6)):
            self._write(_record(f"{index:016x}", count, recent))
        counts = [item["occurrence_count"] for item in _inbox_summary(self.inbox)["recurring"]]
        self.assertEqual([9, 6, 4], counts)


class ResolutionTests(_StateHome):
    def _recurring_ids(self) -> list[str]:
        return [item["lesson_id"] for item in _inbox_summary(self.inbox)["recurring"]]

    def _record_three(self) -> str:
        for session in ("s1", "s2", "s3"):
            blocks.record_block("agent_hook_start", "run_claim_conflict", session_id=session)
        return blocks.block_lesson_id("agent_hook_start", "run_claim_conflict")

    def test_a_clean_finish_naming_the_fixed_lesson_retires_it(self) -> None:
        lesson_id = self._record_three()
        self.assertEqual([lesson_id], self._recurring_ids())
        ledger = {"entries": [{"gate": "retrospective check", "fields": {"fixed_lesson": lesson_id}}]}

        self.assertEqual(lesson_id, blocks.resolve_fixed_lesson(ledger, {"agent_run_id": "run-1"}))
        self.assertEqual([], self._recurring_ids())
        promoted = json.loads((self.state / "lessons" / "promoted" / f"{lesson_id}.json").read_text())
        self.assertEqual("retrospective_fix_verified", promoted["promotion_status"])

    def test_an_invalid_or_unknown_lesson_id_resolves_nothing(self) -> None:
        self._record_three()
        for value in ("../../etc", "f" * 16):
            ledger = {"entries": [{"gate": "retrospective check", "fields": {"fixed_lesson": value}}]}
            self.assertEqual("", blocks.resolve_fixed_lesson(ledger, {"agent_run_id": "run-1"}))

    def test_a_run_bound_block_is_retired_by_that_runs_repair_receipt(self) -> None:
        blocks.record_block("run_reconcile", "resume_drift_refused", run_id="run-42")
        result = promote_repaired_candidates(self.state, occurrence_id="run-42", receipt_id="r1")
        self.assertEqual([blocks.block_lesson_id("run_reconcile", "resume_drift_refused")], result["promoted"])

    def test_a_promoted_lesson_resumes_counting_when_it_returns(self) -> None:
        lesson_id = self._record_three()
        promote_fixed_candidate(self.state, lesson_id, receipt_id="x", promotion_status="repair_verified")
        blocks.record_block("agent_hook_start", "run_claim_conflict", session_id="s4")
        self.assertEqual(4, json.loads((self.inbox / f"{lesson_id}.json").read_text())["occurrence_count"])


class StartRefusalTests(_StateHome):
    def test_compact_start_problems_map_to_fixed_slugs(self) -> None:
        agent_hook = _load("agent_hook_blocks_test", "agent-hook.py")
        self.assertEqual("start_intent_slug_invalid", agent_hook._start_problem_code("--intent `x` must be"))
        self.assertEqual(
            "start_effect_approval_mismatch",
            agent_hook._start_problem_code("--approved-effect git_write is unnecessary"),
        )
        self.assertEqual("start_arguments_invalid", agent_hook._start_problem_code("anything else"))
        agent_hook._learn_start_block("run_claim_conflict")
        self.assertEqual(["agent_hook_start"], [record["source"] for record in self.records()])


class CompactionTests(_StateHome):
    def setUp(self) -> None:
        super().setUp()
        self.inbox.mkdir(parents=True)

    def _write(self, name: str, record: dict) -> None:
        (self.inbox / name).write_text(json.dumps(record), encoding="utf-8")

    def _run(self, *extra: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            compact.main(["--state-home", str(self.state), *extra])
        return output.getvalue()

    def _seed(self) -> tuple[Path, Path]:
        fresh = datetime.now(timezone.utc) - timedelta(days=1)
        old = datetime.now(timezone.utc) - timedelta(days=20)
        first = _record("a" * 16, 2, fresh, created_at=fresh.isoformat(), occurrence_keys=["k1"])
        second = _record("a" * 16, 3, fresh, created_at=(fresh - timedelta(hours=1)).isoformat(),
                         occurrence_keys=["k2"])
        self._write(f"{'a' * 16}.json", first)
        self._write(f"20260901-000000-{'a' * 16}.json", second)
        self._write(f"{'b' * 16}.json", _record("b" * 16, 4, old, created_at=old.isoformat()))
        old_lock = self.inbox / f".{'b' * 16}.json.lock"
        new_lock = self.inbox / f".{'a' * 16}.json.lock"
        old_lock.write_bytes(b"")
        new_lock.write_bytes(b"")
        two_days_ago = time.time() - 2 * 24 * 60 * 60
        os.utime(old_lock, (two_days_ago, two_days_ago))
        return old_lock, new_lock

    def test_dry_run_reports_and_changes_nothing(self) -> None:
        old_lock, _ = self._seed()
        before = sorted(path.name for path in self.inbox.iterdir())
        report = self._run()
        self.assertIn("lessons to mark stale (unseen 14+ days): 1", report)
        self.assertIn("lock files older than a day: 1", report)
        self.assertEqual(before, sorted(path.name for path in self.inbox.iterdir()))
        self.assertTrue(old_lock.exists())

    def test_apply_merges_marks_stale_and_drops_old_locks(self) -> None:
        old_lock, new_lock = self._seed()
        self._run("--apply")

        merged = json.loads((self.inbox / f"{'a' * 16}.json").read_text())
        self.assertEqual(5, merged["occurrence_count"])
        self.assertEqual(["k2", "k1"], merged["occurrence_keys"])
        self.assertEqual("candidate", merged["status"])
        self.assertEqual({f"{'a' * 16}.json", f"{'b' * 16}.json"}, {p.name for p in self.inbox.glob("*.json")})
        self.assertEqual("stale", json.loads((self.inbox / f"{'b' * 16}.json").read_text())["status"])
        self.assertFalse(old_lock.exists())
        self.assertTrue(new_lock.exists())
        self.assertEqual([], [item for item in _inbox_summary(self.inbox)["recurring"]
                              if item["lesson_id"] == "b" * 16])

    def test_a_stale_signature_that_returns_is_open_again(self) -> None:
        self._seed()
        self._run("--apply")
        stale_id = blocks.block_lesson_id("pretool_gate", "worktree_isolation")
        (self.inbox / f"{'b' * 16}.json").rename(self.inbox / f"{stale_id}.json")
        path = self.inbox / f"{stale_id}.json"
        record = json.loads(path.read_text())
        record["lesson_id"] = stale_id
        path.write_text(json.dumps(record), encoding="utf-8")

        blocks.record_block("pretool_gate", "worktree_isolation", session_id="s9")
        reopened = json.loads(path.read_text())
        self.assertEqual("candidate", reopened["status"])
        self.assertEqual(5, reopened["occurrence_count"])
        self.assertIn(stale_id, [item["lesson_id"] for item in _inbox_summary(self.inbox)["recurring"]])


if __name__ == "__main__":
    unittest.main()
