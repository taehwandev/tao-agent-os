from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_request import classify_request


class WorkflowRequestContinuationTests(unittest.TestCase):
    def test_clarity_agrees_with_preparation_not_automatic_ambiguity(self) -> None:
        self.assertEqual("clear-scoped", classify_request("Fix scripts/workflow.py line 10")["clarity"])
        result = classify_request("해결해 그럼", continuation_scope="Known parser correction")
        self.assertEqual("context-dependent", result["clarity"])
        self.assertNotEqual("work", result["response_mode"])

    def test_auto_input_preserves_advice_in_json_and_rendered_output(self) -> None:
        argv = [sys.executable, str(ROOT / "scripts/workflow.py"), "route", "auto", "--advisory",
                "--continuation-scope", "Known parser correction and acceptance case"]
        payload = json.dumps({"prompt": "해결해 그럼"})
        result = subprocess.run([*argv, "--format", "json"], input=payload,
                                cwd=ROOT, capture_output=True, text=True, check=True)
        route = json.loads(result.stdout)
        self.assertEqual("resolve_context", route["intake_advice"]["response_mode"])
        self.assertEqual("context-dependent", route["intake_advice"]["clarity"])
        self.assertFalse(route["intake_advice"]["grill_me"])
        self.assertIsNone(route["request_classification"])
        self.assertTrue(route["advisory"])
        result = subprocess.run([*argv, "--hook-stdin"], input=payload, cwd=ROOT, capture_output=True,
                                text=True, check=True)
        self.assertIn("resolve_context", result.stdout)
        self.assertIn("Resolve the current request against prior scope", result.stdout)
        self.assertNotIn("Required next action: run a user-visible", result.stdout)

    def test_real_hook_without_history_defers_missing_scope_to_agent(self) -> None:
        argv = [sys.executable, str(ROOT / "scripts/workflow.py"), "route", "auto",
                "--advisory", "--hook-stdin", "--format", "json"]
        for prompt, expected in (("해결해 그럼", "resolve_context"),
                                 ("작업해줘", "resolve_context"),
                                 ("Use Grill-Me before work", "clarify_first"),
                                 ("what does this do?", "answer_first")):
            with self.subTest(prompt=prompt):
                process = subprocess.run(argv, input=json.dumps({"prompt": prompt}),
                                         cwd=ROOT, capture_output=True, text=True, check=True)
                route = json.loads(process.stdout)
                self.assertEqual(expected, route["intake_advice"]["response_mode"])
                self.assertIsNone(route["request_classification"])
                self.assertTrue(route["advisory"])

    def test_auto_explicit_request_wins_over_stale_payload(self) -> None:
        from argparse import Namespace
        from workflow import _resolve_auto_command

        args = Namespace(command="auto", request="Review the current diff", continuation_scope="",
                         _hook_payload_text=json.dumps({"prompt": "deploy the production app"}))
        _resolve_auto_command(args)
        self.assertEqual("review", args.command)
        self.assertEqual("prepare_intent", args._auto_intake_advice["response_mode"])

    def test_action_without_a_current_or_continuation_target_is_triaged(self) -> None:
        result = classify_request("작업해줘")

        self.assertEqual("clarify_first", result["response_mode"])
        self.assertEqual("triage", result["recommended_route"])
        self.assertFalse(result["continuation_scope_used"])

    def test_continuation_target_does_not_replace_an_intent_envelope(self) -> None:
        result = classify_request(
            "작업해줘",
            continuation_scope="최근 추가된 actionability 계층 정리",
        )

        self.assertEqual("resolve_context", result["response_mode"])
        self.assertEqual("triage", result["recommended_route"])
        self.assertFalse(result["continuation_scope_used"])
        self.assertFalse(result["grill_me"])

    def test_real_follow_ups_resolve_known_context_before_asking_again(self) -> None:
        from workflow_request import route_block_reason
        from workflow_intent_dual_run import route_intake_decision

        for request in ("해결해 그럼", "응 수정해", "검증해줘", "정리도해줘"):
            with self.subTest(request=request):
                result = classify_request(request, continuation_scope="Previously discussed target and acceptance case")
                self.assertEqual("resolve_context", result["response_mode"])
                self.assertFalse(result["question_drill"])
                self.assertEqual("triage", result["recommended_route"])
                self.assertIsNotNone(route_block_reason("task", result))
                # Resolving context is not permission, even for cleanup.
                _, failures = route_intake_decision(
                    "task", None, request_fingerprint="a" * 64,
                    runtime_session_id="session-current-01",
                )
                self.assertTrue(failures)

    def test_explicit_question_drill_is_not_suppressed_by_context(self) -> None:
        result = classify_request("Use Grill-Me before work", continuation_scope="Known target")
        self.assertTrue(result["grill_me"])
        self.assertEqual("clarify_first", result["response_mode"])

    def test_follow_up_cli_proceeds_only_with_current_resolved_envelope(self) -> None:
        from agent_route_state import request_fingerprint

        request = "해결해 그럼"
        scope = "Correct the known local parser result; verify the reported input"
        session = "session-current-01"
        envelope = {
            "schema_version": 1,
            "request_fingerprint": request_fingerprint({"request": request, "continuation_scope": scope}),
            "runtime_session_id": session, "mode": "work", "intent": "fix",
            "target_summary": "existing local parser", "requested_effects": ["local_write"],
            "ambiguity": "resolved",
        }
        argv = [sys.executable, str(ROOT / "scripts/workflow.py"), "classify", request,
                "--continuation-scope", scope, "--command", "small-change",
                "--runtime-session-id", session, "--format", "json"]
        for changes, allowed in ((None, False), ({}, True),
                                 ({"ambiguity": "blocking"}, False),
                                 ({"runtime_session_id": "session-stale-01"}, False),
                                 ({"request_fingerprint": "b" * 64}, False),
                                 ({"requested_effects": ["external_write"]}, False)):
            with self.subTest(changes=changes):
                command = argv if changes is None else [
                    *argv, "--intent-envelope", json.dumps({**envelope, **changes})]
                process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                result = json.loads(process.stdout)
                self.assertEqual(allowed, result["response_mode"] == "work")
                if allowed:
                    self.assertFalse(result["grill_me"])
                elif changes is not None:
                    self.assertTrue(result["intent_envelope"]["failures"])

    def test_question_does_not_become_work_from_continuation_scope(self) -> None:
        result = classify_request(
            "이제 어떻게 동작해?",
            continuation_scope="최근 추가된 actionability 계층 정리",
        )

        self.assertEqual("answer_first", result["response_mode"])
        self.assertFalse(result["continuation_scope_used"])

    def test_continuation_scope_cannot_authorize_risky_work(self) -> None:
        result = classify_request(
            "배포해줘",
            continuation_scope="이미 합의된 배포 대상",
        )

        self.assertNotEqual("work", result["response_mode"])
        self.assertFalse(result["continuation_scope_used"])

    def test_continuation_scope_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "500-character"):
            classify_request("작업해줘", continuation_scope="x" * 501)


if __name__ == "__main__":
    unittest.main()
