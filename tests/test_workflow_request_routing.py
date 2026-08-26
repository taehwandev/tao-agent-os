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

    def test_commit_push_pr_follow_up_keeps_the_commit_route_shape(self) -> None:
        classification = classify_request(
            "커밋하고 푸시한 뒤 develop 대상 PR까지 생성해줘"
        )

        self.assertEqual("commit", classification["route_shape"])
        self.assertEqual("work", classification["shape_response_mode"])

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
            ("web service React Native Python 스킬 pack 추가", "web-service-stack"),
            ("크리스밴 스킬처럼 활용해서 rn react python 스킬 추가해줘", "web-service-stack"),
            ("React Native 화면을 추가해줘", "react-native"),
            ("FastAPI endpoint를 Python web service에 추가해줘", "python-web-service"),
            ("Create a Python API endpoint", "python-web-service"),
            ("크리스밴 스킬처럼 활용해서 rn react python 스킬 추가해줘", "python-web-service"),
        )
        for request, concern in cases:
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_generic_python_skill_requests_do_not_infer_web_service(self) -> None:
        for request in (
            "Add a Python data science skill card",
            "Create a Python CLI skill",
            "Create a Python exporter skill",
        ):
            with self.subTest(request=request):
                self.assertNotIn(
                    "python-web-service",
                    infer_concerns_from_request(request),
                )
                self.assertNotIn(
                    "web-service-stack",
                    infer_concerns_from_request(request),
                )

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


