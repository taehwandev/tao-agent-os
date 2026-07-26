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


if __name__ == "__main__":
    unittest.main()
