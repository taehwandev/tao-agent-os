"""The dual run must diagnose, never arbitrate.

If the legacy classifier can override the envelope when the two disagree, the
natural-language path stays authoritative and nothing gets deleted. These tests
pin that the envelope decides and the comparison stays content-free.
"""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_intent_dual_run import (
    AUTHORITY_ENVELOPE,
    AUTHORITY_LEGACY,
    dual_run_decision,
)


def envelope(**overrides):
    base = {
        "schema_version": 1,
        "request_fingerprint": "a1b2c3d4e5f60718",
        "runtime_session_id": "runtime-session-01",
        "mode": "work",
        "intent": "edit",
        "target_summary": "the commit parser",
        "requested_effects": ["local_write"],
        "ambiguity": "resolved",
    }
    base.update(overrides)
    return base


def approval(bound, *, command="release", effect="external_write"):
    return {
        "request_fingerprint": bound["request_fingerprint"],
        "target_summary": bound["target_summary"],
        "effect": effect,
        "command": command,
    }


def classify(request, *, command="task", envelope_json=None, runtime_session_id=None):
    argv = [sys.executable, "scripts/workflow.py", "classify", request,
            "--format", "json", "--command", command]
    if envelope_json is not None:
        argv += ["--intent-envelope", envelope_json]
    if runtime_session_id is not None:
        argv += ["--runtime-session-id", runtime_session_id]
    result = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    return json.loads(result.stdout)


class DualRunAuthorityTests(unittest.TestCase):
    def test_the_envelope_decides_even_when_the_classifier_disagrees(self) -> None:
        decision = dual_run_decision(
            "task", envelope(), {"response_mode": "clarify_first"},
            request_fingerprint=envelope()["request_fingerprint"],
            runtime_session_id=envelope()["runtime_session_id"],
        )

        self.assertEqual(AUTHORITY_ENVELOPE, decision["authority"])
        self.assertEqual([], decision["failures"])

    def test_a_disagreement_is_recorded_rather_than_resolved(self) -> None:
        decision = dual_run_decision(
            "task", envelope(), {"response_mode": "answer_first"},
            request_fingerprint=envelope()["request_fingerprint"],
            runtime_session_id=envelope()["runtime_session_id"],
        )

        self.assertEqual("disagree", decision["comparison"]["status"])
        self.assertEqual(AUTHORITY_ENVELOPE, decision["authority"])
        self.assertEqual([], decision["failures"])

    def test_only_a_missing_envelope_falls_back_to_the_classifier(self) -> None:
        """An unreadable envelope is not an absent one.

        Treating both as absent let a broken adapter reach the very path the
        envelope replaces.
        """

        absent = dual_run_decision("task", None, {"response_mode": "work"})
        unreadable = dual_run_decision("task", {}, {"response_mode": "work"})

        self.assertEqual(AUTHORITY_LEGACY, absent["authority"])
        self.assertEqual(AUTHORITY_ENVELOPE, unreadable["authority"])
        self.assertTrue(unreadable["failures"])

    def test_the_comparison_carries_no_request_or_target_text(self) -> None:
        decision = dual_run_decision(
            "task",
            envelope(target_summary="a secret internal codename"),
            {"response_mode": "work", "reason": "raw classifier prose"},
            request_fingerprint=envelope()["request_fingerprint"],
            runtime_session_id=envelope()["runtime_session_id"],
        )

        serialized = json.dumps(decision["comparison"])
        self.assertNotIn("secret internal codename", serialized)
        self.assertNotIn("raw classifier prose", serialized)

    def test_the_route_floor_still_applies_under_the_dual_run(self) -> None:
        decision = dual_run_decision(
            "release", envelope(requested_effects=["read"], intent="release"), None,
            request_fingerprint=envelope()["request_fingerprint"],
            runtime_session_id=envelope()["runtime_session_id"],
        )

        self.assertEqual("external_write", decision["effective_effect"])
        self.assertTrue(decision["failures"])


