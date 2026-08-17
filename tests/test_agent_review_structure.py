from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_structure import (
    REVIEW_ADDED_LINE_LIMIT,
    REVIEW_TEST_ADDED_LINE_LIMIT,
    REVIEW_TEST_FILE_LINE_LIMIT,
    changed_source_paths,
    check_file_size,
    large_block_failures,
    large_block_findings,
    review_source_path,
    structure_review,
)
from agent_review_hook import structure_evidence_failures
from agent_structure_rules import structure_rule_review


class AgentReviewStructureTests(unittest.TestCase):
    def test_repair_ledger_declares_its_runtime_boundary(self) -> None:
        source = (ROOT / "scripts" / "agent_repair_ledger.py").read_text(encoding="utf-8")

        for anchor in (
            "Owner:",
            "Allowed imports:",
            "Forbidden imports:",
            "Callers/tests:",
            "Verification:",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, source)

    def test_new_runtime_boundary_evidence_requires_every_named_contract_field(self) -> None:
        structure = {
            "warnings": [],
            "boundary_note_requirements": [
                {"package": "src/domain", "reason": "new runtime package/folder"},
            ],
        }

        failures = structure_evidence_failures(
            structure,
            "owner=domain; callers/tests=app and domain tests",
        )

        self.assertEqual(1, len(failures))
        self.assertIn("allowed imports", failures[0])
        self.assertIn("forbidden imports", failures[0])
        self.assertIn("verification", failures[0])
        self.assertIn("Example: owner=", failures[0])
        self.assertIn("existing multi-role package", failures[0])
        self.assertIn("not only when the diff creates a new package boundary", failures[0])

        complete = structure_evidence_failures(
            structure,
            (
                "owner=domain; allowed imports=contracts; forbidden imports=ui; "
                "callers/tests=app and domain tests; verification=focused tests"
            ),
        )
        self.assertEqual([], complete)

    def test_pinned_third_party_source_is_outside_human_authored_size_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "scripts" / "third_party" / "engine" / "engine.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n", encoding="utf-8")
            (source.parent / "LICENSE").write_text("license\n", encoding="utf-8")
            (source.parent / "README.md").write_text(
                "Upstream: example\nCommit: abc\nSHA-256: 123\nLicense: MIT\n",
                encoding="utf-8",
            )

            self.assertFalse(review_source_path(project, source.relative_to(project)))

    def test_unprovenanced_third_party_source_stays_in_structure_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "scripts" / "third_party" / "engine" / "engine.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n", encoding="utf-8")

            self.assertTrue(review_source_path(project, source.relative_to(project)))

    def test_changed_source_paths_can_be_limited_to_review_pathspec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "src").mkdir()
            (project / "src" / "a.py").write_text("value = 1\n", encoding="utf-8")
            (project / "src" / "b.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            (project / "src" / "a.py").write_text("value = 2\n", encoding="utf-8")
            (project / "src" / "b.py").write_text("value = 2\n", encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            _discovery, paths = changed_source_paths(project, run_command, ["src/a.py"])

        self.assertEqual([Path("src/a.py")], paths)

    def test_changed_source_paths_can_read_an_exact_commit_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src" / "subject.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "base",
                ],
                cwd=project,
                check=True,
            )
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            source.write_text("value = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "head",
                ],
                cwd=project,
                check=True,
            )
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            source.write_text("value = 3\n", encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            discovery, paths = changed_source_paths(
                project,
                run_command,
                review_commits=(base, head),
            )

        self.assertEqual([Path("src/subject.py")], paths)
        self.assertEqual(1, discovery["path_metadata"]["src/subject.py"]["additions"])
        self.assertEqual(1, discovery["path_metadata"]["src/subject.py"]["deletions"])


    def test_non_git_structure_review_does_not_require_git_file_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src" / "feature.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            commands: list[list[str]] = []

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                commands.append(command)
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 128,
                    "stdout": "",
                    "stderr": "not a git repository",
                }

            review = structure_review(
                project,
                500,
                120,
                run_command,
                ["src/feature.py"],
            )

        self.assertEqual([], review["failures"])
        self.assertEqual([], review["checked_paths"])
        self.assertEqual("non_git_workspace", review["discovery"]["review_only"])
        self.assertEqual([["git", "rev-parse", "--verify", "HEAD"]], commands)

    def test_renamed_legacy_file_compares_owner_count_with_original_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src"
            source.mkdir()
            original = source / "ProposalEntry.kt"
            original.write_text(
                "data class ProposalEntry(val id: Long)\n"
                "data class Notice(val message: String)\n"
                "data class Metadata(val source: String)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            renamed = source / "ChattyEntry.kt"
            original.rename(renamed)
            renamed.write_text(
                "data class ChattyEntry(val id: Long)\n"
                "data class Notice(val message: String)\n"
                "data class Metadata(val source: String)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            review = structure_review(project, 500, 120, run_command, ["src"])

        self.assertEqual([], review["failures"])
        self.assertEqual(
            "src/ProposalEntry.kt",
            review["discovery"]["path_metadata"]["src/ChattyEntry.kt"]["previous_path"],
        )

    def test_unstaged_content_preserving_move_is_not_treated_as_new_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src"
            source.mkdir()
            original = source / "LegacyViewModel.kt"
            original.write_text(
                "package example\n\n" + "\n".join(f"// retained line {index}" for index in range(510)) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            moved = source / "session" / original.name
            moved.parent.mkdir()
            original.rename(moved)
            moved.write_text(
                "package example.session\n\n"
                + "\n".join(f"// retained line {index}" for index in range(510))
                + "\n",
                encoding="utf-8",
            )

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            discovery, paths = changed_source_paths(project, run_command, ["src"])

        metadata = discovery["path_metadata"]["src/session/LegacyViewModel.kt"]
        self.assertEqual([Path("src/session/LegacyViewModel.kt")], paths)
        self.assertEqual("R", metadata["status"])
        self.assertEqual("src/LegacyViewModel.kt", metadata["previous_path"])
        self.assertEqual(1, metadata["additions"])
        self.assertEqual(1, metadata["deletions"])

    def test_unstaged_content_preserving_copy_is_not_treated_as_new_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src"
            source.mkdir()
            original = source / "LegacyViewModel.kt"
            original.write_text(
                "package example\n\n" + "\n".join(f"// retained line {index}" for index in range(510)) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            copied = source / "contact" / original.name
            copied.parent.mkdir()
            copied.write_text(
                "package example.contact\n\n"
                + "\n".join(f"// retained line {index}" for index in range(510))
                + "\n",
                encoding="utf-8",
            )

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            review = structure_review(project, 500, 120, run_command, ["src/contact"])

        metadata = review["discovery"]["path_metadata"]["src/contact/LegacyViewModel.kt"]
        self.assertEqual([], review["failures"])
        self.assertEqual("C", metadata["status"])
        self.assertEqual("src/LegacyViewModel.kt", metadata["previous_path"])
        self.assertEqual(1, metadata["additions"])
        self.assertEqual(1, metadata["deletions"])
        self.assertTrue(
            any("content-preserving source copy" in warning for warning in review["warnings"])
        )

    def test_dissimilar_unstaged_same_name_file_remains_a_new_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src"
            source.mkdir()
            original = source / "LegacyViewModel.kt"
            original.write_text(
                "package example\n\n" + "\n".join(f"// original line {index}" for index in range(510)) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS Tests",
                    "-c",
                    "user.email=tao-agent@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            added = source / "contact" / original.name
            added.parent.mkdir()
            added.write_text(
                "package example.contact\n\n"
                + "\n".join(f"val unrelated{index} = {index}" for index in range(510))
                + "\n",
                encoding="utf-8",
            )

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            review = structure_review(project, 500, 120, run_command, ["src/contact"])

        metadata = review["discovery"]["path_metadata"]["src/contact/LegacyViewModel.kt"]
        self.assertEqual("A", metadata["status"])
        self.assertTrue(
            any("new development source/style file" in failure for failure in review["failures"])
        )

    def test_renamed_preexisting_oversized_block_uses_previous_path(self) -> None:
        lines = ["private fun handle() {"]
        lines.extend(f"    val value{index} = {index}" for index in range(120))
        lines.append("}")
        commands: list[list[str]] = []

        def run_command(command: list[str], _cwd: Path) -> dict[str, object]:
            commands.append(command)
            return {
                "returncode": 0,
                "stdout": "\n".join(lines),
                "stderr": "",
            }

        failures, warnings = large_block_findings(
            Path("."),
            Path("src/session/LegacyHandler.kt"),
            lines,
            120,
            {"status": "R", "previous_path": "src/LegacyHandler.kt"},
            run_command,
        )

        self.assertEqual([], failures)
        self.assertTrue(any("pre-existing oversized unit" in warning for warning in warnings))
        self.assertIn(["git", "show", "HEAD:src/LegacyHandler.kt"], commands)

    def test_existing_oversized_file_growth_requires_evidence_without_hard_failure(self) -> None:
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("src/messages.ts"),
            ["export const messages = {};"] * 501,
            500,
            {"status": "M", "additions": 33},
            result,
        )

        self.assertEqual([], result["failures"])
        self.assertTrue(any("already over 500 lines" in warning for warning in result["warnings"]))

    def test_changed_file_over_review_pressure_limit_requires_evidence(self) -> None:
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("src/workflow.ts"),
            ["export const value = 1;"] * 301,
            500,
            {"status": "M", "additions": 4},
            result,
        )

        self.assertEqual([], result["failures"])
        self.assertTrue(any("review-pressure limit is 300" in warning for warning in result["warnings"]))

    def test_net_reducing_rewrite_warns_instead_of_failing_addition_limit(self) -> None:
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("src/LegacyScreen.kt"),
            ["class LegacyScreen"] * 399,
            500,
            {"status": "M", "additions": 350, "deletions": 898},
            result,
        )

        self.assertEqual([], result["failures"])
        self.assertTrue(any("is not growing" in warning for warning in result["warnings"]))

    def test_per_file_addition_budget_allows_300_lines(self) -> None:
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("src/UploadWorker.kt"),
            ["private val value = 1"] * REVIEW_ADDED_LINE_LIMIT,
            500,
            {"status": "M", "additions": REVIEW_ADDED_LINE_LIMIT, "deletions": 0},
            result,
        )

        self.assertEqual([], result["failures"])

    def test_per_file_addition_budget_rejects_growth_over_300_lines(self) -> None:
        result = {"failures": [], "warnings": []}
        additions = REVIEW_ADDED_LINE_LIMIT + 1

        check_file_size(
            Path("src/UploadWorker.kt"),
            ["private val value = 1"] * additions,
            500,
            {"status": "M", "additions": additions, "deletions": 0},
            result,
        )

        self.assertTrue(
            any(
                f"per-file addition limit is {REVIEW_ADDED_LINE_LIMIT}" in failure
                for failure in result["failures"]
            )
        )

    def test_large_type_container_does_not_use_function_block_limit(self) -> None:
        lines = ["class MainActivity : AppCompatActivity() {"]
        lines.extend(f"    private val value{index} = {index}" for index in range(150))
        lines.append("}")

        self.assertEqual([], large_block_failures(Path("MainActivity.kt"), lines, 120))

    def test_large_function_still_uses_function_block_limit(self) -> None:
        lines = ["private fun handle() {"]
        lines.extend(f"    val value{index} = {index}" for index in range(150))
        lines.append("}")

        failures = large_block_failures(Path("DeepLinkHandler.kt"), lines, 120)

        self.assertTrue(any("private fun handle" in failure for failure in failures))
        self.assertTrue(any("prose alone does not bypass this hard gate" in failure for failure in failures))

    def test_preexisting_oversized_function_growth_still_fails(self) -> None:
        previous_lines = ["private fun handle() {"]
        previous_lines.extend(f"    val value{index} = {index}" for index in range(120))
        previous_lines.append("}")
        current_lines = previous_lines[:-1] + ["    val addedValue = true", "}"]

        failures, warnings = large_block_findings(
            Path("."),
            Path("LegacyHandler.kt"),
            current_lines,
            120,
            {"status": "M"},
            lambda _command, _cwd: {
                "returncode": 0,
                "stdout": "\n".join(previous_lines),
                "stderr": "",
            },
        )

        self.assertTrue(any("private fun handle" in failure for failure in failures))
        self.assertEqual([], warnings)

    def test_unchanged_preexisting_oversized_function_only_warns(self) -> None:
        lines = ["private fun handle() {"]
        lines.extend(f"    val value{index} = {index}" for index in range(120))
        lines.append("}")

        failures, warnings = large_block_findings(
            Path("."),
            Path("LegacyHandler.kt"),
            lines,
            120,
            {"status": "M"},
            lambda _command, _cwd: {
                "returncode": 0,
                "stdout": "\n".join(lines),
                "stderr": "",
            },
        )

        self.assertEqual([], failures)
        self.assertTrue(any("pre-existing oversized unit" in warning for warning in warnings))

    def test_new_oversized_file_still_fails(self) -> None:
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("src/newFeature.ts"),
            ["export const value = 1;"] * 501,
            500,
            {"status": "A", "additions": 501},
            result,
        )

        self.assertTrue(any("new development source/style file" in failure for failure in result["failures"]))

    def test_structure_rules_fail_for_forbidden_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".agents").mkdir()
            (project / ".agents" / "structure-rules.json").write_text(
                json.dumps({"forbidden_new_paths": ["**/utils/**"]}),
                encoding="utf-8",
            )
            source = project / "src" / "utils" / "userClient.ts"
            source.parent.mkdir(parents=True)
            source.write_text("export const userClient = {};\n", encoding="utf-8")

            result = structure_rule_review(
                project,
                [Path("src/utils/userClient.ts")],
                {"src/utils/userClient.ts": {"status": "A"}},
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertTrue(
            any(
                "forbidden" in failure and "src/utils/userClient.ts" in failure
                for failure in result["failures"]
            )
        )

    def test_structure_rules_apply_forbidden_new_path_to_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".agents").mkdir()
            (project / ".agents" / "structure-rules.json").write_text(
                json.dumps({"forbidden_new_paths": ["**/utils/**"]}),
                encoding="utf-8",
            )
            source = project / "src" / "utils" / "userClient.ts"
            source.parent.mkdir(parents=True)
            source.write_text("export const userClient = {};\n", encoding="utf-8")

            result = structure_rule_review(
                project,
                [Path("src/utils/userClient.ts")],
                {
                    "src/utils/userClient.ts": {
                        "status": "R",
                        "previous_path": "src/userClient.ts",
                    }
                },
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertTrue(
            any(
                "forbidden" in failure and "src/utils/userClient.ts" in failure
                for failure in result["failures"]
            )
        )

    def test_structure_rules_fail_for_forbidden_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".agents").mkdir()
            (project / ".agents" / "structure-rules.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "name": "domain_stays_out_of_ui",
                                "paths": ["src/domain/**"],
                                "forbidden_imports": ["src/ui/**"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = project / "src" / "domain" / "userPolicy.ts"
            source.parent.mkdir(parents=True)
            source.write_text("import { Button } from '../ui/button';\n", encoding="utf-8")

            result = structure_rule_review(
                project,
                [Path("src/domain/userPolicy.ts")],
                {"src/domain/userPolicy.ts": {"status": "M"}},
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertTrue(
            any(
                "forbidden by" in failure and "src/ui" in failure
                for failure in result["failures"]
            )
        )

    def test_structure_rules_fail_when_new_path_misses_allowed_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".agents").mkdir()
            (project / ".agents" / "structure-rules.json").write_text(
                json.dumps({"allowed_new_paths": ["src/features/**", "src/domain/**"]}),
                encoding="utf-8",
            )
            source = project / "src" / "platform" / "bridge.ts"
            source.parent.mkdir(parents=True)
            source.write_text("export const bridge = {};\n", encoding="utf-8")

            result = structure_rule_review(
                project,
                [Path("src/platform/bridge.ts")],
                {"src/platform/bridge.ts": {"status": "A"}},
                lambda root, path: (root / path).suffix == ".ts" and (root / path).exists(),
                lambda path: False,
            )

        self.assertTrue(any("allowed_new_paths" in failure for failure in result["failures"]))

    def test_new_oversized_test_file_fails_against_the_wider_test_budget(self) -> None:
        # Regression: test_exempt_path files used to skip check_file_size
        # entirely, so a single test file could grow to thousands of lines
        # with no gate ever flagging it (a real one reached 6,484 lines).
        # Tests get a wider budget than production files, not an unbounded one.
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("tests/test_something.py"),
            ["x"] * (REVIEW_TEST_FILE_LINE_LIMIT + 1),
            REVIEW_TEST_FILE_LINE_LIMIT,
            {"status": "A", "additions": REVIEW_TEST_FILE_LINE_LIMIT + 1},
            result,
            max_added_lines=REVIEW_TEST_ADDED_LINE_LIMIT,
        )

        self.assertTrue(
            any(f"new-file hard limit is {REVIEW_TEST_FILE_LINE_LIMIT}" in failure for failure in result["failures"])
        )

    def test_test_file_budget_is_wider_than_the_source_file_budget(self) -> None:
        # A file just over the 500-line source limit must not fail as a test
        # file -- that is exactly the wider-budget-not-unbounded distinction.
        result = {"failures": [], "warnings": []}

        check_file_size(
            Path("tests/test_something.py"),
            ["x"] * 501,
            REVIEW_TEST_FILE_LINE_LIMIT,
            {"status": "A", "additions": 501},
            result,
            max_added_lines=REVIEW_TEST_ADDED_LINE_LIMIT,
        )

        self.assertEqual([], result["failures"])

    def test_structure_review_flags_a_new_oversized_test_file(self) -> None:
        oversized_lines = "\n".join(f"    value_{index} = {index}" for index in range(REVIEW_TEST_FILE_LINE_LIMIT))
        test_text = "def test_example():\n" + oversized_lines + "\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "tests").mkdir()
            source = project / "tests" / "test_oversized.py"
            source.write_text(test_text, encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "A\ttests/test_oversized.py\n"
                elif command[:3] == ["git", "diff", "--numstat"]:
                    line_count = len(test_text.splitlines())
                    stdout = f"{line_count}\t0\ttests/test_oversized.py\n"
                elif command[:2] == ["git", "ls-files"]:
                    stdout = ""
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            result = structure_review(project, 500, 120, run_command)

        self.assertIn("tests/test_oversized.py", result["test_exempt_paths"])
        self.assertTrue(
            any("tests/test_oversized.py is a new development source" in failure for failure in result["failures"])
        )

    def test_structure_review_flags_new_source_file_sprawl_and_requires_evidence(self) -> None:
        # A small task spread across many new files must be justified: the
        # structure review warns, and the review gate turns that warning into a
        # required-evidence failure when no structure-review evidence is given.
        added_files = [f"src/layer{index}/thing{index}.py" for index in range(6)]

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            for relative in added_files:
                source = project / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("value = 1\n", encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "".join(f"A\t{relative}\n" for relative in added_files)
                elif command[:3] == ["git", "diff", "--numstat"]:
                    stdout = "".join(f"1\t0\t{relative}\n" for relative in added_files)
                elif command[:2] == ["git", "ls-files"]:
                    stdout = ""
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            result = structure_review(project, 500, 120, run_command)

        self.assertEqual(6, result["new_source_file_count"])
        self.assertTrue(
            any("6 new development source files" in warning for warning in result["warnings"])
        )
        # Missing structure-review evidence must escalate the warning to a failure.
        self.assertTrue(structure_evidence_failures(result, ""))
        # A justification clears the gate.
        self.assertEqual(
            [],
            structure_evidence_failures(
                result,
                "each new file owns a distinct platform adapter required by the change",
            ),
        )

    def test_structure_review_allows_a_few_new_source_files(self) -> None:
        added_files = ["src/feature/model.py", "src/feature/service.py"]

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            for relative in added_files:
                source = project / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("value = 1\n", encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "".join(f"A\t{relative}\n" for relative in added_files)
                elif command[:3] == ["git", "diff", "--numstat"]:
                    stdout = "".join(f"1\t0\t{relative}\n" for relative in added_files)
                elif command[:2] == ["git", "ls-files"]:
                    stdout = ""
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            result = structure_review(project, 500, 120, run_command)

        self.assertEqual(2, result["new_source_file_count"])
        self.assertFalse(
            any("new development source files" in warning for warning in result["warnings"])
        )

    def test_structure_review_does_not_run_oversized_block_check_on_test_files(self) -> None:
        # Tests remain exempt from the per-block/function span check -- a long
        # setup or scenario method is a normal test shape, unlike a long
        # production function.
        oversized_lines = "\n".join(f"    value_{index} = {index}" for index in range(200))
        test_text = "def test_example():\n" + oversized_lines + "\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "tests").mkdir()
            source = project / "tests" / "test_long_block.py"
            source.write_text(test_text, encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "A\ttests/test_long_block.py\n"
                elif command[:3] == ["git", "diff", "--numstat"]:
                    line_count = len(test_text.splitlines())
                    stdout = f"{line_count}\t0\ttests/test_long_block.py\n"
                elif command[:2] == ["git", "ls-files"]:
                    stdout = ""
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            result = structure_review(project, 500, 120, run_command)

        self.assertFalse(any("block `test_example` spans" in failure for failure in result["failures"]))


class NumstatDeletionAccountingTests(unittest.TestCase):
    """`check_file_size` downgrades a net-reducing rewrite to a warning.

    That branch reads `metadata["deletions"]`, which only the numstat discovery
    pass can supply. While the parser recorded additions alone the key was
    always absent, so the branch was unreachable through the real review path
    and a shrinking file was failed for its addition count.
    """

    def _collect(
        self,
        numstat_stdout: str,
        name_status_stdout: str = "M\tbig.py\n",
    ) -> dict[str, dict[str, object]]:
        from agent_review_structure import collect_head_diff

        def run_command(command, project):
            if "--name-status" in command:
                return {"returncode": 0, "stdout": name_status_stdout, "stderr": ""}
            if "--numstat" in command:
                self.assertIn("-z", command)
                return {"returncode": 0, "stdout": numstat_stdout, "stderr": ""}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        metadata: dict[str, dict[str, object]] = {}
        collect_head_diff(Path("."), run_command, {}, set(), metadata, [])
        return metadata

    def test_numstat_discovery_records_deleted_lines(self) -> None:
        metadata = self._collect("900\t1500\tbig.py\0")

        self.assertEqual(900, metadata["big.py"]["additions"])
        self.assertEqual(1500, metadata["big.py"]["deletions"])

    def test_net_reducing_rewrite_warns_instead_of_failing(self) -> None:
        metadata = self._collect("900\t1500\tbig.py\0")
        result: dict[str, list[str]] = {"failures": [], "warnings": []}

        check_file_size(Path("big.py"), ["line"] * 200, 500, metadata["big.py"], result)

        self.assertEqual([], result["failures"])
        self.assertTrue(any("is not growing" in warning for warning in result["warnings"]))

    def test_negative_control_growing_file_still_fails(self) -> None:
        """The control: a file that really grows must keep failing.

        If recording deletions had turned the addition limit into a no-op, this
        assertion would break instead of the fix silently disabling the gate.
        """

        metadata = self._collect("900\t10\tbig.py\0")
        result: dict[str, list[str]] = {"failures": [], "warnings": []}

        check_file_size(Path("big.py"), ["line"] * 200, 500, metadata["big.py"], result)

        self.assertEqual([], result["warnings"])
        self.assertTrue(
            any(
                f"per-file addition limit is {REVIEW_ADDED_LINE_LIMIT}" in failure
                for failure in result["failures"]
            )
        )

    def test_binary_numstat_markers_do_not_crash_discovery(self) -> None:
        metadata = self._collect("-\t-\tbig.py\0")

        self.assertEqual(0, metadata["big.py"]["additions"])
        self.assertEqual(0, metadata["big.py"]["deletions"])

    def test_rename_numstat_counts_bind_to_destination_path(self) -> None:
        metadata = self._collect(
            "900\t1500\t\0old/big.py\0new/big.py\0",
            "R087\told/big.py\tnew/big.py\n",
        )

        self.assertEqual(
            {
                "status": "R",
                "previous_path": "old/big.py",
                "additions": 900,
                "deletions": 1500,
            },
            metadata["new/big.py"],
        )
        self.assertNotIn("{old => new}/big.py", metadata)

    def test_copy_numstat_counts_bind_to_destination_path(self) -> None:
        metadata = self._collect(
            "12\t3\t\0old/source.py\0new/copy.py\0",
            "C075\told/source.py\tnew/copy.py\n",
        )

        self.assertEqual(
            {
                "status": "C",
                "previous_path": "old/source.py",
                "additions": 12,
                "deletions": 3,
            },
            metadata["new/copy.py"],
        )


class NameStatusNulSafetyTests(unittest.TestCase):
    """A tab or newline in a path must not corrupt changed-file discovery.

    `--name-status` was split on tabs, so a path containing one kept only the
    fragment after the last tab. `--numstat` already parsed the real path, so
    the two passes disagreed and discovery invented a file that does not exist
    while the real one lost its status.
    """

    TAB_PATH = "src/we\tird.py"

    @staticmethod
    def _collect(name_status: str, numstat: str = "") -> dict:
        from agent_review_structure import collect_head_diff

        def run_command(command, project):
            if "--name-status" in command:
                return {"returncode": 0, "stdout": name_status, "stderr": ""}
            if "--numstat" in command:
                return {"returncode": 0, "stdout": numstat, "stderr": ""}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        metadata: dict = {}
        collect_head_diff(Path("."), run_command, {}, set(), metadata, [])
        return metadata

    def test_name_status_requests_nul_separated_output(self) -> None:
        from agent_review_structure import collect_head_diff

        commands: list[list[str]] = []

        def run_command(command, project):
            commands.append(command)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        collect_head_diff(Path("."), run_command, {}, set(), {}, [])

        name_status = next(c for c in commands if "--name-status" in c)
        self.assertIn("-z", name_status)

    def test_tab_in_path_keeps_one_correct_entry(self) -> None:
        metadata = self._collect(
            f"M\0{self.TAB_PATH}\0",
            f"5\t2\t{self.TAB_PATH}\0",
        )

        self.assertEqual([self.TAB_PATH], list(metadata))
        self.assertEqual("M", metadata[self.TAB_PATH]["status"])
        self.assertEqual(5, metadata[self.TAB_PATH]["additions"])
        self.assertEqual(2, metadata[self.TAB_PATH]["deletions"])

    def test_newline_in_path_does_not_split_the_record(self) -> None:
        newline_path = "src/we\nird.py"
        metadata = self._collect(f"M\0{newline_path}\0")

        self.assertEqual([newline_path], list(metadata))

    def test_rename_with_separator_characters_keeps_both_paths(self) -> None:
        metadata = self._collect("R100\0old\tname.py\0new\tname.py\0")

        self.assertEqual(["new\tname.py"], list(metadata))
        self.assertEqual("old\tname.py", metadata["new\tname.py"]["previous_path"])

    def test_negative_control_ordinary_paths_are_unaffected(self) -> None:
        """The control: NUL parsing must still handle the common case.

        If it broke plain paths, every review would lose its changed-file set.
        """

        metadata = self._collect(
            "M\0src/plain.py\0A\0src/added.py\0",
            "3\t1\tsrc/plain.py\0",
        )

        self.assertEqual(["src/added.py", "src/plain.py"], sorted(metadata))
        self.assertEqual("A", metadata["src/added.py"]["status"])
        self.assertEqual(3, metadata["src/plain.py"]["additions"])

    def test_line_oriented_output_still_parses_for_injected_runners(self) -> None:
        metadata = self._collect("M\tsrc/plain.py\n", "3\t1\tsrc/plain.py\n")

        self.assertEqual("M", metadata["src/plain.py"]["status"])
        self.assertEqual(3, metadata["src/plain.py"]["additions"])


class ListedPathNulSafetyTests(unittest.TestCase):
    """`git ls-files`/`--name-only` discovery must survive a path separator.

    Git quotes any path containing a newline or other special character unless
    `-z` is passed, so `we<newline>ird.py` arrived as the literal text
    `"we\\nird.py"`. Discovery recorded that quoted string and the real file was
    never reviewed at all, which is the one outcome this gate exists to prevent.
    These run against a real repository because the defect lives in git's output
    encoding, not in the parser alone.
    """

    NEWLINE_NAME = "we\nird.py"
    TAB_NAME = "we\tird.py"

    @staticmethod
    def _run_command(command: list[str], cwd: Path) -> dict[str, object]:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return {
            "command": command,
            "cwd": str(cwd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    @classmethod
    def _git(cls, project: Path, *args: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Tao Agent OS Tests",
                "-c",
                "user.email=tao-agent@example.invalid",
                *args,
            ],
            cwd=project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @classmethod
    def _initial_repository(cls, project: Path) -> None:
        (project / "src").mkdir()
        (project / "src" / "base.py").write_text("value = 1\n", encoding="utf-8")
        cls._git(project, "init")
        cls._git(project, "add", "-A")
        cls._git(project, "commit", "-m", "initial")

    def _discover_untracked(self, filename: str) -> tuple[dict, list[Path]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._initial_repository(project)
            (project / "src" / filename).write_text("value = 2\n", encoding="utf-8")

            return changed_source_paths(project, self._run_command)

    def test_newline_path_is_discovered_with_its_real_name(self) -> None:
        discovery, checked = self._discover_untracked(self.NEWLINE_NAME)

        expected = f"src/{self.NEWLINE_NAME}"
        self.assertIn(expected, discovery["path_metadata"])
        self.assertEqual([Path(expected)], checked)

    def test_tab_path_is_discovered_with_its_real_name(self) -> None:
        discovery, checked = self._discover_untracked(self.TAB_NAME)

        expected = f"src/{self.TAB_NAME}"
        self.assertIn(expected, discovery["path_metadata"])
        self.assertEqual([Path(expected)], checked)

    def test_no_quoted_phantom_path_is_recorded(self) -> None:
        """The negative control: reverting `-z` reinstates the quoted phantom.

        Without the fix `path_metadata` holds `"src/we\\nird.py"` -- quotes and a
        two-character backslash-n -- and `checked` is empty.
        """

        discovery, checked = self._discover_untracked(self.NEWLINE_NAME)

        self.assertEqual([], [name for name in discovery["path_metadata"] if '"' in name])
        self.assertNotEqual([], checked)

    def test_initial_commit_discovery_keeps_a_newline_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "src").mkdir()
            (project / "src" / self.NEWLINE_NAME).write_text("value = 1\n", encoding="utf-8")
            self._git(project, "init")

            discovery, checked = changed_source_paths(project, self._run_command)

        expected = f"src/{self.NEWLINE_NAME}"
        self.assertIn(expected, discovery["path_metadata"])
        self.assertEqual([Path(expected)], checked)

    def test_unstaged_move_of_a_newline_path_is_still_recognized(self) -> None:
        """Covers the deleted-path listing that feeds move reclassification."""

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "src").mkdir()
            body = "".join(f"value_{index} = {index}\n" for index in range(20))
            (project / "src" / self.NEWLINE_NAME).write_text(body, encoding="utf-8")
            self._git(project, "init")
            self._git(project, "add", "-A")
            self._git(project, "commit", "-m", "initial")

            (project / "lib").mkdir()
            (project / "lib" / self.NEWLINE_NAME).write_text(body, encoding="utf-8")
            (project / "src" / self.NEWLINE_NAME).unlink()

            discovery, _checked = changed_source_paths(project, self._run_command)

        moved = discovery["path_metadata"][f"lib/{self.NEWLINE_NAME}"]
        self.assertEqual("R", moved["status"])
        self.assertEqual(f"src/{self.NEWLINE_NAME}", moved["previous_path"])

    def test_ordinary_paths_are_still_discovered(self) -> None:
        """The opposite-direction control: NUL parsing must not lose plain paths.

        If it did, every review would silently run against an empty file set.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._initial_repository(project)
            (project / "src" / "base.py").write_text("value = 3\n", encoding="utf-8")
            (project / "src" / "added.py").write_text("value = 4\n", encoding="utf-8")

            discovery, checked = changed_source_paths(project, self._run_command)

        self.assertEqual([Path("src/added.py"), Path("src/base.py")], checked)
        self.assertEqual("M", discovery["path_metadata"]["src/base.py"]["status"])
        self.assertEqual("A", discovery["path_metadata"]["src/added.py"]["status"])

    def test_discovery_commands_request_nul_separated_listings(self) -> None:
        commands: list[list[str]] = []

        def run_command(command: list[str], project: Path) -> dict[str, object]:
            commands.append(command)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        changed_source_paths(Path("."), run_command)

        for marker in ("--others", "--name-only"):
            with self.subTest(marker=marker):
                listing = next(command for command in commands if marker in command)
                self.assertIn("-z", listing)

    def test_line_oriented_listings_still_parse_for_injected_runners(self) -> None:
        from agent_review_structure import _listed_paths

        self.assertEqual(
            ["src/a.py", "src/b.py"],
            _listed_paths("src/a.py\nsrc/b.py\n"),
        )

    def _addition_review(self, added: int, **kwargs: object) -> dict[str, object]:
        """Review one modified source file that adds `added` lines."""

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            source = project / "src" / "adapter.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("value = 1\n" * added, encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    stdout = "abc\n"
                elif command[:3] == ["git", "diff", "--name-status"]:
                    stdout = "M\tsrc/adapter.py\n"
                elif command[:3] == ["git", "diff", "--numstat"]:
                    stdout = f"{added}\t0\tsrc/adapter.py\n"
                else:
                    stdout = ""
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": stdout,
                    "stderr": "",
                }

            return structure_review(project, 5000, 120, run_command, **kwargs)

    def test_default_addition_limit_still_fails_an_oversized_addition(self) -> None:
        result = self._addition_review(REVIEW_ADDED_LINE_LIMIT + 1)

        self.assertEqual(REVIEW_ADDED_LINE_LIMIT, result["max_added_lines"])
        self.assertTrue(
            any("per-file addition limit" in failure for failure in result["failures"])
        )

    def test_raised_addition_limit_allows_an_unsplittable_single_file_artifact(self) -> None:
        # A source file distributed and installed as a single standalone artifact
        # cannot be split, so the reviewer may raise the limit for that run.
        result = self._addition_review(REVIEW_ADDED_LINE_LIMIT + 1, max_added_lines=600)

        self.assertEqual(600, result["max_added_lines"])
        self.assertEqual([], [f for f in result["failures"] if "addition limit" in f])

    def test_raised_addition_limit_still_fails_past_the_raised_value(self) -> None:
        result = self._addition_review(601, max_added_lines=600)

        self.assertTrue(
            any("per-file addition limit is 600" in failure for failure in result["failures"])
        )

    def test_raised_addition_limit_scales_the_test_file_budget(self) -> None:
        from agent_review_structure import REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER

        result = self._addition_review(1, max_added_lines=600)

        self.assertEqual(
            600 * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER,
            result["test_max_added_lines"],
        )


if __name__ == "__main__":
    unittest.main()
