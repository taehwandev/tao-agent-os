"""Observation-time skill patch drafts carry the reasoning slugs cannot."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_skill_draft import (  # noqa: E402
    DRAFT_PRIVACY,
    MAX_DRAFTS,
    MAX_PROPOSAL_CHARS,
    MIN_PROPOSAL_CHARS,
    draft_binding,
    draft_path,
    normalize_proposal,
    proposal_sha256,
    read_draft,
    record_draft,
    valid_draft,
)
from agent_skill_learning import record_observation, curate_observations, review_candidate  # noqa: E402
from agent_skill_state import candidate_id  # noqa: E402

SKILL = "code_conventions"
SIGNAL = "missing_rule"
PROPOSAL = (
    "The skill does not say which import form wins when a module is reachable "
    "by both a package alias and a relative path, so the run guessed. Add a "
    "decision rule naming the package alias as canonical."
)


def _project_with_skill(root: Path, skill_id: str) -> Path:
    bundle = root / "project" / ".agents" / "shared" / "llm-skills" / skill_id.replace("_", "-")
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    return root / "project"


class NormalizeProposalTests(unittest.TestCase):
    def test_rejects_too_short_and_too_long(self):
        self.assertEqual(normalize_proposal("x" * (MIN_PROPOSAL_CHARS - 1)), "")
        self.assertEqual(normalize_proposal("x" * (MAX_PROPOSAL_CHARS + 1)), "")

    def test_rejects_binary_and_terminal_capture(self):
        self.assertEqual(normalize_proposal(PROPOSAL + "\x00"), "")
        self.assertEqual(normalize_proposal(PROPOSAL + "\x1b[31m"), "")

    def test_keeps_tabs_and_newlines_and_normalizes_line_endings(self):
        text = "a" * MIN_PROPOSAL_CHARS + "\r\n\tsecond line"
        self.assertEqual(normalize_proposal(text), "a" * MIN_PROPOSAL_CHARS + "\n\tsecond line")


class RecordDraftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "state"
        self.root.mkdir(parents=True)
        self.project = _project_with_skill(Path(self._tmp.name), SKILL)
        self.candidate = candidate_id(SKILL, SIGNAL)

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self, **overrides):
        kwargs = {
            "project": self.project,
            "rules": ROOT,
            "skill_id": SKILL,
            "signal": SIGNAL,
            "proposal": PROPOSAL,
            "occurrence_id": "run-abc-123",
        }
        kwargs.update(overrides)
        return record_draft(self.root, **kwargs)

    def test_records_a_valid_bound_draft(self):
        result = self._record()
        self.assertTrue(result["created"], result)
        self.assertEqual(result["candidate_id"], self.candidate)
        payload = read_draft(self.root, self.candidate)
        self.assertTrue(valid_draft(payload, self.candidate))
        self.assertEqual(payload["privacy"], DRAFT_PRIVACY)
        self.assertEqual(payload["proposal"], PROPOSAL)
        self.assertEqual(payload["proposal_sha256"], proposal_sha256(PROPOSAL))
        self.assertEqual(payload["revisions"], 1)

    def test_observation_record_is_not_touched_by_the_draft(self):
        """The content-free guarantee of lifecycle records must survive."""

        self._record()
        observation = record_observation(
            self.root, occurrence_id="run-abc-123", skill_id=SKILL, signal=SIGNAL
        )
        self.assertTrue(observation.get("created"), observation)
        stored = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.root / "skill-learning" / "observations").glob("*.json")
        ]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["privacy"], "safe_slugs_and_opaque_ids_only")
        self.assertNotIn("proposal", stored[0])
        self.assertNotIn("draft_id", stored[0])

    def test_identical_reproposal_is_idempotent(self):
        self._record()
        again = self._record()
        self.assertFalse(again.get("created"))
        self.assertTrue(again.get("idempotent"))
        self.assertEqual(read_draft(self.root, self.candidate)["revisions"], 1)

    def test_revision_bumps_count_and_merges_occurrences(self):
        self._record()
        revised = self._record(proposal=PROPOSAL + " Also name the test that proves it.",
                               occurrence_id="run-def-456")
        self.assertTrue(revised["created"], revised)
        self.assertTrue(revised["revised"])
        payload = read_draft(self.root, self.candidate)
        self.assertEqual(payload["revisions"], 2)
        self.assertEqual(len(payload["occurrence_keys"]), 2)

    def test_rejects_unknown_skill_signal_proposal_and_occurrence(self):
        self.assertEqual(self._record(skill_id="not_a_real_skill")["reason"],
                         "unknown_canonical_skill")
        self.assertEqual(self._record(signal="totally_made_up")["reason"],
                         "unknown_feedback_signal")
        self.assertEqual(self._record(proposal="too short")["reason"], "unusable_proposal")
        self.assertEqual(self._record(occurrence_id="")["reason"], "missing_occurrence")

    def test_draft_store_is_capped(self):
        drafts = self.root / "skill-learning" / "drafts"
        drafts.mkdir(parents=True)
        for index in range(MAX_DRAFTS):
            (drafts / f"{index:016x}.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self._record()["reason"], "draft_store_full")

    def test_revision_is_allowed_at_the_cap(self):
        self._record()
        drafts = self.root / "skill-learning" / "drafts"
        for index in range(MAX_DRAFTS):
            (drafts / f"{index:016x}.json").write_text("{}", encoding="utf-8")
        revised = self._record(proposal=PROPOSAL + " Add the missing verification step.")
        self.assertTrue(revised["created"], revised)


class DraftBindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "state"
        self.root.mkdir(parents=True)
        self.project = _project_with_skill(Path(self._tmp.name), SKILL)
        self.candidate = candidate_id(SKILL, SIGNAL)

    def tearDown(self):
        self._tmp.cleanup()

    def _reach_review_ready(self):
        for occurrence in ("run-1", "run-2"):
            record_observation(
                self.root, occurrence_id=occurrence, skill_id=SKILL, signal=SIGNAL
            )
        curate_observations(self.root)

    def test_binding_is_empty_without_a_draft(self):
        self.assertEqual(draft_binding(self.root, self.candidate), {})

    def test_binding_is_empty_for_a_tampered_draft(self):
        record_draft(
            self.root, project=self.project, rules=ROOT, skill_id=SKILL,
            signal=SIGNAL, proposal=PROPOSAL, occurrence_id="run-1",
        )
        path = self.root / draft_path(self.candidate)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["proposal"] = payload["proposal"] + " silently rewritten"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(draft_binding(self.root, self.candidate), {})

    def test_staged_record_binds_the_reviewed_proposal_digest(self):
        record_draft(
            self.root, project=self.project, rules=ROOT, skill_id=SKILL,
            signal=SIGNAL, proposal=PROPOSAL, occurrence_id="run-1",
        )
        self._reach_review_ready()
        result = review_candidate(
            self.root,
            candidate_id=self.candidate,
            decision="stage_patch",
            gap_type="missing_decision_rule",
            change_type="add_rule",
            promotion_target=SKILL,
        )
        self.assertTrue(result.get("updated"), result)
        staged = json.loads(
            (self.root / "skill-learning" / "staged" / f"{self.candidate}.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(staged["draft_sha256"], proposal_sha256(PROPOSAL))
        self.assertTrue(staged["draft_id"])

    def test_stage_patch_is_refused_without_a_draft(self):
        """Staging requires the reviewed proposal; the write policy is draft-first."""

        self._reach_review_ready()
        result = review_candidate(
            self.root,
            candidate_id=self.candidate,
            decision="stage_patch",
            gap_type="missing_decision_rule",
            change_type="add_rule",
            promotion_target=SKILL,
        )
        self.assertFalse(result.get("updated"))
        self.assertEqual(result.get("reason"), "skill_draft_required")
        self.assertFalse(
            (self.root / "skill-learning" / "staged" / f"{self.candidate}.json").exists()
        )


class RetrospectiveGateOrderingTests(unittest.TestCase):
    """`reusable_gap` must be recordable; the observation check belongs to finish.

    Requiring a stored observation when the gate is recorded deadlocked every
    reusable gap: the gate needed the observation, the observation writer needed
    the gate, and the transitional value had been removed.
    """

    def test_gate_recording_no_longer_requires_a_stored_observation(self):
        import inspect

        import agent_hook_gate_records as records

        source = inspect.getsource(records)
        self.assertNotIn("recorded_observation_failures(", source)
        self.assertNotIn("from agent_retrospective_observation import", source)

    def test_finish_enforces_the_observation_instead(self):
        import inspect

        import agent_skill_followup as followup

        source = inspect.getsource(followup.skill_followup_failures)
        self.assertIn("recorded_observation_failures(", source)
        self.assertIn("_retrospective_fields(preflight)", source)

    def test_retrospective_fields_are_read_from_the_gate_ledger(self):
        from agent_skill_followup import _retrospective_fields

        self.assertEqual(_retrospective_fields({}), {})
        self.assertEqual(_retrospective_fields({"route": "not a dict"}), {})
        preflight = {
            "route": {
                "gate_ledger": [
                    {"gate": "act", "fields": {"x": "y"}},
                    {"gate": "retrospective check", "fields": {"outcome": "reusable_gap"}},
                ]
            }
        }
        self.assertEqual(_retrospective_fields(preflight), {"outcome": "reusable_gap"})

    def test_a_reusable_gap_without_a_stored_observation_still_fails_at_finish(self):
        from agent_retrospective_observation import recorded_observation_failures

        with TemporaryDirectory() as tmp:
            failures = recorded_observation_failures(
                preflight={"agent_run_id": "run-xyz"},
                fields={
                    "outcome": "reusable_gap",
                    "observation": "recorded",
                    "skills_checked": "code_conventions",
                },
                state_root=Path(tmp),
            )
        self.assertEqual(len(failures), 1)
        self.assertIn("matching stored observation", failures[0])


class NonGitMaintenanceReachabilityTests(unittest.TestCase):
    """`applied` must be reachable in a runtime tree that is not a git checkout.

    The change check has a non-git fallback, but the maintenance caller used to
    omit the preflight and relative path it needs, so every `applied` in such a
    tree failed as `maintenance_target_not_changed` and the observe-to-applied
    loop could never close there.
    """

    def test_maintenance_forwards_preflight_to_the_change_check(self):
        import inspect

        from agent_skill_maintenance import complete_verified_skill_maintenance

        signature = inspect.signature(complete_verified_skill_maintenance)
        self.assertIn("preflight", signature.parameters)

        source = inspect.getsource(complete_verified_skill_maintenance)
        self.assertIn("verification_target_is_changed(", source)
        self.assertIn("preflight=preflight", source)
        self.assertIn("target_relative=target_relative", source)

    def test_hook_adapter_accepts_and_reads_the_evidence_path(self):
        import inspect

        from agent_skill_feedback import _preflight_payload, record_skill_maintenance

        self.assertIn("evidence_path", inspect.signature(record_skill_maintenance).parameters)
        self.assertIn(
            "preflight=_preflight_payload(evidence_path)",
            inspect.getsource(record_skill_maintenance),
        )
        self.assertIsNone(_preflight_payload(None))
        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "preflight.json"
            broken.write_text("not json", encoding="utf-8")
            self.assertIsNone(_preflight_payload(broken))
            good = Path(tmp) / "ok.json"
            good.write_text(json.dumps({"project": "/x"}), encoding="utf-8")
            self.assertEqual(_preflight_payload(good), {"project": "/x"})


class LocalSkillsValidationScopeTests(unittest.TestCase):
    """The runtime document contract must not claim ownership of personal skills."""

    def test_local_is_excluded_from_markdown_validation(self):
        from workflow_validate import MARKDOWN_VALIDATE_IGNORED_DIRS, markdown_files_to_validate

        self.assertIn("local", MARKDOWN_VALIDATE_IGNORED_DIRS)
        files = markdown_files_to_validate(ROOT)
        under_local = [f for f in files if "local" in f.relative_to(ROOT).parts]
        self.assertEqual(under_local, [])


if __name__ == "__main__":
    unittest.main()