class DualRunCliTests(unittest.TestCase):
    def test_the_cli_omits_the_envelope_block_when_none_is_given(self) -> None:
        self.assertNotIn("intent_envelope", classify("Fix the commit parser"))

    def test_the_cli_reports_the_envelope_decision_when_one_is_given(self) -> None:
        result = classify(
            "Fix the commit parser", envelope_json=json.dumps(envelope()),
            runtime_session_id=envelope()["runtime_session_id"],
        )

        block = result["intent_envelope"]
        self.assertEqual(AUTHORITY_ENVELOPE, block["authority"])
        self.assertEqual("local_write", block["effective_effect"])

    def test_an_unreadable_cli_value_refuses_instead_of_falling_back(self) -> None:
        block = classify(
            "Fix the commit parser", envelope_json="not json",
            runtime_session_id=envelope()["runtime_session_id"],
        )[
            "intent_envelope"
        ]

        self.assertEqual(AUTHORITY_ENVELOPE, block["authority"])
        self.assertFalse(block["schema_valid"])
        self.assertTrue(block["failures"])

    def test_the_same_envelope_decides_alike_whatever_the_request_says(self) -> None:
        """The request text is no longer what the decision rests on."""

        payload = json.dumps(envelope())
        english = classify(
            "Fix the commit parser", envelope_json=payload,
            runtime_session_id=envelope()["runtime_session_id"],
        )
        korean = classify(
            "배포해줘", envelope_json=payload,
            runtime_session_id=envelope()["runtime_session_id"],
        )

        self.assertEqual(
            english["intent_envelope"]["effective_effect"],
            korean["intent_envelope"]["effective_effect"],
        )
        self.assertEqual(
            english["intent_envelope"]["failures"],
            korean["intent_envelope"]["failures"],
        )


