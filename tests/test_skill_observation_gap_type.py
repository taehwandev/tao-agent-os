"""An observation may name its gap, and the curator must carry that forward.

`signal` gives the category of a gap, not the gap. Candidates observed in an
earlier closeout were therefore unreviewable later — the record held only
`skill_id` and `signal`, so 18 of them accumulated unactionable. `gap_type`
closes that, but only if it stays a safe slug, never changes candidate identity,
and actually reaches the review queue.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_skill_curator import MAX_QUEUED_GAP_TYPES, _observed_gap_types, curate_observations
from agent_skill_learning import record_observation, review_candidate
from agent_skill_state import candidate_id, completed_path, review_queue_path


class RecordObservationGapType(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _record(self, occurrence_id, **kwargs):
        options = {"skill_id": "branch_cleanup", "signal": "missing_rule"}
        options.update(kwargs)
        return record_observation(self.root, occurrence_id=occurrence_id, **options)

    def _stored(self, result):
        return json.loads((self.root / result["relative_path"]).read_text(encoding="utf-8"))

    def test_gap_type_is_optional(self):
        result = self._record("occ-1")
        self.assertTrue(result["created"])
        self.assertNotIn("gap_type", self._stored(result))

    def test_gap_type_is_stored_when_given(self):
        result = self._record("occ-1", gap_type="missing_concurrent_session_precheck")
        self.assertTrue(result["created"])
        self.assertEqual(
            self._stored(result)["gap_type"], "missing_concurrent_session_precheck"
        )

    def test_unsafe_gap_type_is_refused(self):
        for unsafe in ("Not A Slug", "path/like", "with space", "-leading", "tab\there"):
            with self.subTest(unsafe=unsafe):
                result = self._record("occ-unsafe", gap_type=unsafe)
                self.assertFalse(result["created"])
                self.assertEqual(result["reason"], "unsafe_observation_fields")

    def test_blank_gap_type_is_treated_as_absent(self):
        result = self._record("occ-1", gap_type="   ")
        self.assertTrue(result["created"])
        self.assertNotIn("gap_type", self._stored(result))

    def test_gap_type_does_not_change_candidate_identity(self):
        expected = candidate_id("branch_cleanup", "missing_rule")
        with_gap = self._record("occ-1", gap_type="one_thing")
        without = self._record("occ-2")
        self.assertEqual(with_gap["candidate_id"], expected)
        self.assertEqual(without["candidate_id"], expected)

    def test_privacy_marker_is_preserved(self):
        result = self._record("occ-1", gap_type="a_gap")
        self.assertEqual(
            self._stored(result)["privacy"], "safe_slugs_and_opaque_ids_only"
        )

    def test_candidate_order_disambiguates_equal_timestamps(self):
        with patch(
            "agent_skill_learning._now",
            return_value="2026-08-11T00:00:00+00:00",
        ):
            first = self._record("occ-1", gap_type="gap_alpha")
            second = self._record("occ-2", gap_type="gap_beta")

        self.assertEqual(1, self._stored(first)["candidate_order"])
        self.assertEqual(2, self._stored(second)["candidate_order"])


class ObservedGapTypes(unittest.TestCase):
    def test_distinct_sorted_and_deduplicated(self):
        observations = [
            {"gap_type": "beta"},
            {"gap_type": "alpha"},
            {"gap_type": "beta"},
        ]
        self.assertEqual(_observed_gap_types(observations), ["alpha", "beta"])

    def test_missing_blank_and_unsafe_values_are_dropped(self):
        observations = [
            {},
            {"gap_type": ""},
            {"gap_type": "   "},
            {"gap_type": "Not A Slug"},
            {"gap_type": "kept_one"},
        ]
        self.assertEqual(_observed_gap_types(observations), ["kept_one"])

    def test_result_is_capped(self):
        observations = [{"gap_type": f"gap_{index}"} for index in range(20)]
        self.assertEqual(len(_observed_gap_types(observations)), MAX_QUEUED_GAP_TYPES)


class CuratorCarriesGapTypes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        import agent_skill_curator

        original = agent_skill_curator.state_lock
        self.addCleanup(lambda: setattr(agent_skill_curator, "state_lock", original))

    def test_queue_record_names_the_gaps(self):
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_concurrent_session_precheck",
        )
        curate_observations(self.root, min_occurrences=1)
        candidate = candidate_id("branch_cleanup", "missing_rule")
        queued = json.loads(
            (self.root / review_queue_path(candidate)).read_text(encoding="utf-8")
        )
        self.assertEqual(queued["gap_types"], ["missing_concurrent_session_precheck"])
        self.assertEqual(queued["status"], "review_ready")

    def test_queue_record_is_empty_list_when_no_gap_named(self):
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
        )
        curate_observations(self.root, min_occurrences=1)
        candidate = candidate_id("branch_cleanup", "missing_rule")
        queued = json.loads(
            (self.root / review_queue_path(candidate)).read_text(encoding="utf-8")
        )
        self.assertEqual(queued["gap_types"], [])

    def test_a_new_gap_reopens_a_completed_no_change_candidate(self):
        candidate = candidate_id("branch_cleanup", "missing_rule")
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curate_observations(self.root, min_occurrences=1)
        self.assertTrue(
            review_candidate(
                self.root,
                candidate,
                decision="no_change",
                min_occurrences=1,
            )["updated"]
        )
        self.assertTrue((self.root / completed_path(candidate)).exists())

        record_observation(
            self.root,
            occurrence_id="occ-2",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_error_policy",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual(curated["queued"], [candidate])
        self.assertFalse((self.root / completed_path(candidate)).exists())
        reopened = json.loads(
            (self.root / review_queue_path(candidate)).read_text(encoding="utf-8")
        )
        self.assertEqual(
            reopened["gap_types"],
            ["missing_error_policy", "missing_import_policy"],
        )

    def test_a_fifth_gap_reopens_and_enters_the_bounded_queue(self):
        candidate = candidate_id("branch_cleanup", "missing_rule")
        covered_gaps = ("gap_alpha", "gap_beta", "gap_delta", "gap_gamma")
        for index, gap_type in enumerate(covered_gaps, 1):
            record_observation(
                self.root,
                occurrence_id=f"occ-{index}",
                skill_id="branch_cleanup",
                signal="missing_rule",
                gap_type=gap_type,
            )
        curate_observations(self.root, min_occurrences=1)
        self.assertTrue(
            review_candidate(
                self.root,
                candidate,
                decision="no_change",
                min_occurrences=1,
            )["updated"]
        )

        record_observation(
            self.root,
            occurrence_id="occ-5",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="gap_zeta",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual(curated["queued"], [candidate])
        self.assertFalse((self.root / completed_path(candidate)).exists())
        reopened = json.loads(
            (self.root / review_queue_path(candidate)).read_text(encoding="utf-8")
        )
        self.assertEqual(len(reopened["gap_types"]), MAX_QUEUED_GAP_TYPES)
        self.assertIn("gap_zeta", reopened["gap_types"])


if __name__ == "__main__":
    unittest.main()
