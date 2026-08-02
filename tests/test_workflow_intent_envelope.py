"""Contract tests for the runtime intent envelope.

These assert invariants over intent, target and risk rather than over
sentences. A sentence test pins one phrasing; an invariant test pins what the
system is allowed to do, which is the thing that must not regress.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_catalog import COMMANDS
from workflow_effect_policy import (
    APPROVAL_REQUIRED_FROM,
    ROUTE_MINIMUM_EFFECT,
    effect_decision,
    effective_effect,
    route_minimum_effect,
)
from workflow_intent_envelope import EFFECT_RANK, validate_envelope


FINGERPRINT = "a1b2c3d4e5f60718"
SESSION = "runtime-session-01"


def envelope(**overrides):
    base = {
        "schema_version": 1,
        "request_fingerprint": FINGERPRINT,
        "runtime_session_id": SESSION,
        "mode": "work",
        "intent": "edit",
        "target_summary": "the commit parser in the request classifier",
        "requested_effects": ["local_write"],
        "ambiguity": "resolved",
    }
    base.update(overrides)
    return base


def approval(**overrides):
    base = {
        "request_fingerprint": FINGERPRINT,
        "target_summary": envelope()["target_summary"],
        "effect": "external_write",
        "command": "release",
    }
    base.update(overrides)
    return base


class EnvelopeSchemaTests(unittest.TestCase):
    def test_a_well_formed_envelope_is_accepted(self) -> None:
        self.assertEqual([], validate_envelope(envelope()))

    def test_every_required_field_is_required(self) -> None:
        for field in (
            "schema_version", "request_fingerprint", "runtime_session_id",
            "mode", "intent", "target_summary", "requested_effects", "ambiguity",
        ):
            with self.subTest(field=field):
                incomplete = envelope()
                del incomplete[field]
                self.assertTrue(validate_envelope(incomplete))

    def test_the_target_summary_stays_bounded_and_single_line(self) -> None:
        self.assertTrue(validate_envelope(envelope(target_summary="x" * 201)))
        self.assertTrue(validate_envelope(envelope(target_summary="two\nlines")))
        self.assertTrue(validate_envelope(envelope(target_summary="  ")))
        self.assertTrue(validate_envelope(envelope(target_summary=12345678)))

    def test_unknown_effects_and_unknown_fields_are_rejected(self) -> None:
        self.assertTrue(validate_envelope(envelope(requested_effects=["sudo"])))
        self.assertTrue(validate_envelope(envelope(prompt="raw user text")))
        self.assertTrue(validate_envelope(envelope(approval_ref=12345678)))

    def test_an_envelope_cannot_request_what_it_prohibits(self) -> None:
        contradictory = envelope(
            requested_effects=["external_write"], prohibited_effects=["external_write"]
        )

        self.assertTrue(validate_envelope(contradictory))


class EffectUnionTests(unittest.TestCase):
    def test_a_runtime_claim_can_raise_the_effect(self) -> None:
        self.assertEqual(
            "destructive",
            effective_effect("task", envelope(requested_effects=["destructive"])),
        )

    def test_a_runtime_claim_can_never_lower_the_route_floor(self) -> None:
        """The self-assertion hole, rebuilt in JSON, is what this forbids."""

        claimed_read = envelope(requested_effects=["read"], intent="release")

        self.assertEqual("external_write", effective_effect("release", claimed_read))

    def test_a_runtime_claim_can_never_lower_the_tool_effect(self) -> None:
        self.assertEqual(
            "git_write",
            effective_effect("task", envelope(requested_effects=["read"]),
                             tool_effect="git_write"),
        )

    def test_an_undeclared_route_floors_at_the_most_dangerous_effect(self) -> None:
        self.assertEqual("external_write", route_minimum_effect("no-such-route"))

    def test_every_shipped_route_declares_its_floor(self) -> None:
        for command in COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, ROUTE_MINIMUM_EFFECT)


class EffectDecisionTests(unittest.TestCase):
    def test_a_read_only_request_may_not_reach_a_writing_tool(self) -> None:
        failures = effect_decision(
            "review",
            envelope(mode="answer", requested_effects=["read"],
                     prohibited_effects=["local_write"]),
            tool_effect="local_write",
        )

        self.assertTrue(failures)

    def test_a_release_route_claiming_no_external_effect_is_refused(self) -> None:
        failures = effect_decision(
            "release", envelope(requested_effects=["read"], intent="release")
        )

        self.assertTrue(failures)

    def test_the_same_release_proceeds_with_a_bound_approval(self) -> None:
        failures = effect_decision(
            "release",
            envelope(requested_effects=["external_write"], intent="release"),
            approval=approval(),
        )

        self.assertEqual([], failures)

    def test_an_approval_for_another_target_is_not_reusable(self) -> None:
        for mismatch in (
            {"target_summary": "a different deployment"},
            {"request_fingerprint": "0000000000000000"},
            {"command": "ship"},
            {"effect": "git_write"},
        ):
            with self.subTest(mismatch=sorted(mismatch)):
                failures = effect_decision(
                    "release",
                    envelope(requested_effects=["external_write"], intent="release"),
                    approval=approval(**mismatch),
                )
                self.assertTrue(failures)

    def test_an_envelope_cannot_approve_itself(self) -> None:
        failures = effect_decision(
            "release",
            envelope(
                requested_effects=["external_write"],
                intent="release",
                approval_ref="self-asserted-approval",
            ),
        )

        self.assertTrue(failures)

    def test_the_policy_refuses_an_envelope_it_could_not_validate(self) -> None:
        """Every check below the schema is a claim the envelope makes about
        itself, so acting on an unvalidated one rebuilds the hole this contract
        closes: omitting `ambiguity` used to skip the blocking check silently.
        """

        malformed = [
            {key: value for key, value in envelope().items() if key != "ambiguity"},
            {key: value for key, value in envelope().items() if key != "mode"},
            {key: value for key, value in envelope().items() if key != "requested_effects"},
            envelope(ambiguity="Blocking"),
            envelope(requested_effects=["sudo"]),
            {},
        ]
        for candidate in malformed:
            with self.subTest(candidate=sorted(candidate)):
                self.assertTrue(validate_envelope(candidate))
                self.assertTrue(effect_decision("task", candidate))

    def test_an_approval_must_name_the_route_it_was_granted_for(self) -> None:
        """Defaulting a missing route to the current one made an unbound
        approval look bound, so one granted for `release` worked on `ship`."""

        unbound = approval()
        del unbound["command"]

        for command in ("release", "ship"):
            with self.subTest(command=command):
                failures = effect_decision(
                    command,
                    envelope(requested_effects=["external_write"], intent="release"),
                    approval=unbound,
                )
                self.assertTrue(failures)

    def test_a_blocking_ambiguity_stops_work_at_any_effect(self) -> None:
        self.assertTrue(
            effect_decision("task", envelope(ambiguity="blocking"))
        )

    def test_the_target_wording_never_grants_an_effect(self) -> None:
        """"commit parser" is a target name, not commit authority."""

        named_commit = envelope(target_summary="the commit parser", intent="edit")

        self.assertEqual("local_write", effective_effect("task", named_commit))
        self.assertEqual([], effect_decision("task", named_commit))

    def test_one_envelope_decides_the_same_way_whatever_language_wrote_it(self) -> None:
        korean = envelope(target_summary="요청 분류기의 커밋 파서")
        english = envelope(target_summary="the commit parser in the request classifier")

        self.assertEqual(
            effective_effect("task", korean), effective_effect("task", english)
        )
        self.assertEqual(
            effect_decision("task", korean), effect_decision("task", english)
        )

    def test_approval_is_required_from_the_declared_effect_upward(self) -> None:
        for command, needs_approval in (
            ("review", False), ("task", False), ("commit", True), ("release", True),
        ):
            with self.subTest(command=command):
                effect = route_minimum_effect(command)
                required = EFFECT_RANK[effect] >= EFFECT_RANK[APPROVAL_REQUIRED_FROM]
                self.assertEqual(needs_approval, required)
                failures = effect_decision(command, envelope(requested_effects=[effect]))
                self.assertEqual(needs_approval, bool(failures))


if __name__ == "__main__":
    unittest.main()
