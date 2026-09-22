"""What `start` accepts from a runtime, and what it says when it refuses.

Each refusal here ends a `start` call, so a message that names the wrong flag
costs the caller a whole call -- and four of them in a row cost four. Two
observed failures are pinned below: `--approved-effect git_write` on a route
whose floor is `local_write`, refused as "unnecessary" when the flag was in
fact the one thing present; and an `--intent` the caller spelled as a phrase,
refused by a message that never said which characters a slug admits.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from argparse import ArgumentParser, Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_compact_authority_test", "agent-hook.py")

from workflow_effect_policy import effect_decision  # noqa: E402
from workflow_intent_envelope import (  # noqa: E402
    normalize_intent_slug,
    validate_envelope,
)


SESSION = {"runtime": "codex", "session_id": "compact-start-session"}


class _Refused(Exception):
    """What ``parser.error`` does to the process, without ending it."""


class CompactStartAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        session = patch.object(agent_hook, "runtime_session", return_value=SESSION)
        session.start()
        self.addCleanup(session.stop)
        self.parser = ArgumentParser(prog="agent-hook.py")

    def _materialize(self, **overrides) -> Namespace:
        args = Namespace(
            command="bugfix",
            request="the current request",
            continuation_scope="",
            request_classified=False,
            classification_evidence="",
            intent="fix_start_failures",
            target_summary="scripts/agent-hook.py compact start authority",
            requested_effect="",
            approved_effect="",
            prohibited_effect=[],
            intent_envelope="",
            approval_record="",
            runtime_session_id="",
        )
        args.__dict__.update(overrides)
        agent_hook._materialize_compact_start_authority(self.parser, args)
        return args

    def _envelope_and_approval(self, **overrides) -> tuple[dict, dict]:
        args = self._materialize(**overrides)
        return (
            json.loads(args.intent_envelope),
            json.loads(args.approval_record) if args.approval_record else {},
        )

    def _refusal(self, **overrides) -> str:
        def refuse(message: str) -> None:
            raise _Refused(message)

        with patch.object(self.parser, "error", side_effect=refuse):
            with self.assertRaises(_Refused) as refused:
                self._materialize(**overrides)
        return str(refused.exception)

    def test_an_approval_above_the_route_floor_also_declares_that_effect(self) -> None:
        """The observed refusal: `agent-hook.py: error: --approved-effect is
        unnecessary below git_write`, on a `refactor` start carrying
        `--approved-effect git_write` and no `--requested-effect`."""

        envelope, approval = self._envelope_and_approval(
            command="refactor", approved_effect="git_write"
        )

        self.assertEqual(["git_write"], envelope["requested_effects"])
        self.assertEqual("git_write", approval["effect"])
        self.assertEqual([], validate_envelope(envelope))
        self.assertEqual(
            [],
            effect_decision(
                "refactor",
                envelope,
                approval=approval,
                request_fingerprint=envelope["request_fingerprint"],
                runtime_session_id=envelope["runtime_session_id"],
            ),
        )

    def test_nothing_is_approved_that_the_envelope_did_not_request(self) -> None:
        envelope, approval = self._envelope_and_approval(
            command="refactor",
            requested_effect="git_write",
            approved_effect="git_write",
        )

        self.assertEqual(envelope["requested_effects"], [approval["effect"]])

    def test_explicit_request_is_not_widened_by_higher_approval(self) -> None:
        envelope, approval = self._envelope_and_approval(
            requested_effect="git_write", approved_effect="external_write",
        )
        self.assertEqual(["git_write"], envelope["requested_effects"])
        self.assertEqual("external_write", approval["effect"])

    def test_read_route_and_prohibited_effect_still_refuse_writes(self) -> None:
        for overrides in (
            {"command": "analysis"},
            {"prohibited_effect": ["git_write"]},
        ):
            with self.subTest(overrides=overrides):
                args = self._materialize(approved_effect="git_write", **overrides)
                self.assertTrue(effect_decision(
                    args.command, json.loads(args.intent_envelope),
                    approval=json.loads(args.approval_record),
                ))

    def test_an_approval_below_the_threshold_says_what_needs_one(self) -> None:
        message = self._refusal(command="refactor", approved_effect="local_write")

        self.assertIn("--approved-effect local_write is unnecessary", message)
        self.assertIn("required only from `git_write` up", message)

    def test_missing_or_insufficient_approval_is_rejected(self) -> None:
        self.assertIn("--approved-effect", self._refusal(command="commit"))
        self.assertIn("below", self._refusal(
            requested_effect="external_write", approved_effect="git_write",
        ))

    def test_pr_alias_uses_one_commit_lifecycle_with_external_authority(self) -> None:
        """A PR follow-up is publication, not a second unknown workflow route."""

        args = self._materialize(command="pr", approved_effect="external_write")
        envelope = json.loads(args.intent_envelope)
        approval = json.loads(args.approval_record)

        self.assertEqual("commit", args.command)
        self.assertEqual(["external_write"], envelope["requested_effects"])
        self.assertEqual("external_write", approval["effect"])
        self.assertEqual("commit", approval["command"])

    def test_pr_alias_refuses_git_only_authority_before_normalizing(self) -> None:
        message = self._refusal(command="pr", approved_effect="git_write")

        self.assertIn("external_write", message)
        self.assertIn("below", message)

    def test_compatibility_pr_alias_keeps_the_external_effect_floor(self) -> None:
        compact = self._materialize(command="pr", approved_effect="external_write")
        envelope = compact.intent_envelope
        approval = json.loads(compact.approval_record)
        approval["command"] = "pr"

        args = self._materialize(
            command="pr",
            intent="",
            target_summary="",
            approved_effect="",
            intent_envelope=envelope,
            approval_record=json.dumps(approval),
        )

        self.assertEqual("commit", args.command)
        self.assertEqual("commit", json.loads(args.approval_record)["command"])

    def test_compatibility_pr_alias_rejects_a_git_only_envelope(self) -> None:
        compact = self._materialize(command="commit", approved_effect="git_write")

        message = self._refusal(
            command="pr",
            intent="",
            target_summary="",
            approved_effect="",
            intent_envelope=compact.intent_envelope,
            approval_record=compact.approval_record,
        )

        self.assertIn("external_write", message)

    def test_foreign_session_is_rejected(self) -> None:
        self.assertIn("does not match", self._refusal(
            runtime_session_id="another-runtime-session",
        ))

    def test_small_change_names_the_routes_that_take_the_git_write(self) -> None:
        envelope, approval = self._envelope_and_approval(
            command="small-change", approved_effect="git_write"
        )

        failures = effect_decision("small-change", envelope, approval=approval)

        self.assertEqual(1, len(failures))
        self.assertIn("small-change permits only local writes", failures[0])
        self.assertIn("`commit`", failures[0])

    def test_a_hyphenated_intent_is_the_same_slug_as_an_underscored_one(self) -> None:
        envelope, _ = self._envelope_and_approval(intent="fix-start-failures")

        self.assertEqual("fix_start_failures", envelope["intent"])
        self.assertEqual([], validate_envelope(envelope))

    def test_an_intent_phrase_is_refused_with_the_pattern_it_failed(self) -> None:
        """The observed refusal said only "must be a safe lowercase slug"."""

        message = self._refusal(intent="Continue authorized module separation")

        self.assertIn("^[a-z][a-z0-9_-]{1,40}$", message)
        self.assertIn("fix_start_failures", message)
        self.assertIn("never the request text", message)

    def test_every_input_problem_is_reported_by_one_refusal(self) -> None:
        """Answering them one at a time is what made a single task spend four
        `start` calls in forty-five seconds."""

        message = self._refusal(
            command="refactor",
            intent="Continue authorized module separation",
            approved_effect="local_write",
        )

        self.assertIn("^[a-z][a-z0-9_-]{1,40}$", message)
        self.assertIn("--approved-effect local_write is unnecessary", message)

    def test_hand_built_envelope_keeps_canonical_contract_without_mutation(self) -> None:
        envelope, _ = self._envelope_and_approval()
        envelope["intent"] = "fix-start-failures"

        self.assertTrue(validate_envelope(envelope))
        self.assertEqual("fix-start-failures", envelope["intent"])
        self.assertEqual("fix_start_failures", normalize_intent_slug(envelope["intent"]))


if __name__ == "__main__":
    unittest.main()