class EnvelopeWiringTests(unittest.TestCase):
    """The checks must run on the path callers actually take.

    Every defect these pin was a check that existed and was never reached:
    the binding arguments were added but not threaded, `start` never learned
    the flag, and inline JSON was discarded before it could be parsed.
    """

    def _route(
        self,
        command,
        envelope,
        request="Fix the commit parser",
        approval_record=None,
        approval_option="--approval-record",
        continuation_scope="",
    ):
        argv = [
            sys.executable, "scripts/workflow.py", "route", command,
            "--format", "json", "--request", request,
            "--intent-envelope", json.dumps(envelope),
            "--runtime-session-id", envelope.get("runtime_session_id", ""),
        ]
        if continuation_scope:
            argv.extend(["--continuation-scope", continuation_scope])
        if approval_record is not None:
            argv.extend([approval_option, json.dumps(approval_record)])
        return subprocess.run(
            argv,
            capture_output=True, text=True, cwd=ROOT,
        )

    def _bound(self, request="Fix the commit parser", **overrides):
        from agent_route_state import request_fingerprint

        return envelope(request_fingerprint=request_fingerprint({"request": request}), **overrides)

    def test_inline_json_is_parsed_rather_than_probed_as_a_path(self) -> None:
        """A JSON string is longer than the OS name limit, so probing the
        filesystem first raised and discarded every real envelope."""

        result = self._route("bugfix", self._bound())

        self.assertEqual(0, result.returncode, result.stderr)

    def test_the_route_refuses_an_envelope_bound_to_another_request(self) -> None:
        result = self._route("bugfix", self._bound(request="a different request"))

        self.assertEqual(2, result.returncode)
        self.assertIn("different request", result.stderr)

    def test_the_route_refuses_an_envelope_bound_to_another_runtime_session(self) -> None:
        bound = self._bound()
        result = subprocess.run(
            [sys.executable, "scripts/workflow.py", "route", "bugfix",
             "--format", "json", "--request", "Fix the commit parser",
             "--intent-envelope", json.dumps(bound),
             "--runtime-session-id", "different-runtime-session"],
            capture_output=True, text=True, cwd=ROOT,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("different runtime session", result.stderr)

    def test_the_route_refuses_an_envelope_without_the_current_runtime_session(self) -> None:
        bound = self._bound()
        result = subprocess.run(
            [sys.executable, "scripts/workflow.py", "route", "bugfix",
             "--format", "json", "--request", "Fix the commit parser",
             "--intent-envelope", json.dumps(bound)],
            capture_output=True, text=True, cwd=ROOT,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("current runtime session id", result.stderr)

    def test_the_route_still_enforces_the_floor_and_the_ambiguity_state(self) -> None:
        for command, overrides in (
            ("release", {"intent": "release"}),
            ("bugfix", {"ambiguity": "blocking"}),
        ):
            with self.subTest(command=command, overrides=sorted(overrides)):
                self.assertEqual(
                    2, self._route(command, self._bound(**overrides)).returncode
                )

    def test_release_route_accepts_a_separate_bound_user_approval(self) -> None:
        request = "Publish the next release"
        bound = self._bound(
            request=request,
            intent="release",
            requested_effects=["external_write"],
            target_summary="the next repository release",
        )

        result = self._route(
            "release",
            bound,
            request=request,
            approval_record=approval(bound),
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_release_route_accepts_user_approval_compatibility_alias(self) -> None:
        request = "Publish the next release"
        bound = self._bound(
            request=request,
            intent="release",
            requested_effects=["external_write"],
            target_summary="the next repository release",
        )
        result = self._route(
            "release",
            bound,
            request=request,
            approval_record=approval(bound),
            approval_option="--user-approval",
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_start_and_preflight_accept_the_envelope(self) -> None:
        for script, action in (("scripts/agent-hook.py", "start"), ("scripts/agent-preflight.py", None)):
            with self.subTest(script=script):
                argv = [sys.executable, script] + ([action] if action else []) + ["--help"]
                helptext = subprocess.run(
                    argv, capture_output=True, text=True, cwd=ROOT
                ).stdout
                self.assertIn("--intent-envelope", helptext)
                self.assertIn("--approval-record", helptext)
                self.assertIn("--user-approval", helptext)
                self.assertIn("--runtime-session-id", helptext)

    def test_preflight_in_process_routing_consumes_the_bound_envelope(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_preflight_intent_test", ROOT / "scripts" / "agent-preflight.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        bound = self._bound()
        args = module.build_parser(ROOT).parse_args(
            [
                "--command", "bugfix",
                "--request", "Fix the commit parser",
                "--project", str(ROOT),
                "--intent-envelope", json.dumps(bound),
                "--runtime-session-id", bound["runtime_session_id"],
            ]
        )

        route, error, returncode = module.route_payload(args, {})

        self.assertEqual(0, returncode, error)
        self.assertIsNotNone(route)
        self.assertEqual("envelope", route["request_classification"]["intent_envelope"]["authority"])

    def test_preflight_in_process_routing_consumes_bound_user_approval(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_preflight_approval_test", ROOT / "scripts" / "agent-preflight.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        request = "Publish the next release"
        bound = self._bound(
            request=request,
            intent="release",
            requested_effects=["external_write"],
            target_summary="the next repository release",
        )
        args = module.build_parser(ROOT).parse_args(
            [
                "--command", "release",
                "--request", request,
                "--project", str(ROOT),
                "--intent-envelope", json.dumps(bound),
                "--approval-record", json.dumps(approval(bound)),
                "--runtime-session-id", bound["runtime_session_id"],
            ]
        )

        route, error, returncode = module.route_payload(args, {})

        self.assertEqual(0, returncode, error)
        self.assertIsNotNone(route)
        self.assertEqual(
            "external_write",
            route["request_classification"]["intent_envelope"]["effective_effect"],
        )

    def test_start_threads_the_envelope_and_runtime_session_to_preflight(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_hook_intent_test", ROOT / "scripts" / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        bound = self._bound()
        approval_record = approval(bound)
        args = module.build_parser().parse_args(
            [
                "start",
                "--project", str(ROOT),
                "--rules", str(ROOT),
                "--command", "bugfix",
                "--request", "Fix the commit parser",
                "--intent-envelope", json.dumps(bound),
                "--approval-record", json.dumps(approval_record),
                "--runtime-session-id", bound["runtime_session_id"],
            ]
        )

        command = module._preflight_arguments(args)

        self.assertEqual(json.dumps(bound), command[command.index("--intent-envelope") + 1])
        self.assertEqual(
            json.dumps(approval_record),
            command[command.index("--approval-record") + 1],
        )
        self.assertEqual(
            bound["runtime_session_id"],
            command[command.index("--runtime-session-id") + 1],
        )

    def test_start_normalizes_user_approval_alias_to_canonical_preflight_option(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_hook_approval_alias_test", ROOT / "scripts" / "agent-hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        bound = self._bound()
        approval_record = approval(bound)
        args = module.build_parser().parse_args(
            [
                "start",
                "--project",
                str(ROOT),
                "--rules",
                str(ROOT),
                "--command",
                "bugfix",
                "--request",
                "Fix the commit parser",
                "--intent-envelope",
                json.dumps(bound),
                "--user-approval",
                json.dumps(approval_record),
                "--runtime-session-id",
                bound["runtime_session_id"],
            ]
        )

        command = module._preflight_arguments(args)

        self.assertNotIn("--user-approval", command)
        self.assertEqual(
            json.dumps(approval_record),
            command[command.index("--approval-record") + 1],
        )


    def _scoped(self, request, continuation_scope, **overrides):
        from agent_route_state import request_fingerprint

        return envelope(
            request_fingerprint=request_fingerprint(
                {"request": request, "continuation_scope": continuation_scope}
            ),
            **overrides,
        )

    def test_the_route_refuses_an_envelope_bound_to_another_continuation_scope(
        self,
    ) -> None:
        """A terse follow-up carries its meaning in the scope, not the request.

        The binding hashed the request text alone, so an envelope minted for
        "y" about one target stayed valid for "y" about the next one -- the
        replay the binding exists to refuse, at the one place the request text
        cannot distinguish two tasks.
        """

        result = self._route(
            "bugfix",
            self._scoped("y", "publish the approved release"),
            request="y",
            continuation_scope="delete the production database",
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("different request", result.stderr)

    def test_the_route_accepts_an_envelope_bound_to_its_own_continuation_scope(
        self,
    ) -> None:
        """The tightened binding must still admit the matching scope."""

        result = self._route(
            "bugfix",
            self._scoped("y", "publish the approved release"),
            request="y",
            continuation_scope="publish the approved release",
        )

        self.assertEqual(0, result.returncode, result.stderr)


class NoEnvelopeWorkRouteTests(unittest.TestCase):
    def _route(self, command, request):
        return subprocess.run(
            [sys.executable, "scripts/workflow.py", "route", command,
             "--format", "json", "--request", request],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_text_only_release_phrases_cannot_open_the_release_route(self) -> None:
        for request in (
            "커밋하고 푸시해줘",
            "commit and push",
            "v1.2.3 태그를 배포해줘",
        ):
            with self.subTest(request=request):
                result = self._route("release", request)
                self.assertEqual(2, result.returncode)
                self.assertIn("intent envelope", result.stderr)

    def test_even_precise_local_work_needs_an_envelope(self) -> None:
        result = self._route("bugfix", "Fix scripts/workflow.py line 10")

        self.assertEqual(2, result.returncode)
        self.assertIn("intent envelope", result.stderr)

    def test_dispatch_cannot_bypass_the_route_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/workflow.py", "dispatch", "release",
             "--request", "commit and push", "--project", str(ROOT)],
            capture_output=True, text=True, cwd=ROOT,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("intent envelope", result.stderr)

if __name__ == "__main__":
    unittest.main()
