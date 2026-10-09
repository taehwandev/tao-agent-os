"""A failed finish stays repairable, and a write chained ahead of start is explained."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_hook_gate_records as records  # noqa: E402
import claude_pretool_gate as gate  # noqa: E402


class StartAfterWriteNoteTest(unittest.TestCase):
    def test_a_write_chained_ahead_of_start_is_explained(self) -> None:
        for command in (
            "git add .agent && git diff --cached --stat; /Users/x/.tao/bin/tao-hook start --project p",
            'cd repo && git add -A && python3 "$TAO_ROOT/scripts/agent-hook.py" start --project p',
        ):
            with self.subTest(command=command):
                self.assertIn("Run the start on its own first", gate._start_after_write_note(command))

    def test_a_start_at_the_head_of_the_line_needs_no_note(self) -> None:
        for command in (
            "/Users/x/.tao/bin/tao-hook start --project p --request r",
            "TAO_HOOK_SOFT_FAIL=1 /Users/x/.tao/bin/tao-hook start --project p",
            "git add -A",
            "",
        ):
            with self.subTest(command=command):
                self.assertEqual("", gate._start_after_write_note(command))


class FailedRunIsResumableTest(unittest.TestCase):
    def test_the_gate_looks_for_a_failed_run_with_the_paused_ones(self) -> None:
        asked: list[frozenset] = []

        class Reader:
            @staticmethod
            def resolve_runtime_evidence(root, session, states=None, *, latest_of_several=False):
                asked.append(states)
                return None

        with patch.object(gate, "_run_evidence_reader", return_value=Reader):
            gate.paused_session_evidence(Path("/tmp"), "session")

        self.assertEqual([frozenset({"interrupted", "blocked", "failed"})], asked)


class FailedRunSameSessionClaimTest(unittest.TestCase):
    def test_its_own_session_may_reclaim_a_failed_run_while_it_lives(self) -> None:
        import agent_continuation_claim as claim

        binding = {
            "runtime_session": {"runtime": "claude", "session_id": "s"},
            "route": {"lifecycle_version": 2},
        }
        with patch.object(claim, "runtime_session", return_value={"runtime": "claude", "session_id": "s"}):
            for state, expected in (("failed", True), ("interrupted", True), ("running", False), ("completed", False)):
                with self.subTest(state=state):
                    self.assertEqual(
                        expected,
                        claim.stopped_session_matches({"state": state, "resume_generation": 0}, binding),
                    )


class HookEvidenceFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.failed = self._run("f" * 32)
        self.completed = self._run("c" * 32)
        self.found: dict[str, Path | None] = {"active": None, "failed": self.failed, "completed": None}

    def _run(self, run_id: str) -> Path:
        evidence = self.project / ".tao" / "runs" / run_id / "preflight.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("{}", encoding="utf-8")
        return evidence

    def _resolve(self, project, session, states=None, *, latest_of_several=False):
        key = "active" if states is None else next(iter(states))
        return self.found.get(key)

    def _path(self, hook: str = "gate") -> Path:
        args = argparse.Namespace(evidence=None, project=self.project, hook=hook)
        with (
            patch.object(records, "runtime_session", return_value={"runtime": "claude", "session_id": "s"}),
            patch.object(records, "resolve_runtime_evidence", self._resolve),
        ):
            return records.preflight_evidence_path(args)

    def test_a_failed_run_is_used_before_the_legacy_preflight(self) -> None:
        self.assertEqual(self.failed, self._path())

    def test_a_later_completed_run_retires_the_failed_one(self) -> None:
        os.utime(self.failed, (1, 1))
        self.found["completed"] = self.completed
        self.assertEqual(self.project / ".tao" / "preflight.json", self._path())

    def test_a_failed_run_newer_than_the_completed_one_still_wins(self) -> None:
        os.utime(self.completed, (1, 1))
        self.found["completed"] = self.completed
        self.assertEqual(self.failed, self._path())

    def test_an_active_run_is_still_preferred(self) -> None:
        active = self._run("a" * 32)
        self.found["active"] = active
        self.assertEqual(active, self._path())


if __name__ == "__main__":
    unittest.main()
