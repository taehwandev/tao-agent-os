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
from agent_skill_feedback import _declined_curation_details
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

    def test_an_unnamed_gap_against_a_closed_candidate_is_reported(self):
        """Declining to queue is right here; declining in silence is not.

        A recurrence that names no gap carries nothing a closed review did not
        already decide, so it must not reopen the candidate. But `queued 0` is
        indistinguishable from `nothing was observed`, and the way forward --
        name the gap -- appears nowhere. A closeout that hits this reads its own
        observation as accepted and never learns why review never came.
        """

        candidate = candidate_id("branch_cleanup", "missing_rule")
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curate_observations(self.root, min_occurrences=1)
        review_candidate(
            self.root, candidate, decision="no_change", min_occurrences=1
        )

        record_observation(
            self.root,
            occurrence_id="occ-2",
            skill_id="branch_cleanup",
            signal="missing_rule",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual([], curated["queued"])
        self.assertEqual(
            [{"candidate_id": candidate, "reason": "closed_review_no_new_gap"}],
            curated["not_queued"],
        )

    def test_a_queued_group_is_not_reported_as_declined(self):
        # The report must distinguish declined from queued, or it is noise.
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual([candidate_id("branch_cleanup", "missing_rule")], curated["queued"])
        self.assertEqual([], curated["not_queued"])

    def test_the_hook_prints_the_reason_and_the_way_forward(self):
        """The reason has to reach the caller through the hook that prints.

        Written first against `_declined_curation_details` alone, which proved
        the formatting and nothing about the wiring: deleting the line that
        calls it left that test green. `record_skill_curation` builds the lines
        the hook prints, so the assertion belongs there.
        """

        import agent_skill_feedback

        candidate = candidate_id("branch_cleanup", "missing_rule")
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curate_observations(self.root, min_occurrences=1)
        review_candidate(self.root, candidate, decision="no_change", min_occurrences=1)
        record_observation(
            self.root,
            occurrence_id="occ-2",
            skill_id="branch_cleanup",
            signal="missing_rule",
        )

        with patch.object(agent_skill_feedback, "state_home", return_value=self.root):
            _result, details = agent_skill_feedback.record_skill_curation(
                min_occurrences=1
            )

        printed = "\n".join(details)
        self.assertIn("observations not queued for review: 1", printed)
        self.assertIn(candidate, printed)
        self.assertIn("closed_review_no_new_gap", printed)
        self.assertIn("--feedback-gap", printed)

    def test_an_unknown_reason_still_names_itself(self):
        # A reason added later must not print as a blank line.
        details = _declined_curation_details(
            [{"candidate_id": "abc123", "reason": "some_future_reason"}]
        )

        self.assertIn("some_future_reason", details[1])
        self.assertIn("no remedy is recorded", details[1])

    def _reject_after_staging(self, candidate: str) -> None:
        """Drive a candidate to the state maintenance leaves when it cannot apply."""

        from agent_skill_draft import record_draft
        from agent_skill_maintenance import complete_verified_skill_maintenance

        bundle = (
            self.root / "project" / ".agents" / "shared" / "llm-skills" / "branch-cleanup"
        )
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        record_draft(
            self.root,
            project=self.root / "project",
            rules=ROOT,
            skill_id="branch_cleanup",
            signal="missing_rule",
            proposal=(
                "The skill does not say which branch survives when two cleanup "
                "runs claim the same name, so the run guessed. Add a decision "
                "rule naming the newest claim as canonical."
            ),
            occurrence_id="occ-1",
        )
        review_candidate(
            self.root,
            candidate,
            decision="stage_patch",
            gap_type="missing_import_policy",
            change_type="add_rule",
            promotion_target="branch_cleanup",
            min_occurrences=1,
        )
        complete_verified_skill_maintenance(
            self.root,
            project=self.root / "project",
            rules=ROOT,
            candidate_id=candidate,
            outcome="rejected",
            verification_kind="",
            target="",
            test_selector="",
        )

    def test_a_gap_the_reviewer_accepted_and_maintenance_never_applied_reopens(self):
        """Nobody decided this gap needed nothing, so nothing should block it.

        A completed record covers its gaps when a reviewer decided `no_change`,
        or when the fix was `applied`. A `rejected` record means the opposite:
        the review said `stage_patch` -- the gap should be fixed -- and
        maintenance did not apply it. Treating that as covered made an accepted
        gap unreachable forever, and told the next closeout that a review had
        already closed it.
        """

        candidate = candidate_id("branch_cleanup", "missing_rule")
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curate_observations(self.root, min_occurrences=1)
        self._reject_after_staging(candidate)
        self.assertEqual(
            "rejected",
            json.loads(
                (self.root / completed_path(candidate)).read_text(encoding="utf-8")
            )["status"],
        )

        record_observation(
            self.root,
            occurrence_id="occ-2",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual([candidate], curated["queued"])
        self.assertEqual([], curated["not_queued"])
        self.assertFalse((self.root / completed_path(candidate)).exists())

    def test_a_gap_the_reviewer_closed_still_blocks(self):
        # The reviewer decided this one needed nothing. That decision stands.
        candidate = candidate_id("branch_cleanup", "missing_rule")
        record_observation(
            self.root,
            occurrence_id="occ-1",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curate_observations(self.root, min_occurrences=1)
        review_candidate(
            self.root, candidate, decision="no_change", min_occurrences=1
        )

        record_observation(
            self.root,
            occurrence_id="occ-2",
            skill_id="branch_cleanup",
            signal="missing_rule",
            gap_type="missing_import_policy",
        )
        curated = curate_observations(self.root, min_occurrences=1)

        self.assertEqual([], curated["queued"])
        self.assertEqual(
            [{"candidate_id": candidate, "reason": "closed_review_no_new_gap"}],
            curated["not_queued"],
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
