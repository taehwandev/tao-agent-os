from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_request import classify_request


class WorkflowRequestContinuationTests(unittest.TestCase):
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

        self.assertEqual("clarify_first", result["response_mode"])
        self.assertEqual("triage", result["recommended_route"])
        self.assertFalse(result["continuation_scope_used"])

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
