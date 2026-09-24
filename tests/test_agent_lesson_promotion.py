from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_lesson_store as store
from agent_global_lessons import retrospective_candidate


class LessonPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lesson = retrospective_candidate({"missed_gates": ["tests"], "gate_signals": []})
        self.lesson_id = self.lesson["lesson_id"]
        self.inbox = self.root / "lessons" / "inbox" / f"{self.lesson_id}.json"
        self.promoted = self.root / "lessons" / "promoted" / self.inbox.name
        self.record("repaired-run")

    def record(self, occurrence):
        return store.upsert_retrospective_candidate(
            self.root, dict(self.lesson), occurrence_id=occurrence
        )

    def promote(self):
        return store.promote_repaired_candidates(
            self.root, occurrence_id="repaired-run", receipt_id="receipt"
        )

    def test_arrival_after_observation_preserves_newer_candidate(self):
        original = store._promote_one

        def promote_after_arrival(*args, **kwargs):
            self.assertTrue(self.record("new-run")["created"])
            return original(*args, **kwargs)

        with patch.object(store, "_promote_one", side_effect=promote_after_arrival):
            self.assertEqual([], self.promote()["promoted"])
        self.assertEqual(2, json.loads(self.inbox.read_text())["occurrence_count"])
        self.assertFalse(self.promoted.exists())

    def test_writer_during_promotion_remains_open_with_lifetime_baseline(self):
        entered = threading.Event()
        original_lock = store.state_lock
        original_write = store.atomic_write_json
        future = None
        held_by_promotion = set()

        @contextmanager
        def observed_lock(path):
            if threading.current_thread() is not threading.main_thread() and path == self.inbox:
                entered.set()
            with original_lock(path):
                is_promoter = threading.current_thread() is threading.main_thread()
                if is_promoter:
                    held_by_promotion.add(path)
                try:
                    yield
                finally:
                    if is_promoter:
                        held_by_promotion.remove(path)

        with ThreadPoolExecutor(max_workers=1) as pool:
            def write_while_recording(path, payload):
                nonlocal future
                if path == self.promoted:
                    future = pool.submit(self.record, "new-run")
                    self.assertTrue(entered.wait(3))
                    # Force the losing interleaving when no inbox lock is
                    # held. With the fix, the writer instead waits until
                    # promotion releases the lock. No scheduling sleep needed.
                    if self.inbox not in held_by_promotion:
                        future.result(timeout=3)
                return original_write(path, payload)

            with patch.object(store, "state_lock", side_effect=observed_lock), patch.object(
                store, "atomic_write_json", side_effect=write_while_recording
            ):
                self.assertEqual([self.lesson_id], self.promote()["promoted"])
                self.assertTrue(future.result(timeout=3)["created"])
        current = json.loads(self.inbox.read_text())
        self.assertEqual(2, current["occurrence_count"])
        self.assertEqual(1, sum(current["recent_occurrences"].values()))
        self.assertEqual(1, json.loads(self.promoted.read_text())["occurrence_count"])
        index = json.loads((self.root / "index.json").read_text())
        self.assertEqual(f"lessons/inbox/{self.inbox.name}", index["lessons"][0]["relative_path"])

    def test_same_snapshot_cannot_be_promoted_twice(self):
        snapshot = json.loads(self.inbox.read_text())
        self.assertEqual([self.lesson_id], self.promote()["promoted"])
        self.assertFalse(store._promote_one(
            self.root, self.inbox, snapshot, receipt_id="stale-receipt"
        ))
        self.assertEqual("receipt", json.loads(self.promoted.read_text())["repair_receipt_id"])
