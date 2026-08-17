from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_purpose import (
    purpose_failures,
    top_level_declaration_failures,
    top_level_type_declarations,
)


def declarations(source: str, path: Path = Path("src/model/contracts.ts")):
    return top_level_type_declarations(path, source.strip().splitlines())


class AgentReviewPurposeTests(unittest.TestCase):
    def test_private_compose_helpers_and_preview_do_not_force_file_splitting(self) -> None:
        current = declarations(
            """
            @Composable
            fun UploadFeedbackStack() {}

            private fun Modifier.uploadFeedbackPadding(): Modifier = this

            @Composable
            private fun UploadRetrySnackbar() {}

            @Composable
            private fun UploadFailureIcon() {}

            @Preview
            @Composable
            private fun UploadFeedbackStackPreview() {}

            private class UploadFeedbackPreviewProvider
            """,
            Path("src/UploadFeedbackStack.kt"),
        )

        self.assertEqual(
            [
                "UploadFeedbackStack",
                "UploadRetrySnackbar",
                "UploadFailureIcon",
                "UploadFeedbackStackPreview",
                "UploadFeedbackPreviewProvider",
            ],
            [declaration["name"] for declaration in current],
        )
        self.assertEqual(
            [],
            top_level_declaration_failures(Path("src/UploadFeedbackStack.kt"), current),
        )

    def test_existing_broad_contract_file_can_change_without_new_owner_failure(self) -> None:
        previous = declarations(
            """
            export type Alpha = { value: string };
            export type Beta = { count: number };
            """
        )
        current = declarations(
            """
            export type Alpha = { value: string; label?: string };
            export type Beta = { count: number };
            """
        )

        self.assertEqual([], top_level_declaration_failures(Path("src/model/contracts.ts"), current, previous))

    def test_existing_broad_contract_file_still_fails_when_new_owner_is_added(self) -> None:
        previous = declarations(
            """
            export type Alpha = { value: string };
            export type Beta = { count: number };
            """
        )
        current = declarations(
            """
            export type Alpha = { value: string };
            export type Beta = { count: number };
            export type Gamma = { enabled: boolean };
            """
        )

        failures = top_level_declaration_failures(Path("src/model/contracts.ts"), current, previous)

        self.assertTrue(any("public/exported top-level owners" in failure for failure in failures))

    def test_existing_broad_contract_file_can_rename_owner_without_growth_failure(self) -> None:
        previous = declarations(
            """
            export type ProposalResult = { value: string };
            export type Notice = { message: string };
            """
        )
        current = declarations(
            """
            export type ChatStartResult = { value: string };
            export type Notice = { message: string };
            """
        )

        self.assertEqual([], top_level_declaration_failures(Path("src/model/contracts.ts"), current, previous))

    def test_kotlin_internal_type_and_factory_are_not_public_owners(self) -> None:
        current = declarations(
            """
            internal class ClickThrottle

            internal fun rememberClickThrottle(): ClickThrottle = ClickThrottle()
            """,
            Path("src/ClickThrottle.kt"),
        )

        self.assertEqual(
            [],
            top_level_declaration_failures(Path("src/ClickThrottle.kt"), current),
        )

    def test_kotlin_state_helpers_with_request_verb_do_not_mix_data_role(self) -> None:
        current = declarations(
            """
            internal class PinnedTabsState

            internal fun rememberPinnedTabsState() = PinnedTabsState()

            internal fun resolvePinnedTabsVisibilityRequest() = true

            internal fun areOriginalTabsVisible() = false
            """,
            Path("src/PinnedTabsState.kt"),
        )

        self.assertEqual(
            ["state", "state", None, None],
            [declaration["role"] for declaration in current],
        )
        self.assertEqual(
            [],
            top_level_declaration_failures(Path("src/PinnedTabsState.kt"), current),
        )

    def test_kotlin_extensions_on_one_receiver_form_one_owner_family(self) -> None:
        current = declarations(
            """
            internal fun UploadActionHandler.start() = Unit
            internal fun UploadActionHandler.cancel() = Unit
            internal fun UploadActionHandler.retry() = Unit
            internal fun UploadActionHandler.finish() = Unit
            internal fun UploadActionHandler.removeMedia() = Unit
            internal fun UploadActionHandler.selectMedia() = Unit
            internal fun UploadActionHandler.openEditor() = Unit
            internal fun UploadActionHandler.closeEditor() = Unit
            """,
            Path("src/UploadTransitions.kt"),
        )

        self.assertEqual(
            [],
            top_level_declaration_failures(Path("src/UploadTransitions.kt"), current),
        )

    def test_kotlin_extensions_on_different_receivers_remain_separate_owners(self) -> None:
        current = declarations(
            """
            internal fun UploadActionHandler.start() = Unit
            internal fun UploadRetryHandler.retry() = Unit
            internal fun UploadCancelHandler.cancel() = Unit
            internal fun UploadEditorHandler.open() = Unit
            internal fun UploadResultHandler.finish() = Unit
            """,
            Path("src/UploadTransitions.kt"),
        )

        failures = top_level_declaration_failures(Path("src/UploadTransitions.kt"), current)

        self.assertTrue(any("non-private top-level owners" in failure for failure in failures))

    def test_unrelated_kotlin_free_functions_remain_separate_owners(self) -> None:
        current = declarations(
            """
            internal fun parseUpload() = Unit
            internal fun validateUpload() = Unit
            internal fun startUpload() = Unit
            internal fun retryUpload() = Unit
            internal fun finishUpload() = Unit
            """,
            Path("src/UploadFunctions.kt"),
        )

        failures = top_level_declaration_failures(Path("src/UploadFunctions.kt"), current)

        self.assertTrue(any("non-private top-level owners" in failure for failure in failures))

    def test_legacy_mixed_package_growth_is_not_a_hard_failure_by_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            package = project / "src" / "model"
            package.mkdir(parents=True)
            (package / "dashboardView.ts").write_text(
                "export function DashboardView() { return null; }\n",
                encoding="utf-8",
            )
            (package / "userClient.ts").write_text(
                "export function createUserClient() { return {}; }\n",
                encoding="utf-8",
            )

            failures = purpose_failures(
                project,
                [Path("src/model/userClient.ts")],
                {"src/model/userClient.ts": {"status": "M", "additions": 1}},
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertFalse(any("package mixes runtime roles" in failure for failure in failures))

    def test_new_runtime_source_in_generic_package_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            package = project / "src" / "utils"
            package.mkdir(parents=True)
            (package / "userClient.ts").write_text(
                "export function createUserClient() { return {}; }\n",
                encoding="utf-8",
            )

            failures = purpose_failures(
                project,
                [Path("src/utils/userClient.ts")],
                {"src/utils/userClient.ts": {"status": "A", "additions": 1}},
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertTrue(any("grab-bag package" in failure for failure in failures))


class KotlinDefaultPublicOwnerTests(unittest.TestCase):
    """Kotlin top-level functions are public with no modifier to match on.

    Scenario: a reviewer runs the structure gate over a Kotlin file that owns
    several unrelated top-level functions. Before the fix the token-driven owner
    test found no `public` keyword, counted zero owners, and let the file pass
    both the four-owner and one-public-owner budgets.
    """

    KOTLIN_FILE = """
package sample

fun buildAlpha() = 1

fun buildBravo() = 2

fun buildCharlie() = 3

fun buildDelta() = 4

fun buildEcho() = 5
"""

    def test_bare_top_level_functions_count_as_public_owners(self) -> None:
        path = Path("app/src/main/kotlin/sample/Builders.kt")
        found = top_level_type_declarations(path, self.KOTLIN_FILE.strip().splitlines())

        self.assertEqual(
            ["buildAlpha", "buildBravo", "buildCharlie", "buildDelta", "buildEcho"],
            [declaration["name"] for declaration in found],
        )

        failures = top_level_declaration_failures(path, found)
        self.assertTrue(any("public/exported top-level owners" in item for item in failures))
        self.assertTrue(any("non-private top-level owners" in item for item in failures))

    def test_negative_control_same_source_as_go_stays_unowned(self) -> None:
        """Go encodes export in the identifier, so lowercase funcs must not count.

        This is the control for the fix: if `default_public` leaked to every
        language whose members are exported by default, this Go file would start
        failing and the assertion below would break.
        """

        path = Path("internal/sample/builders.go")
        source = "package sample\n\n" + "\n\n".join(
            f"func build{name}() int {{ return 1 }}"
            for name in ("Alpha", "Bravo", "Charlie", "Delta", "Echo")
        )
        found = top_level_type_declarations(path, source.splitlines())

        self.assertEqual([], found)
        self.assertEqual([], top_level_declaration_failures(path, found))

    def test_private_kotlin_top_level_functions_stay_unowned(self) -> None:
        path = Path("app/src/main/kotlin/sample/Helpers.kt")
        source = "package sample\n\n" + "\n\n".join(
            f"private fun helper{index}() = {index}" for index in range(6)
        )
        found = top_level_type_declarations(path, source.splitlines())

        self.assertEqual([], found)
        self.assertEqual([], top_level_declaration_failures(path, found))

    def test_internal_kotlin_functions_are_owners_but_not_public(self) -> None:
        path = Path("app/src/main/kotlin/sample/Internals.kt")
        source = "package sample\n\ninternal fun buildAlpha() = 1\n"
        found = top_level_type_declarations(path, source.splitlines())

        self.assertEqual(["buildAlpha"], [item["name"] for item in found])
        self.assertTrue(found[0]["internal"])
        self.assertEqual([], top_level_declaration_failures(path, found))

    def test_expect_and_actual_kotlin_functions_count_as_public_owners(self) -> None:
        for modifier in ("expect", "actual"):
            with self.subTest(modifier=modifier):
                path = Path(f"app/src/{modifier}Main/kotlin/sample/Builders.kt")
                source = "\n".join(
                    f"{modifier} fun build{name}(): Unit"
                    for name in ("Alpha", "Bravo", "Charlie", "Delta", "Echo")
                )
                found = top_level_type_declarations(path, source.splitlines())

                self.assertEqual(
                    ["buildAlpha", "buildBravo", "buildCharlie", "buildDelta", "buildEcho"],
                    [item["name"] for item in found],
                )
                failures = top_level_declaration_failures(path, found)
                self.assertTrue(any("public/exported top-level owners" in item for item in failures))
                self.assertTrue(any("non-private top-level owners" in item for item in failures))


class KotlinMultiplatformOwnerTests(unittest.TestCase):
    """`expect`/`actual` are declaration modifiers, not a separate construct.

    The function pattern already listed them, so `expect fun` counted while
    `expect class` did not: a multiplatform file could declare any number of
    top-level classes and report zero owners, bypassing both budgets.
    """

    def _declare(self, keyword: str, name: str = "Widgets.kt"):
        source = "package a\n\n" + "\n\n".join(
            f"{keyword} class Widget{index}" for index in range(5)
        )
        path = Path(f"app/src/commonMain/kotlin/{name}")
        return path, top_level_type_declarations(path, source.splitlines())

    def test_expect_classes_count_as_owners(self) -> None:
        path, found = self._declare("expect")

        self.assertEqual(5, len(found))
        self.assertTrue(top_level_declaration_failures(path, found))

    def test_actual_classes_count_as_owners(self) -> None:
        path, found = self._declare("actual")

        self.assertEqual(5, len(found))
        self.assertTrue(top_level_declaration_failures(path, found))

    def test_expect_and_actual_functions_still_count(self) -> None:
        path = Path("app/src/commonMain/kotlin/Builders.kt")
        source = "package a\n\nexpect fun buildAlpha(): Int\n\nactual fun buildBravo(): Int = 2\n"
        found = top_level_type_declarations(path, source.splitlines())

        self.assertEqual(["buildAlpha", "buildBravo"], [item["name"] for item in found])

    def test_negative_control_private_multiplatform_classes_stay_unowned(self) -> None:
        """The control: widening the modifier list must not swallow `private`."""

        path = Path("app/src/commonMain/kotlin/Internals.kt")
        source = "package a\n\n" + "\n\n".join(
            f"private class Helper{index}" for index in range(5)
        )
        found = top_level_type_declarations(path, source.splitlines())

        self.assertEqual([], top_level_declaration_failures(path, found))


if __name__ == "__main__":
    unittest.main()