class AttachedHangulParticleTests(unittest.TestCase):
    """Korean writes "Graphify는", not "Graphify 는".

    Python's \\b finds no boundary between a Latin letter and a Hangul particle
    because both are word characters, so the ordinary Korean spelling used to
    match no hint at all: "Graphify는 제외하지 마" inferred nothing, which looks
    to the user exactly like the inverted match — they asked to keep Graphify
    and lost it.
    """

    def test_attached_particle_opt_out_drops_the_concern(self) -> None:
        for request in (
            "Graphify는 빼줘",
            "Graphify는 제외해줘",
            "graphify는 생략",
            "Graphify는 하지 마",
            "graphify없이 진행해줘",
        ):
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_attached_particle_double_negation_keeps_the_concern(self) -> None:
        for request in (
            "Graphify는 제외하지 마",
            "Graphify는 빼지 말고 돌려줘",
            "graphify는 생략하지 마",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_attached_particle_request_infers_the_concern(self) -> None:
        """The control that fails if the junction fix is reverted.

        Without it the hint itself never fires, so the concern is absent no
        matter which direction the sentence argues.
        """

        self.assertIn("graphify", infer_concerns_from_request("Graphify는 어떻게 써?"))

    def test_other_latin_keyword_concerns_share_the_fix(self) -> None:
        """The blind spot was never graphify-specific: 228 hints are \\b-anchored."""

        for request, concern in (
            ("SwiftUI는 어떻게 쓰지", "swift"),
            ("CI는 어떻게 되어 있어", "ci"),
            ("PR을 만들어줘", "pull-request"),
            ("SEO를 개선하자", "seo"),
        ):
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_negative_control_latin_identifiers_do_not_match(self) -> None:
        """The junction split must not become a substring match.

        The space only lands between a complete Latin run and an attached
        Hangul syllable, so a longer identifier still has to fail the hint.
        """

        self.assertNotIn("graphify", infer_concerns_from_request("graphifyer를 고쳐줘"))
        self.assertNotIn(
            "graphify", infer_concerns_from_request("graphifyui는 무엇인가")
        )


class GraphifyExclusionPhrasingTests(unittest.TestCase):
    """Opting out of Graphify must not depend on one exact verb.

    The exclusion patterns were anchored to run/use/invoke/call/install/enable,
    so "do not execute Graphify" still inferred the concern and pulled the whole
    Graphify surface into the route. Korean drops the verb entirely.
    """

    EXCLUSIONS = (
        "Do not execute Graphify for this task",
        "Do not run Graphify for this task",
        "Never execute graphify here",
        "Finish without executing graphify",
        "Don't include Graphify",
        "Don’t include Graphify",
        "Do not include graphify in this task",
        "Never include Graphify here",
        "Proceed without including Graphify",
        "Graphify should not be included",
        "Graphify 는 하지 마",
        "graphify 하지 않습니다",
        "그래프 는 제외",
    )

    def test_exclusion_phrasings_drop_the_graphify_concern(self) -> None:
        for request in self.EXCLUSIONS:
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_negated_include_regresses_the_old_action_verb_gap(self) -> None:
        """`include` was absent from the action verbs, so this kept Graphify."""

        self.assertNotIn(
            "graphify",
            infer_concerns_from_request("Don't include Graphify"),
        )

    def test_negative_control_ordinary_graphify_requests_still_infer_it(self) -> None:
        """The control: broadening the exclusion must not disable inference.

        If it did, a genuine Graphify request would silently lose its concern
        and the route would never load the Graphify surface at all.
        """

        for request in (
            "Run graphify and report the project graph",
            "Include Graphify in the routing review",
            "graphify 그래프를 갱신해줘",
            "Rebuild the knowledge graph with graphify update",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_double_negation_include_fix_does_not_invert_removal_verbs(self) -> None:
        for request in (
            "Do not exclude Graphify",
            "Don’t exclude Graphify",
            "Graphify 는 제외하지 마",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))


class GraphifyOptOutVerbTests(unittest.TestCase):
    """Opting out by removal verb, and the double negation that undoes it.

    "Skip Graphify" was not recognised at all, and "Graphify 는 제외하지 마"
    ("do NOT exclude Graphify") matched a bare-negation pattern and dropped the
    concern the user had just asked to keep.
    """

    OPT_OUTS = (
        "Skip Graphify for this task",
        "Omit graphify here",
        "Please exclude graphify",
        "Disable graphify for now",
        "Bypass graphify entirely",
        "Leave out graphify",
        "Leave graphify out of this",
        "Drop graphify from this run",
        "Graphify should be skipped",
        "그래피는 빼줘",
        "그래피 빼고 진행해줘",
        "그래피를 제외해줘",
        "지식 그래프는 생략해줘",
        "graphify 는 건너뛰어",
        "프로젝트 그래프는 무시해줘",
    )

    DOUBLE_NEGATIONS = (
        "Do not skip graphify",
        "Don't exclude graphify",
        "Never omit graphify",
        "do not disable graphify",
        "You should not bypass graphify",
        "Graphify 는 제외하지 마",
        "그래피는 빼지 마",
        "그래피 건너뛰지 마",
        "graphify 생략하지 말고 진행해",
        "지식 그래프는 무시하지 않는다",
    )

    def test_opt_out_verbs_drop_the_graphify_concern(self) -> None:
        for request in self.OPT_OUTS:
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_double_negation_keeps_the_graphify_concern(self) -> None:
        """Negating the opt-out verb asks for the opposite of the opt-out."""

        for request in self.DOUBLE_NEGATIONS:
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_negative_control_genuine_graphify_requests_still_infer_it(self) -> None:
        """The opposite direction: the broadened opt-out must not swallow work.

        Korean 그래프 is an ordinary word, so an over-broad opt-out pattern
        would strip the concern from requests that are asking for Graphify.
        """

        for request in (
            "Run graphify update on the repo",
            "graphify query 로 구조를 설명해줘",
            "graphify 그래프를 갱신해줘",
            "지식 그래프를 만들어줘",
            "Rebuild the knowledge graph with graphify update",
        ):
            with self.subTest(request=request):
                self.assertIn("graphify", infer_concerns_from_request(request))

    def test_unrelated_chart_sentence_is_unaffected(self) -> None:
        """A bare 그래프 mention is not a Graphify request either way."""

        self.assertEqual(
            infer_concerns_from_request("차트에서 그래프를 제외한 나머지를 보여줘"),
            [],
        )


class MixedScriptRequestTests(unittest.TestCase):
    """A Korean particle attached to an English token hid it from the classifier.

    Hangul is a word character, so `\\bproduction\\b` does not match
    `production으로`: there is no boundary between `n` and `으`. Korean requests
    naming an English artifact, destination, path, or verb therefore classified
    as if those words were absent -- `v1.2.3을 build를 production으로 승격해줘`
    reached triage while its spaced form did not.

    The property under test is not which route each request gets. It is that
    attaching a particle cannot change the answer, which is what makes this a
    normalization bug rather than a pattern list to extend forever.
    """

    def _classification(self, text: str) -> tuple[str, str]:
        result = classify_request(text)
        return result["route_shape"], result["shape_response_mode"]

    def test_a_particle_does_not_change_the_classification(self) -> None:
        for joined, spaced in (
            (
                "v1.2.3을 build를 production으로 승격해줘",
                "v1.2.3 을 build 를 production 으로 승격해줘",
            ),
            (
                "v1.2.3 tag를 production으로 배포해줘",
                "v1.2.3 tag 를 production 으로 배포해줘",
            ),
            ("working tree를 review해줘", "working tree 를 review 해줘"),
            (
                "scripts/workflow.py의 line 10을 fix해줘",
                "scripts/workflow.py 의 line 10 을 fix 해줘",
            ),
        ):
            with self.subTest(request=joined):
                self.assertEqual(
                    self._classification(spaced), self._classification(joined)
                )

    def test_a_scoped_korean_promotion_naming_english_parts_is_a_release(self) -> None:
        # The reviewer's case: every release signal is present and every one of
        # them is an English token carrying a Korean particle.
        shape, mode = self._classification("v1.2.3을 build를 production으로 승격해줘")

        self.assertEqual("release", shape)
        self.assertEqual("work", mode)

    def test_the_request_is_echoed_as_the_user_wrote_it(self) -> None:
        # Normalization is for matching. Spacing the text for the reader would
        # change what every consumer of this field sees.
        request = "v1.2.3을 production으로 승격해줘"

        self.assertEqual(request, classify_request(request)["request"])


class PromotionReleaseActionTests(unittest.TestCase):
    """A promotion is a release, and it did not route like one.

    `RELEASE_ACTION_PATTERNS` named the verbs that start a release -- deploy,
    publish, ship, tag, push -- but not the ones that finish one. "Promote the
    staging build to production" therefore carried no release action, so the
    release branch never fired and the two-signal scope rule never got the
    chance to send it to Grill-Me either. It routed as an ordinary `task` in
    `work` mode: no release readiness, and no clarification.
    """

    def test_a_promotion_to_production_routes_to_release(self) -> None:
        for request in (
            "promote the 1.4.0 staging build to production for the ios app",
            "roll out the 1.4.0 staging build to production for the ios app",
            "1.4.0 스테이징 빌드를 프로덕션으로 승격해줘",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("release", result["route_shape"])
                self.assertEqual("work", result["shape_response_mode"])

    def test_a_bare_promotion_verb_still_asks_for_clarification(self) -> None:
        # Naming no artifact and no destination is a real ambiguity, not a gap.
        for request in ("promote it", "승격해줘"):
            with self.subTest(request=request):
                self.assertEqual(
                    "clarify_first", classify_request(request)["response_mode"]
                )

    def test_promoting_something_that_is_not_a_build_keeps_the_commit_route(self) -> None:
        """`promote` is anchored to a destination, and this is what that buys.

        Written first as `assertNotEqual("release", ...)` on a bare promotion,
        which passed with or without the anchor: that request names no release
        scope, so the two-signal rule rejects it either way. The anchor earns
        its keep one level down. `commit_release_substep` is false whenever a
        commit request also carries a release action, so an unanchored
        `promote` costs this request its commit route entirely.
        """

        result = classify_request("commit the fix and promote the lesson candidates")
        self.assertEqual("commit", result["route_shape"])
        self.assertNotEqual("release", result["route_shape"])


class KoreanReleaseScopeSignalTests(unittest.TestCase):
    """Release scope signals were English-only while the action list was not.

    A Korean request could name the action -- 배포 was already in
    RELEASE_ACTION_PATTERNS -- but never the destination, so the two-signal scope
    rule read a real deploy as an unclear ask and sent it to Grill-Me. The English
    phrasing of the same request routed to `release`, which is the asymmetry.
    """

    def test_korean_deploy_with_a_destination_routes_to_release(self) -> None:
        for request in (
            "테스터에게 앱 배포",
            "develop 최신화하고 Firebase App Distribution 으로 테스터에게 배포해줘",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("release", result["route_shape"])
                self.assertEqual("work", result["shape_response_mode"])

    def test_a_bare_deploy_verb_still_asks_for_clarification(self) -> None:
        # Naming no artifact and no destination is a real ambiguity, not a gap.
        result = classify_request("배포해줘")
        self.assertEqual("clarify_first", result["response_mode"])

    def test_unrelated_requests_keep_their_route(self) -> None:
        self.assertEqual("code-simplify", classify_request("리팩터링해줘")["route_shape"])


if __name__ == "__main__":
    unittest.main()
