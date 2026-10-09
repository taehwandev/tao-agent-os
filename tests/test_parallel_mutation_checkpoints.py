"""Parallel tool calls share one pre-mutation bracket; an abandoned one still refuses."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_checkpoint import (  # noqa: E402
    PARALLEL_MUTATION_WINDOW_SECONDS,
    _pending,
)
from agent_continuation_store import ContinuationPacketError  # noqa: E402
from agent_continuation_packet import _checkpoint as validate_checkpoint  # noqa: E402

BEFORE = {"head": "a" * 40, "worktree_fingerprint": "b" * 64, "worktree_signature": "c" * 64}
AFTER = {**BEFORE, "worktree_fingerprint": "d" * 64}


def _pending_record(paths: list[str], *, age_seconds: float = 1.0, outstanding: int | None = None) -> dict:
    record = {
        "kind": "update",
        "paths": paths,
        "project": BEFORE,
        "rules": BEFORE,
        "started_at": (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat(),
    }
    if outstanding is not None:
        record["outstanding"] = outstanding
    return record


def _base(pending: dict | None) -> dict:
    return {"checkpoint": {"mutation_pending": pending}}


DRIFT_CHANGED = {"project": AFTER, "rules": BEFORE}


class ParallelMutationTest(unittest.TestCase):
    def test_a_sibling_started_moments_ago_is_merged(self) -> None:
        merged = _pending("pre_mutation", _base(_pending_record(["a.txt"])),
                          {"kind": "update", "paths": ["b.txt"]}, DRIFT_CHANGED)

        self.assertEqual(["a.txt", "b.txt"], merged["paths"])
        self.assertEqual(2, merged["outstanding"])
        self.assertEqual(BEFORE, merged["project"])

    def test_the_bracket_closes_only_on_the_last_post(self) -> None:
        shared = _pending_record(["a.txt", "b.txt", "c.txt"], outstanding=3)

        after_one = _pending("post_mutation", _base(shared), None, DRIFT_CHANGED)
        after_two = _pending("post_mutation", _base(after_one), None, DRIFT_CHANGED)
        after_three = _pending("post_mutation", _base(after_two), None, DRIFT_CHANGED)

        self.assertEqual(2, after_one["outstanding"])
        self.assertNotIn("outstanding", after_two)
        self.assertIsNone(after_three)

    def test_an_abandoned_pending_still_refuses(self) -> None:
        stale = _pending_record(["a.txt"], age_seconds=PARALLEL_MUTATION_WINDOW_SECONDS + 30)

        with self.assertRaises(ContinuationPacketError) as raised:
            _pending("pre_mutation", _base(stale), {"kind": "update", "paths": ["b.txt"]}, DRIFT_CHANGED)
        self.assertEqual("mutation_already_pending", raised.exception.failures[0]["rule"])

    def test_the_merged_record_passes_the_packet_schema(self) -> None:
        for record in (_pending_record(["a.txt"]), _pending_record(["a.txt", "b.txt"], outstanding=2)):
            with self.subTest(record=record):
                failures: list = []
                validate_checkpoint(
                    {"last_completed": None, "first_unfinished": None, "mutation_pending": record},
                    failures,
                )
                self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
