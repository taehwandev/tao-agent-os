"""Selection follows the change, not the platform name.

Each case fixes three sets, written from what the change has to decide before
any of it was implemented: what must be required, what must not be, and what is
allowed either way. The must-not set is the point -- a test that only asserts
what is present passes just as well when the router requires everything.

`conditional` documents are asserted only to be *reachable*: required or
available as a reference. A reading budget may move them between those, but it
may never make them unreachable.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_doc_resolution import resolve_guidance_docs  # noqa: E402
from workflow_request import classify_request, infer_concerns_from_request  # noqa: E402
from workflow_route import resolve_docs  # noqa: E402


def route_for(command, platform, request_text, surface_paths=()):
    concerns = infer_concerns_from_request(request_text)
    return resolve_docs(
        command, platform, concerns, request_classified=True,
        inferred_concerns=concerns, request_text=request_text,
        surface_paths=list(surface_paths),
    )


def resolved(docs):
    return set(resolve_guidance_docs(ROOT, list(docs)))


class ChangeDrivenSelectionTests(unittest.TestCase):
    maxDiff = None

    def test_negated_data_change_does_not_require_data_guidance(self):
        for platform, prompt in (
            ("web", "Do not change the JSON parser; fix only the React button layout."),
            ("android", "DTO 파싱은 수정하지 말고 Compose 버튼 위치만 수정해줘"),
        ):
            with self.subTest(prompt=prompt):
                route = route_for("feature", platform, prompt)
                ui = ("platforms/web/skills/web-react-ui/SKILL.md" if platform == "web"
                      else "platforms/android/skills/android-compose-ui/SKILL.md")
                self.assert_case(route, must=[ui], must_not=[
                    "common/skills/api-contract-compatibility/SKILL.md",
                    "common/skills/defensive-boundaries/SKILL.md",
                ])

    def test_independent_ui_work_survives_data_narrowing(self):
        for platform, prompt, card in (
            ("android", "응답 DTO 파싱을 수정하고 Compose 화면의 로딩 상태 표시도 구현해줘",
             "platforms/android/skills/android-compose-ui/SKILL.md"),
            ("web", "Fix the JSON parser and implement the React loading screen.",
             "platforms/web/skills/web-design-system/SKILL.md"),
        ):
            with self.subTest(prompt=prompt):
                route = route_for("feature", platform, prompt)
                self.assert_case(route, must=[card,
                    "common/skills/api-contract-compatibility/SKILL.md"], must_not=[])

    def assert_case(self, route, *, must, must_not, conditional=()):
        required = set(route["required_docs"])
        reachable = required | set(route["reference_docs"])

        for doc in resolved(must):
            with self.subTest(must=doc):
                self.assertIn(doc, required)
        for doc in resolved(must_not):
            with self.subTest(must_not=doc):
                self.assertNotIn(doc, required)
        for doc in resolved(conditional):
            with self.subTest(conditional=doc):
                self.assertIn(doc, reachable)

    # ------------------------------------------------------------------ A
    def test_android_dto_parsing_fix_reads_the_contract_not_the_architecture(self):
        route = route_for(
            "bugfix", "android", "안드로이드 응답 DTO의 JSON 파싱 오류 수정해줘",
            ["app/src/main/java/com/example/data/dto/UserDto.kt"],
        )
        self.assert_case(
            route,
            must=[
                "common/skills/api-contract-compatibility/SKILL.md",
                "common/skills/defensive-boundaries/SKILL.md",
                "common/skills/testing/SKILL.md",
                "workflows/skills/bugfix-debugging/SKILL.md",
            ],
            must_not=[
                "platforms/android/skills/android-compose-ui/SKILL.md",
                "platforms/android/skills/android-memory-lifecycle/SKILL.md",
                "platforms/android/skills/android-architecture/references/navigation-deep-links.md",
                "platforms/android/skills/android-architecture/references/runtime-composition.md",
                "platforms/web/skills/web-architecture/SKILL.md",
            ],
            conditional=[
                "common/skills/error-modeling/SKILL.md",
                "platforms/android/skills/android-state-data/SKILL.md",
            ],
        )

    def test_a_dto_under_a_ui_package_is_still_a_data_change(self):
        """Item 4: where the file sits does not decide what the change is."""

        route = route_for(
            "bugfix", "android", "응답 DTO 파싱 오류 수정해줘",
            ["app/src/main/java/com/example/ui/settings/SettingsDto.kt"],
        )
        self.assert_case(
            route,
            must=["common/skills/api-contract-compatibility/SKILL.md"],
            must_not=["platforms/android/skills/android-compose-ui/SKILL.md"],
        )

    # ------------------------------------------------------------------ B
    def test_compose_button_placement_reads_ui_and_accessibility_only(self):
        route = route_for(
            "feature", "android", "Compose 설정 화면에서 저장 버튼 위치 수정해줘",
            ["app/src/main/java/com/example/ui/settings/SettingsScreen.kt"],
        )
        self.assert_case(
            route,
            must=[
                "platforms/android/skills/android-compose-ui/SKILL.md",
                "common/skills/accessibility-i18n/SKILL.md",
                "common/skills/ui-visual-verification/SKILL.md",
            ],
            must_not=[
                "platforms/android/skills/android-state-data/SKILL.md",
                "platforms/android/skills/android-module-structure/SKILL.md",
                "platforms/android/skills/android-background-work/SKILL.md",
                "common/skills/api-contract-compatibility/SKILL.md",
                "common/skills/data-persistence-sync/SKILL.md",
            ],
        )

    # ------------------------------------------------------------------ C
    def test_a_web_config_lookup_reads_only_the_core_contract(self):
        prompt = "웹 재시도 설정이 어디에 있는지 알려줘"
        classification = classify_request(prompt, conversation_first=True)
        self.assertEqual("answer_first", classification["shape_response_mode"])

        route = route_for("analysis", "web", prompt)

        self.assertEqual(
            ["common/skills/agent-operating-skill/SKILL.md"], route["required_docs"]
        )
        self.assertEqual("lookup", route["reading_scope"]["mode"])

    # ------------------------------------------------------------------ D
    def test_web_api_parsing_fix_reads_the_contract_not_the_design_system(self):
        route = route_for(
            "bugfix", "web", "웹 API 응답 파싱 오류 수정해줘",
            ["src/api/parseResponse.ts"],
        )
        self.assert_case(
            route,
            must=[
                "common/skills/api-contract-compatibility/SKILL.md",
                "common/skills/defensive-boundaries/SKILL.md",
                "common/skills/testing/SKILL.md",
            ],
            must_not=[
                "platforms/web/skills/web-design-system/SKILL.md",
                "common/skills/public-discovery/SKILL.md",
                "platforms/web/skills/web-accessibility-i18n/SKILL.md",
            ],
            conditional=[
                "common/skills/error-modeling/SKILL.md",
                "platforms/web/skills/web-state-data/SKILL.md",
            ],
        )

    # ------------------------------------------------------------------ E
    def test_check_then_add_keeps_its_edit_intent(self):
        prompt = "기본 이미지 필드가 있는지 확인하고 없으면 추가해줘"
        classification = classify_request(prompt, conversation_first=True)

        self.assertNotEqual("analysis", classification["route_shape"])
        self.assertNotEqual("none", classification["route_shape"])

    def test_check_then_add_selects_as_a_data_change_once_the_owner_is_known(self):
        route = route_for(
            "bugfix", "android",
            "응답에 기본 이미지 필드가 있는지 확인하고 없으면 추가해줘",
            ["app/src/main/java/com/example/data/dto/ImageDto.kt"],
        )
        self.assert_case(
            route,
            must=[
                "common/skills/api-contract-compatibility/SKILL.md",
                "common/skills/testing/SKILL.md",
            ],
            must_not=["platforms/android/skills/android-compose-ui/SKILL.md"],
        )

    # ------------------------------------------------------------------ F
    def test_an_explicit_security_change_keeps_every_safety_card(self):
        route = route_for(
            "task", "web", "로그인 토큰 저장 방식을 보안 요구대로 바꿔줘",
        )
        self.assert_case(
            route,
            must=[
                "common/skills/secure-development-baseline/SKILL.md",
                "common/skills/security-privacy-review/SKILL.md",
                "product-patterns/skills/auth-rbac-permissions/SKILL.md",
                "product-patterns/skills/auth-rbac-implementation/SKILL.md",
            ],
            must_not=[],
        )

    def test_no_optimization_drops_a_named_safety_concern(self):
        """The cap and the byte budget must not be able to reach these."""

        from unittest.mock import patch

        with patch("workflow_route.MAX_REQUIRED_DOCS", 1), \
                patch("workflow_route.REQUIRED_DOC_BUDGET_BYTES", 1):
            route = resolve_docs(
                "bugfix", "web", ["security", "auth"], request_classified=True,
            )
        required = set(route["required_docs"])
        for doc in resolved([
            "common/skills/secure-development-baseline/SKILL.md",
            "common/skills/security-privacy-review/SKILL.md",
            "product-patterns/skills/auth-rbac-permissions/SKILL.md",
        ]):
            with self.subTest(doc=doc):
                self.assertIn(doc, required)


class PlatformNameAloneTests(unittest.TestCase):
    """Naming a platform may require its contract, never its detailed cards."""

    DETAIL_CARDS = (
        "platforms/android/skills/android-architecture/references/runtime-composition.md",
        "platforms/android/skills/android-architecture/references/webview-surface.md",
        "platforms/android/skills/android-architecture/references/navigation-deep-links.md",
        "platforms/android/skills/android-architecture/references/structure-baseline.md",
    )

    def test_the_platform_name_does_not_require_the_detail_cards(self):
        for command in ("bugfix", "feature", "task", "refactor"):
            with self.subTest(command=command):
                route = resolve_docs(command, "android", [], request_classified=True)
                for doc in self.DETAIL_CARDS:
                    self.assertNotIn(doc, route["required_docs"])

    def test_a_named_concern_still_reaches_them(self):
        cases = (
            ("dependency",
             "platforms/android/skills/android-architecture/references/runtime-composition.md"),
            ("navigation",
             "platforms/android/skills/android-architecture/references/navigation-deep-links.md"),
            ("webview",
             "platforms/android/skills/android-architecture/references/webview-surface.md"),
            ("structure",
             "platforms/android/skills/android-architecture/references/structure-baseline.md"),
        )
        for concern, doc in cases:
            with self.subTest(concern=concern):
                route = resolve_docs("task", "android", [concern], request_classified=True)
                self.assertIn(
                    doc, set(route["required_docs"]) | set(route["reference_docs"])
                )

    def test_the_platform_contract_stays_small(self):
        """Item 3: the always-applicable contract is small, the detail is not."""

        card = ROOT / ("platforms/android/skills/android-architecture/"
                       "references/current-guidance.md")
        self.assertLess(card.stat().st_size, 10_000)


class ComposeCardSplitTests(unittest.TestCase):
    """The Compose bundle is split by decision, and the split lost no rule.

    39.9 KB reached every Compose change because one card answered six
    questions. Splitting it is only safe if each piece is selectable by the
    decision it answers and every surviving rule still has a home, so both are
    asserted here rather than assumed.
    """

    REFS = ROOT / "platforms/android/skills/android-compose-ui/references"
    CONTRACT = REFS / "current-guidance.md"
    SIBLINGS = (
        "screen-structure.md",
        "compose-performance.md",
        "compose-previews.md",
        "wear-compose.md",
        "official-source-surfaces.md",
    )

    def test_the_authoring_contract_stays_small(self):
        self.assertLess(self.CONTRACT.stat().st_size, 12_000)

    def test_every_sibling_exists_and_is_reachable_from_the_contract(self):
        contract = self.CONTRACT.read_text(encoding="utf-8")
        for name in self.SIBLINGS:
            with self.subTest(sibling=name):
                self.assertTrue((self.REFS / name).is_file())
                self.assertIn(name, contract)

    def test_each_decision_selects_its_own_sibling(self):
        cases = (
            ("performance", "compose-performance.md"),
            ("preview", "compose-previews.md"),
            ("wear", "wear-compose.md"),
        )
        for concern, sibling in cases:
            with self.subTest(concern=concern):
                route = resolve_docs("task", "android", [concern], request_classified=True)
                reachable = set(route["required_docs"]) | set(route["reference_docs"])
                self.assertIn(
                    f"platforms/android/skills/android-compose-ui/references/{sibling}",
                    reachable,
                )

    def test_moving_a_control_does_not_require_the_other_decisions(self):
        route = route_for(
            "feature", "android", "Compose 설정 화면에서 저장 버튼 위치 수정해줘",
            ["app/src/main/java/com/example/ui/settings/SettingsScreen.kt"],
        )
        required = set(route["required_docs"])
        base = "platforms/android/skills/android-compose-ui/references"
        for sibling in ("compose-performance.md", "screen-structure.md",
                        "wear-compose.md", "official-source-surfaces.md"):
            with self.subTest(sibling=sibling):
                self.assertNotIn(f"{base}/{sibling}", required)
        self.assertIn(f"{base}/current-guidance.md", required)

    def test_the_split_kept_every_rule_it_did_not_explicitly_drop(self):
        """One distinctive sentence per moved section, each still present once."""

        moved = {
            "screen-structure.md": [
                "Replace `hiltViewModel()` with the repo's DI pattern.",
                "Choose the smallest track that makes ownership clear",
                "Use package names that reveal ownership and dependency direction",
                "Before moving Compose UI into a shared package, ask",
            ],
            "compose-performance.md": [
                "Use a measure-first loop for Compose performance work",
                "Stability annotations are contracts.",
                "Every domain-backed lazy item should have a stable key",
                "Compose performance starts with stable inputs.",
                "A Compose stability configuration file can mark external",
            ],
            "compose-previews.md": [
                "Every named stateless composable that renders UI needs a colocated",
                "Use the official Compose preview parameter APIs for multi-state previews",
            ],
            "wear-compose.md": [
                "Use one outer `AppScaffold` with `ScreenScaffold` children.",
            ],
            "official-source-surfaces.md": [
                "XML-to-Compose migration: migrate one XML candidate at a time",
                "CameraX in Compose: keep camera provider/use-case binding",
            ],
        }
        kept_in_contract = [
            "Screen/Holder Composable -> Content Composable -> Section Composable",
            "Compose screens must be split into named composables",
            "Do not obtain ViewModels, repositories, activities, nav controllers",
            "Model screen states explicitly",
            "Accessibility labels, roles, selected states, enabled states",
        ]

        for name, sentences in moved.items():
            body = (self.REFS / name).read_text(encoding="utf-8")
            for sentence in sentences:
                with self.subTest(sibling=name, sentence=sentence[:40]):
                    self.assertIn(sentence, body)

        contract = self.CONTRACT.read_text(encoding="utf-8")
        for sentence in kept_in_contract:
            with self.subTest(sentence=sentence[:40]):
                self.assertIn(sentence, contract)

    def test_the_dropped_content_was_routing_not_rules(self):
        """Only the two pointer sections left the bundle."""

        bundle = "\n".join(
            (self.REFS / name).read_text(encoding="utf-8")
            for name in ("current-guidance.md", *self.SIBLINGS)
        )
        for gone in ("## Android Skill Source Check",
                     "## Edge-To-Edge And IME Insets"):
            with self.subTest(section=gone):
                self.assertNotIn(gone, bundle)
        # The edge-to-edge reference it pointed at is still reachable.
        self.assertIn("edge-to-edge-insets.md", bundle)
        self.assertTrue((self.REFS / "edge-to-edge-insets.md").is_file())

    def test_a_pruned_duplicate_survives_in_exactly_one_place(self):
        """Each rule that was stated twice is now stated once."""

        duplicates = (
            "stable key from server/domain data",
            "Optional slots should be nullable",
            "placement such as outer padding",
        )
        files = ("current-guidance.md", *self.SIBLINGS)
        for fragment in duplicates:
            hits = [
                name for name in files
                if fragment in (self.REFS / name).read_text(encoding="utf-8")
            ]
            with self.subTest(fragment=fragment):
                self.assertEqual(1, len(hits), f"{fragment} in {hits}")


class PathSurfaceScopeTests(unittest.TestCase):
    """A touched file names the surface; the request names the change.

    One touched Compose file used to make 162 KB across 21 documents required-
    eligible, and the cap then kept whichever tier came first: a scroll
    performance task required the previews and screen-structure references and
    never the performance one. The path rule now carries the contract any
    change to that surface applies, the ecosystem stays a reference candidate,
    and performance, state and layout each have their own rule.
    """

    COMPOSE_SCREEN = ["app/src/main/java/com/example/ui/feed/FeedScreen.kt"]
    PERF = "platforms/android/skills/android-compose-ui/references/compose-performance.md"
    STRUCTURE = "platforms/android/skills/android-compose-ui/references/screen-structure.md"
    PREVIEWS = "platforms/android/skills/android-compose-ui/references/compose-previews.md"
    SOURCE_MAP = ("platforms/android/skills/source-coverage/references/"
                  "compose-performance-source-map.md")

    def test_a_performance_task_requires_the_performance_reference(self):
        route = route_for("task", "android", "리스트 스크롤이 버벅여서 성능 개선해줘",
                          self.COMPOSE_SCREEN)
        required = set(route["required_docs"])

        self.assertIn(self.PERF, required)
        # The failure this replaces: previews and screen structure were
        # required for a performance task and the performance card was not.
        self.assertNotIn(self.PREVIEWS, required)
        self.assertNotIn(self.STRUCTURE, required)

    def test_a_state_bug_requires_the_state_holder_rules(self):
        route = route_for("bugfix", "android", "ViewModel 상태가 회전 후 사라져요",
                          ["app/src/main/java/com/example/ui/feed/FeedViewModel.kt"])
        required = set(route["required_docs"])

        self.assertTrue(any("android-viewmodel-state" in doc for doc in required))
        self.assertNotIn(self.PREVIEWS, required)
        self.assertNotIn(self.PERF, required)

    def test_touching_a_file_alone_requires_only_the_surface_contract(self):
        """No action word: the contract, not the platform's whole library."""

        route = resolve_docs("task", "android", [], request_classified=True,
                             surface_paths=self.COMPOSE_SCREEN)
        required = set(route["required_docs"])

        for doc in (self.PERF, self.STRUCTURE, self.PREVIEWS, self.SOURCE_MAP):
            with self.subTest(doc=doc):
                self.assertNotIn(doc, required)

    def test_the_ecosystem_stays_a_reference_candidate(self):
        """Narrowing what is required must not remove what is reachable."""

        route = resolve_docs("task", "android", [], request_classified=True,
                             surface_paths=self.COMPOSE_SCREEN)
        reachable = set(route["docs"]) | set(route["reference_docs"])

        for doc in (self.SOURCE_MAP, self.STRUCTURE, self.PREVIEWS):
            with self.subTest(doc=doc):
                self.assertIn(doc, reachable)

    def test_a_reference_only_surface_never_becomes_required(self):
        from workflow_doc_surfaces import infer_surface_docs, required_surface_docs

        _, matches = infer_surface_docs(
            command="task", platform="android", request_text="",
            surface_paths=self.COMPOSE_SCREEN,
        )
        required_surface_docs(matches)
        ecosystem = [m for m in matches if m.get("name") == "android_compose_ecosystem"]

        self.assertTrue(ecosystem, "the ecosystem surface did not match")
        for match in ecosystem:
            self.assertFalse(match["required_eligible"])
            self.assertEqual("reference_only_surface", match["selection_reason"])

    def test_every_ui_path_rule_carries_a_small_contract(self):
        """The regression this prevents is a path rule regrowing into a library."""

        import json
        from workflow_doc_resolution import resolve_guidance_docs

        rules = json.loads((ROOT / "workflow-doc-surfaces.json").read_text(encoding="utf-8"))
        doc_sets = rules["doc_sets"]
        for rule in rules["path_surfaces"]:
            if rule.get("reference_only"):
                continue
            for name in rule.get("doc_sets", []):
                resolved = resolve_guidance_docs(ROOT, list(doc_sets[name]))
                size = sum((ROOT / d).stat().st_size for d in resolved if (ROOT / d).exists())
                with self.subTest(rule=rule["name"], doc_set=name):
                    self.assertLessEqual(
                        size, 50_000,
                        f"{name} makes {size}B required from a touched file alone",
                    )


if __name__ == "__main__":
    unittest.main()
