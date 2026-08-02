"""Request text may inform answers and documentation, never authorize work."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_request import classify_request, infer_concerns_from_request


class WorkflowRequestIntakeTests(unittest.TestCase):
    def test_natural_language_never_selects_a_work_route(self) -> None:
        requests = (
            "코드 정리해줘",
            "Review the current diff",
            "Fix scripts/workflow.py line 10",
            "커밋하고 푸시해줘",
            "commit and push",
            "v1.2.3 태그를 배포해줘",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
        )

        for request in requests:
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("clarify_first", classification["response_mode"])
                self.assertEqual("triage", classification["recommended_route"])
                self.assertTrue(classification["grill_me"])

    def test_direct_questions_remain_answer_first(self) -> None:
        for request in (
            "what does this do?",
            "이제 어떻게 동작해?",
            "Fix means the same as repair here, right?",
        ):
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("answer_first", classification["response_mode"])
                self.assertEqual("none", classification["recommended_route"])
                self.assertFalse(classification["grill_me"])

    def test_action_shaped_questions_are_not_answer_only(self) -> None:
        classification = classify_request("Can you fix scripts/workflow.py?")

        self.assertEqual("clarify_first", classification["response_mode"])
        self.assertEqual("triage", classification["recommended_route"])


class ConcernInferenceTests(unittest.TestCase):
    def test_request_text_still_infers_non_authoritative_document_concerns(self) -> None:
        cases = (
            ("Add scenario regression tests", "testing"),
            ("Preserve Spill workflow label bridge data", "metering"),
            ("Update the agent skill bundle", "skill-card"),
            ("Review the branch naming strategy", "branch"),
        )

        for request, concern in cases:
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_explicit_graphify_opt_out_drops_the_concern(self) -> None:
        for request in (
            "Do not run Graphify for this task.",
            "Never include Graphify here.",
            "Graphify는 제외해줘.",
            "그래피는 지금 돌리면 안됨",
        ):
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_double_negation_keeps_the_graphify_concern(self) -> None:
        for request in (
            "Do not skip Graphify.",
            "Graphify는 제외하지 마.",
            "그래피는 건너뛰지 마.",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_attached_hangul_particles_match_complete_latin_keywords(self) -> None:
        self.assertIn("graphify", infer_concerns_from_request("Graphify를 실행해줘"))
        self.assertNotIn("graphify", infer_concerns_from_request("graphifyer를 검토해줘"))


if __name__ == "__main__":
    unittest.main()
