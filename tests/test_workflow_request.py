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
    def test_advisory_does_not_require_a_lifecycle_for_read_only_answers(self) -> None:
        for prompt in ("함수 설명해줘", "What does the function do?",
                       "Explain the function and fix the bug."):
            for output_format in ("json", "markdown"):
                with self.subTest(prompt=prompt, format=output_format):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "scripts/workflow.py"), "route", "auto",
                         "--advisory", "--hook-stdin", "--format", output_format],
                        input=json.dumps({"prompt": prompt}), cwd=ROOT,
                        capture_output=True, text=True, check=True,
                    )
                    self.assertNotIn("before editing, reviewing, or reporting completion", result.stdout)
                    self.assertIn("Read-only answers need no lifecycle", result.stdout)
                    self.assertIn("For work requiring a tracked lifecycle", result.stdout)
                    self.assertIn("satisfies no downstream gate", result.stdout)
                    if output_format == "json":
                        route = json.loads(result.stdout)
                        self.assertIsNone(route["request_classification"])
                        self.assertEqual(["common/skills/agent-operating-skill/SKILL.md"],
                                         route["required_docs"])

    def test_provisional_effort_reaches_actual_cli_consumers(self) -> None:
        for prompt, effort in (("함수 설명해줘", "quick"),
                               ("Explain the function and fix the bug.", "standard")):
            for command in (["classify", prompt], ["route", "auto", "--advisory", "--hook-stdin"]):
                for output_format in ("json", "markdown"):
                    with self.subTest(prompt=prompt, command=command, format=output_format):
                        result = subprocess.run(
                            [sys.executable, str(ROOT / "scripts/workflow.py"),
                             *command, "--format", output_format],
                            input=json.dumps({"prompt": prompt}), cwd=ROOT,
                            capture_output=True, text=True, check=True,
                        )
                        self.assertIn(f"Effort {effort} is current-intake-only", result.stdout)
                        self.assertIn("Reassess before substantive analysis or execution", result.stdout)
                        if output_format == "json" and command[0] == "route":
                            route = json.loads(result.stdout)
                            self.assertIsNone(route["request_classification"])
                            self.assertEqual(["common/skills/agent-operating-skill/SKILL.md"],
                                             route["required_docs"])

    def test_explanation_intake_effort_is_not_intent_certainty(self) -> None:
        for request in ("함수 설명해줘", "Explain input and output.",
                        "Please explain the function."):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("resolve_context", result["response_mode"])
                self.assertEqual("quick", result["effort"])
                self.assertEqual("fast", result["model_tier"])
                self.assertFalse(result["grill_me"])
                self.assertEqual("current-intake-only", result["model_selection"]["scope"])
                self.assertIn("Reassess", result["model_selection"]["reason"])
        for request in ("Explain the function and fix the bug.",
                        "함수 설명하고 수정해줘"):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("standard", result["effort"])
                self.assertEqual("balanced", result["model_tier"])
                self.assertEqual("resolve_context", result["response_mode"])

    def test_explanation_cue_never_certifies_no_action_from_sentence_shape(self) -> None:
        explanations = ("Explain the function", "Explain how the function works",
                        "Can you explain the function", "함수 설명해줘", "함수 설명 부탁해")
        actions = ("delete the file", "perform the requested change", "파일 삭제해줘",
                   "검증해줘")
        separators = (";", "\n", " & ", " and ", " ", ". ")
        for explanation in explanations:
            for action in actions:
                for separator in separators:
                    for left, right in ((explanation, action), (action, explanation)):
                        request = left + separator + right
                        with self.subTest(request=request):
                            result = classify_request(request)
                            self.assertEqual("resolve_context", result["response_mode"])
                            self.assertFalse(result["grill_me"])
                            self.assertEqual("triage", result["recommended_route"])

    def test_explanation_cue_defers_meaning_without_requiring_a_question(self) -> None:
        for request in (
            "render_advisory_markdown 함수 설명해줘",
            "scripts/workflow_output.py의 함수가 빈 목록을 어떻게 처리하는지 설명해줘",
            "Explain the render_advisory_markdown function.",
            "Please explain the render_advisory_markdown function.",
            "Can you please explain the function?",
            "Please could you explain the function?",
            "Explain how to update the implementation.",
            "Explain how to apply the patch.",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("resolve_context", result["response_mode"])
                self.assertFalse(result["grill_me"])
                self.assertIn("Answer directly", result["reason"])
                self.assertIn("without another routing pass", result["reason"])

    def test_explanation_does_not_hide_a_separate_action(self) -> None:
        for request in (
            "파일 삭제해주고 함수 설명해줘",
            "Explain the function;delete the file.",
            "Explain the function\nDelete the file.",
            "Explain the function & fix the bug.",
            "Explain the function and fix the empty-list bug.",
            "함수 설명해줘. 그리고 빈 목록 버그도 수정해줘",
            "설명해줘. 그다음 테스트를 실행해줘",
            "Please explain and commit the fix.",
            "Explain the function, then update the implementation.",
            "Explain the function and also fix the empty-list bug.",
            "Explain the function and apply the patch.",
            "Can you please explain the function and then apply the patch?",
            "Explain the function; please also update the implementation.",
            "Explain the function and quickly fix the bug.",
            "Explain the function and make the requested change.",
            "설명해줘. 그리고 파일 삭제해.",
            "Explain how the function works and fix the empty-list bug.",
            "Explain how the function works and perform the requested changes.",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertNotEqual("answer_first", result["response_mode"])
                self.assertNotEqual("none", result["recommended_route"])

    def test_uncertain_coordination_requires_context_not_a_user_question(self) -> None:
        for request in (
            "Explain input and output.",
            "Explain how to update and apply the patch.",
            "Explain the function and perform the requested changes.",
            "Explain how the function works and quickly fix it.",
            "설명해줘. 그리고 파일 삭제해.",
            "설명해줘 파일 삭제해",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("resolve_context", result["response_mode"])
                self.assertFalse(result["grill_me"])
                self.assertNotEqual("work", result["response_mode"])

    def test_explanation_auto_route_answers_without_work_authority(self) -> None:
        argv = [sys.executable, str(ROOT / "scripts" / "workflow.py"), "route", "auto",
                "--advisory", "--hook-stdin", "--format", "json"]
        for prompt in ("render_advisory_markdown 함수 설명해줘",
                       "Please explain the render_advisory_markdown function.",
                       "Can you please explain the function?"):
            with self.subTest(prompt=prompt):
                result = subprocess.run(argv, input=json.dumps({"prompt": prompt}),
                                        cwd=ROOT, capture_output=True, text=True, check=True)
                route = json.loads(result.stdout)
                self.assertEqual("resolve_context", route["intake_advice"]["response_mode"])
                self.assertEqual(["common/skills/agent-operating-skill/SKILL.md"],
                                 route["required_docs"])
                self.assertIsNone(route["request_classification"])
                self.assertTrue(route["advisory"])

    def test_mixed_explanation_auto_route_preserves_action_without_authority(self) -> None:
        argv = [sys.executable, str(ROOT / "scripts" / "workflow.py"), "route", "auto",
                "--advisory", "--hook-stdin", "--format", "json"]
        for prompt in (
            "파일 삭제해주고 함수 설명해줘",
            "Explain the function;delete the file.",
            "Explain the function\nDelete the file.",
            "Explain the function & fix the bug.",
            "Explain the function, then update the implementation.",
            "Explain the function and also fix the empty-list bug.",
            "Explain the function and apply the patch.",
            "Explain how the function works and fix the empty-list bug.",
            "설명해줘. 그리고 파일 삭제해.",
        ):
            with self.subTest(prompt=prompt):
                result = subprocess.run(argv, input=json.dumps({"prompt": prompt}),
                                        cwd=ROOT, capture_output=True, text=True, check=True)
                route = json.loads(result.stdout)
                self.assertNotEqual("answer_first", route["intake_advice"]["response_mode"])
                self.assertNotEqual("none", route["command"])
                self.assertIsNone(route["request_classification"])
                self.assertTrue(route["advisory"])

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
