from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_route_state import request_fingerprint
from workflow_platform_inference import infer_platform

SPEC = importlib.util.spec_from_file_location("platform_preflight", ROOT / "scripts/agent-preflight.py")
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

REQUEST = "응 좋아. 그리고 서비스 코드들은 다 외부 별개로 분리할거고, 안드로이드 코드만 남길거야. 작업 진행하고, 커밋도 계속해줘"
CONTINUATION = "스킬 문서대로 앱 서비스 분리, 앱 모듈의 DI 조립과 서비스 구현 경계 점검 및 수정"
ANDROID_CARD = "platforms/android/skills/android-architecture/references/current-guidance.md"
MODULE_REFS = "platforms/android/skills/android-module-structure/references/"


class PlatformInferenceTests(unittest.TestCase):
    def args(self, request=REQUEST, continuation=CONTINUATION, *, platform=None, command="refactor", authorize=True):
        argv = ["--command", command, "--project", str(ROOT), "--request", request,
                "--continuation-scope", continuation]
        if platform:
            argv += ["--platform", platform]
        args = preflight.build_parser(ROOT).parse_args(argv)
        if authorize:
            args.runtime_session_id = "platform-test-session"
            args.intent_envelope = json.dumps({
                "schema_version": 1,
                "request_fingerprint": request_fingerprint(preflight.request_intake(args)),
                "runtime_session_id": args.runtime_session_id,
                "mode": "answer" if command == "analysis" else "work",
                "intent": "analysis" if command == "analysis" else "refactoring",
                "target_summary": "authentication module boundary",
                "requested_effects": ["read" if command == "analysis" else "local_write"],
                "ambiguity": "resolved",
            })
        return args

    def test_actual_android_followup_selects_di_boundaries_without_flag(self):
        route, error, status = preflight.route_payload(self.args())
        self.assertEqual((error, status), ("", 0))
        self.assertEqual(route["platform"], "android")
        self.assertIn(MODULE_REFS + "current-guidance.md", route["required_docs"])
        self.assertIn(MODULE_REFS + "di-build-logic.md", route["required_docs"])
        self.assertIn(MODULE_REFS + "module-boundaries.md", route["required_docs"])
        self.assertNotIn("module", route.get("inferred_concerns", []))
        self.assertNotIn("dependency", route.get("inferred_concerns", []))
        for unrelated in ("compose", "webview", "external-skill-source-coverage", "performance"):
            self.assertFalse(any(unrelated in doc for doc in route["required_docs"]))
        explicit, _, _ = preflight.route_payload(self.args(platform="android"))
        self.assertEqual(route["required_docs"], explicit["required_docs"])

    def test_original_missing_flag_path_has_no_android_card(self):
        with patch.object(preflight, "infer_platform", return_value=None):
            route, error, status = preflight.route_payload(self.args())
        self.assertEqual((error, status), ("", 0))
        self.assertIsNone(route["platform"])
        self.assertNotIn(ANDROID_CARD, route["required_docs"])

    def test_explicit_platform_wins(self):
        route, error, status = preflight.route_payload(self.args(platform="web"))
        self.assertEqual((error, status), ("", 0))
        self.assertEqual(route["platform"], "web")

    def test_continuation_can_select_docs_after_independent_authorization(self):
        route, error, status = preflight.route_payload(self.args("수정해줘", "안드로이드 앱의 인증 계약 분리"))
        self.assertEqual((error, status), ("", 0))
        self.assertEqual(route["platform"], "android")

    def test_continuation_never_authorizes_work(self):
        route, error, status = preflight.route_payload(self.args("응", "안드로이드 앱 수정", authorize=False))
        self.assertIsNone(route)
        self.assertEqual(status, 2)
        self.assertTrue(error)

    def test_read_only_intake_stays_read_only(self):
        route, error, status = preflight.route_payload(self.args("안드로이드 코드 구조 설명해줘", "", command="analysis"))
        self.assertEqual((error, status), ("", 0))
        self.assertEqual(route["command"], "analysis")
        self.assertEqual(route["platform"], "android")

    def test_behavior_preservation_does_not_negate_platform(self):
        for request in (
            "Android app refactor without changing behavior",
            "Refactor Android app without changing the existing behaviour",
            "안드로이드 앱 동작은 바꾸지 않고 DI 모듈만 분리해줘",
        ):
            with self.subTest(request=request):
                self.assertEqual(infer_platform(request), "android")
                route, error, status = preflight.route_payload(self.args(request, ""))
                self.assertEqual((error, status), ("", 0))
                self.assertEqual(route["platform"], "android")
                self.assertTrue(any(doc.startswith("platforms/android/") for doc in route["required_docs"]))

    def test_preservation_phrase_does_not_hide_exclusion_or_uncertainty(self):
        for request in (
            "Don't modify Android app without changing behavior",
            "Maybe refactor Android app without changing behavior",
            "안드로이드 앱 동작은 바꾸지 않고 모듈도 건드리지 마",
        ):
            with self.subTest(request=request):
                self.assertIsNone(infer_platform(request))

    def test_macos_selects_shared_swift_platform_without_implying_ios(self):
        for request in ("macOS 앱 리팩토링", "Swift macOS app refactor", "Swift code cleanup"):
            with self.subTest(request=request):
                self.assertEqual(infer_platform(request), "swift")
                route, error, status = preflight.route_payload(self.args(request, ""))
                self.assertEqual((error, status), ("", 0))
                self.assertEqual(route["platform"], "swift")
                self.assertFalse(any(doc.startswith("platforms/ios/") for doc in route["required_docs"]))

    def test_macos_exclusions_and_cross_platform_requests_abstain(self):
        for request in ("macOS 앱은 제외", "Maybe a macOS app", "macOS app and iOS app"):
            self.assertIsNone(infer_platform(request))

    def test_ambiguous_negated_unrelated_and_repository_mentions_abstain(self):
        for request, continuation in [
            ("Android app and web service boundaries", ""),
            ("Android app or iOS app?", ""),
            ("This is not an Android app change", ""),
            ("Don't modify the Android app", ""),
            ("No Android app changes", ""),
            ("안드로이드 코드는 제외하고 문구만 수정", ""),
            ("안드로이드 앱은 건드리지 마", ""),
            ("안드로이드 앱과 무관한 문서 수정", ""),
            ("Maybe an Android app", ""),
            ("Read /repos/android/app", ""),
            ("Notmid 수정", ""),
            ("web app 수정", "Android app 수정"),
        ]:
            with self.subTest(request=request):
                self.assertIsNone(infer_platform(request, continuation))


if __name__ == "__main__":
    unittest.main()
