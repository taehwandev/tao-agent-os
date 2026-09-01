from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_hook import (
    clean_repo_hygiene_review,
    clean_restored_pathspec_review,
    clean_task_setup_pathspec_review,
    resolve_commit_range_subject,
    review_hook,
)
from agent_review_attestation import ReviewAttestation


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


def commit(project: Path, message: str) -> str:
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
            message,
        ],
        cwd=project,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


class ReviewScopeGuardTests(unittest.TestCase):
    def test_clean_restored_pathspec_accepts_preflight_dirty_path_for_writing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"surface_candidates":{"dirty_paths":["subject.py"]},'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"local_write"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                project=project,
                evidence=evidence,
                review_scope="pathspec",
            )

            self.assertTrue(
                clean_restored_pathspec_review(
                    args,
                    {"kind": "working-tree"},
                    ["subject.py"],
                )
            )

    def test_clean_restored_pathspec_rejects_unbound_or_non_writing_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            evidence = project / "preflight.json"
            args = SimpleNamespace(
                project=project,
                evidence=evidence,
                review_scope="pathspec",
            )
            payloads = (
                '{"route":{"surface_candidates":{"dirty_paths":["other.py"]},'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"local_write"}}}}',
                '{"route":{"surface_candidates":{"dirty_paths":["subject.py"]},'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"read"}}}}',
                '{"route":{"surface_candidates":{"dirty_paths":["subject.py"]},'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"local_write"}}},'
                '"execution_mode":{"read_only":true}}',
            )

            for payload in payloads:
                with self.subTest(payload=payload):
                    evidence.write_text(payload, encoding="utf-8")
                    self.assertFalse(
                        clean_restored_pathspec_review(
                            args,
                            {"kind": "working-tree"},
                            ["subject.py"],
                        )
                    )

    def test_clean_restored_pathspec_runs_review_without_a_current_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            commit(project, "base")
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"surface_candidates":{"dirty_paths":["subject.py"]},'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"local_write"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            output: dict[str, object] = {}
            args = SimpleNamespace(
                project=project,
                rules=ROOT,
                evidence=evidence,
                review_path=["subject.py"],
                review_scope="pathspec",
                review_base="",
                review_head="",
                review_outcome="pass",
                code_review_evidence="reviewed the exact restored path",
                docs_freshness_evidence="review guidance covers the restored path scope",
                structure_review_evidence="",
                boundary_plan_evidence="owned only the restored subject.py path",
                side_effect_audit_evidence="confirmed the restored path and checkout are clean",
                allow_vibeguard_review="",
                max_changed_paths=25,
                max_source_file_lines=500,
                max_function_lines=120,
                max_added_lines=300,
                output=None,
                repair_cycle=0,
            )

            def clean_status(_project: Path) -> tuple[dict[str, object], list[str]]:
                return {"returncode": 0, "stdout": "", "stderr": ""}, []

            def finish_with_result(
                _name: str,
                success: bool,
                _details: list[str],
                _output: Path | None,
                payload: dict[str, object],
                _repair_cycle: int,
                **_kwargs: object,
            ) -> int:
                output.update(success=success, payload=payload)
                return 0 if success else 1

            structure = {
                "checked_path_count": 0,
                "scope": "pathspec",
                "warnings": [],
                "failures": [],
                "boundary_note_requirements": [],
                "net_deletions": [],
            }

            with (
                patch("agent_review_hook.record_review_prerequisite_readiness"),
                patch("agent_review_hook.record_review_input_evidence"),
                patch("agent_review_hook.structure_review", return_value=structure),
                patch("agent_review_hook.record_review_base_drift"),
                patch("agent_review_hook.record_review_worktree_stability"),
                patch("agent_review_hook.record_review_workflow_validation") as validation,
                patch("agent_review_hook.record_review_vibeguard") as vibeguard,
                patch("agent_review_hook.record_successful_review_workflow_validation"),
                patch("agent_review_hook.record_review_gate"),
            ):
                validation.side_effect = lambda _args, checks, _failures: checks.update(
                    workflow_validate={"returncode": 0}
                )
                vibeguard.side_effect = lambda _args, _runner, _command, _parser, _paths, checks, _failures, **_kwargs: checks.update(
                    vibeguard={"returncode": 0, "overall": "Ready"}
                )
                result = review_hook(
                    args,
                    lambda _command, _cwd: {"returncode": 0, "stdout": "", "stderr": ""},
                    clean_status,
                    lambda _project, _rules: ["vibeguard", "audit", "."],
                    lambda output: "Ready" if "Ready" in output else "unknown",
                    finish_with_result,
                )

        self.assertEqual(0, result)
        self.assertTrue(output["success"])
        payload = output["payload"]
        self.assertEqual(0, payload["changed_path_count"])
        self.assertTrue(payload["clean_restoration_scope"]["accepted"])

    def test_repo_hygiene_scope_accepts_destructive_branch_or_worktree_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"concerns":["branch","worktree"],'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"destructive"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evidence=evidence,
                review_scope="repo-hygiene",
            )

            self.assertTrue(
                clean_repo_hygiene_review(args, {"kind": "working-tree"}, [])
            )

    def test_repo_hygiene_scope_accepts_destructive_project_state_cleanup(self) -> None:
        """Clearing the run store produces the same clean checkout.

        The store is Git-ignored, so the whole result of the work is what is
        no longer there. Admitting only branch and worktree concerns let such
        a task be started and performed but never closed, which refuses the
        only outcome it can produce rather than an unsafe one.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"concerns":["state"],'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"destructive"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evidence=evidence,
                review_scope="repo-hygiene",
            )

            self.assertTrue(
                clean_repo_hygiene_review(args, {"kind": "working-tree"}, [])
            )

    def test_repo_hygiene_scope_still_requires_a_destructive_state_task(self) -> None:
        """The concern widens what may be attested, never why."""

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"concerns":["state"],'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"local_write"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evidence=evidence,
                review_scope="repo-hygiene",
            )

            self.assertFalse(
                clean_repo_hygiene_review(args, {"kind": "working-tree"}, [])
            )

    def test_repo_hygiene_scope_rejects_non_destructive_or_unrelated_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / "preflight.json"
            args = SimpleNamespace(
                evidence=evidence,
                review_scope="repo-hygiene",
            )
            for payload in (
                '{"route":{"concerns":["branch"],"request_classification":'
                '{"intent_envelope":{"effective_effect":"git_write"}}}}\n',
                '{"route":{"concerns":["module"],"request_classification":'
                '{"intent_envelope":{"effective_effect":"destructive"}}}}\n',
            ):
                evidence.write_text(payload, encoding="utf-8")
                self.assertFalse(
                    clean_repo_hygiene_review(args, {"kind": "working-tree"}, [])
                )

    def test_repo_hygiene_scope_runs_clean_review_without_a_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            (project / "tracked.txt").write_text("base\n", encoding="utf-8")
            commit(project, "base")
            evidence = project / ".tao/preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                '{"route":{"concerns":["branch","worktree"],'
                '"request_classification":{"intent_envelope":'
                '{"effective_effect":"destructive"}}},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            outputs: list[dict[str, object]] = []

            def git_status(path: Path) -> tuple[dict[str, object], list[str]]:
                result = run_command(
                    ["git", "status", "--short", "--untracked-files=all"],
                    path,
                )
                return result, [line for line in str(result["stdout"]).splitlines() if line]

            def finish_with_result(
                name: str,
                success: bool,
                details: list[str],
                output: Path | None,
                payload: dict[str, object],
                repair_cycle: int,
                invocation_error: bool = False,
            ) -> int:
                outputs.append(
                    {
                        "name": name,
                        "success": success,
                        "details": details,
                        "payload": payload,
                        "invocation_error": invocation_error,
                    }
                )
                return 0 if success else 1

            args = SimpleNamespace(
                project=project,
                rules=ROOT,
                evidence=evidence,
                review_path=[],
                review_scope="repo-hygiene",
                review_base="",
                review_head="",
                review_outcome="pass",
                code_review_evidence="reviewed the exact branch and worktree post-state",
                docs_freshness_evidence="repo-hygiene guidance matches the executable scope",
                structure_review_evidence="",
                boundary_plan_evidence="owned only branch and worktree cleanup state",
                side_effect_audit_evidence="re-read worktrees and branches; checkout remained clean",
                allow_vibeguard_review="",
                max_changed_paths=25,
                max_source_file_lines=500,
                max_function_lines=120,
                max_added_lines=300,
                output=None,
                repair_cycle=0,
            )

            def successful_validation(
                _args: object,
                checks: dict[str, object],
                _failures: list[str],
            ) -> None:
                checks["workflow_validate"] = {"returncode": 0}

            def successful_vibeguard(
                _args: object,
                _runner: object,
                _command: object,
                _parser: object,
                paths: object,
                checks: dict[str, object],
                _failures: list[str],
                audit_project: Path | None = None,
            ) -> None:
                self.assertEqual([], paths)
                checks["vibeguard"] = {"returncode": 0, "overall": "Ready"}

            with (
                patch("agent_review_hook.record_review_prerequisite_readiness"),
                patch(
                    "agent_review_hook.record_review_workflow_validation",
                    side_effect=successful_validation,
                ),
                patch(
                    "agent_review_hook.record_review_vibeguard",
                    side_effect=successful_vibeguard,
                ),
                patch("agent_review_hook.record_successful_review_workflow_validation"),
                patch("agent_review_hook.record_review_gate"),
            ):
                result = review_hook(
                    args,
                    run_command,
                    git_status,
                    lambda _project, _rules: ["vibeguard", "audit", "."],
                    lambda output: "Ready" if "Ready" in output else "unknown",
                    finish_with_result,
                )

        self.assertEqual(0, result)
        self.assertTrue(outputs[0]["success"])
        payload = outputs[0]["payload"]
        self.assertEqual(0, payload["changed_path_count"])
        self.assertTrue(payload["repo_hygiene_clean_scope"]["accepted"])

    def test_clean_task_setup_pathspec_accepts_bound_task_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            policy = project / ".agents/shared/llm-skills/task/SKILL.md"
            policy.parent.mkdir(parents=True)
            policy.write_text("# Task\n", encoding="utf-8")
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"command":"task","request_classification":'
                '{"intent_envelope":{"effective_effect":"external_write"}}}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                project=project,
                evidence=evidence,
                review_scope="pathspec",
            )

            self.assertTrue(
                clean_task_setup_pathspec_review(
                    args,
                    {"kind": "working-tree"},
                    [".agents/shared/llm-skills/task/SKILL.md"],
                )
            )

    def test_clean_task_setup_pathspec_rejects_non_task_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            policy = project / ".agents/shared/llm-skills/task/SKILL.md"
            policy.parent.mkdir(parents=True)
            policy.write_text("# Task\n", encoding="utf-8")
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"route":{"command":"feature","request_classification":'
                '{"intent_envelope":{"effective_effect":"external_write"}}}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                project=project,
                evidence=evidence,
                review_scope="pathspec",
            )

            self.assertFalse(
                clean_task_setup_pathspec_review(
                    args,
                    {"kind": "working-tree"},
                    [".agents/shared/llm-skills/task/SKILL.md"],
                )
            )

    def test_clean_read_only_pathspec_runs_inspection_checks_without_a_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            commit(project, "base")
            evidence = project / "preflight.json"
            evidence.write_text(
                '{"execution_mode":{"read_only":true}}\n',
                encoding="utf-8",
            )
            outputs: list[dict[str, object]] = []

            def git_status(path: Path) -> tuple[dict[str, object], list[str]]:
                result = run_command(
                    ["git", "status", "--short", "--untracked-files=all"],
                    path,
                )
                return result, [line for line in str(result["stdout"]).splitlines() if line]

            def finish_with_result(
                name: str,
                success: bool,
                details: list[str],
                output: Path | None,
                payload: dict[str, object],
                repair_cycle: int,
                invocation_error: bool = False,
            ) -> int:
                outputs.append(
                    {
                        "name": name,
                        "success": success,
                        "details": details,
                        "payload": payload,
                        "invocation_error": invocation_error,
                    }
                )
                return 0 if success else 1

            args = SimpleNamespace(
                project=project,
                rules=ROOT,
                evidence=evidence,
                review_path=["subject.py"],
                review_scope="pathspec",
                review_base="",
                review_head="",
                review_outcome="pass",
                code_review_evidence="inspected the explicit read-only source path",
                docs_freshness_evidence="docs unchanged after inspecting the source path",
                structure_review_evidence="",
                boundary_plan_evidence="owned read-only subject.py inspection and verification",
                side_effect_audit_evidence="checked the clean diff and found no side effects",
                allow_vibeguard_review="",
                max_changed_paths=25,
                max_source_file_lines=500,
                max_function_lines=120,
                max_added_lines=300,
                output=None,
                repair_cycle=0,
            )

            def successful_validation(
                _args: object,
                checks: dict[str, object],
                _failures: list[str],
            ) -> None:
                checks["workflow_validate"] = {"returncode": 0}

            def successful_vibeguard(
                _args: object,
                _runner: object,
                _command: object,
                _parser: object,
                _paths: object,
                checks: dict[str, object],
                _failures: list[str],
                audit_project: Path | None = None,
            ) -> None:
                checks["vibeguard"] = {"returncode": 0, "overall": "Ready"}

            with (
                patch("agent_review_hook.record_review_prerequisite_readiness"),
                patch(
                    "agent_review_hook.record_review_workflow_validation",
                    side_effect=successful_validation,
                ),
                patch(
                    "agent_review_hook.record_review_vibeguard",
                    side_effect=successful_vibeguard,
                ),
                patch("agent_review_hook.record_successful_review_workflow_validation"),
                patch("agent_review_hook.record_review_gate"),
            ):
                result = review_hook(
                    args,
                    run_command,
                    git_status,
                    lambda _project, _rules: ["vibeguard", "audit", "."],
                    lambda output: "Ready" if "Ready" in output else "unknown",
                    finish_with_result,
                )

        self.assertEqual(0, result)
        self.assertTrue(outputs[0]["success"])
        payload = outputs[0]["payload"]
        self.assertEqual(0, payload["changed_path_count"])
        self.assertTrue(payload["read_only_clean_scope"]["accepted"])

    def test_local_config_scope_reviews_ignored_agent_config_without_a_git_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            (project / ".gitignore").write_text(
                ".tao/\n.codex/\n",
                encoding="utf-8",
            )
            (project / "tracked.txt").write_text("base\n", encoding="utf-8")
            commit(project, "base")
            config = project / ".codex/hooks.json"
            config.parent.mkdir(parents=True)
            config.write_text('{"hooks": {}}\n', encoding="utf-8")
            evidence = project / ".tao/preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                '{"route":{"command":"workflow-setup"},'
                '"execution_mode":{"read_only":false}}\n',
                encoding="utf-8",
            )
            outputs: list[dict[str, object]] = []

            def git_status(path: Path) -> tuple[dict[str, object], list[str]]:
                result = run_command(
                    ["git", "status", "--short", "--untracked-files=all"],
                    path,
                )
                return result, [line for line in str(result["stdout"]).splitlines() if line]

            def finish_with_result(
                name: str,
                success: bool,
                details: list[str],
                output: Path | None,
                payload: dict[str, object],
                repair_cycle: int,
                invocation_error: bool = False,
            ) -> int:
                outputs.append(
                    {
                        "name": name,
                        "success": success,
                        "details": details,
                        "payload": payload,
                        "invocation_error": invocation_error,
                    }
                )
                return 0 if success else 1

            args = SimpleNamespace(
                project=project,
                rules=ROOT,
                evidence=evidence,
                review_path=[".codex/hooks.json"],
                review_scope="local-config",
                review_base="",
                review_head="",
                review_outcome="pass",
                code_review_evidence="reviewed the current ignored Codex hook configuration bytes",
                docs_freshness_evidence="review guidance covers the local config boundary",
                structure_review_evidence="",
                boundary_plan_evidence="owned only .codex/hooks.json and its byte snapshot",
                side_effect_audit_evidence="confirmed no tracked, remote, credential, or product side effects",
                allow_vibeguard_review="",
                max_changed_paths=25,
                max_source_file_lines=500,
                max_function_lines=120,
                max_added_lines=300,
                output=None,
                repair_cycle=0,
            )

            def successful_validation(
                _args: object,
                checks: dict[str, object],
                _failures: list[str],
            ) -> None:
                checks["workflow_validate"] = {"returncode": 0}

            def successful_vibeguard(
                _args: object,
                _runner: object,
                _command: object,
                _parser: object,
                paths: object,
                checks: dict[str, object],
                _failures: list[str],
                audit_project: Path | None = None,
            ) -> None:
                self.assertEqual([], paths)
                checks["vibeguard"] = {"returncode": 0, "overall": "Ready"}

            with (
                patch("agent_review_hook.record_review_prerequisite_readiness"),
                patch(
                    "agent_review_hook.record_review_workflow_validation",
                    side_effect=successful_validation,
                ),
                patch(
                    "agent_review_hook.record_review_vibeguard",
                    side_effect=successful_vibeguard,
                ),
                patch("agent_review_hook.record_successful_review_workflow_validation"),
                patch("agent_review_hook.record_review_gate"),
            ):
                result = review_hook(
                    args,
                    run_command,
                    git_status,
                    lambda _project, _rules: ["vibeguard", "audit", "."],
                    lambda output: "Ready" if "Ready" in output else "unknown",
                    finish_with_result,
                )

        self.assertEqual(0, result)
        self.assertTrue(outputs[0]["success"])
        payload = outputs[0]["payload"]
        self.assertEqual(1, payload["changed_path_count"])
        self.assertTrue(payload["local_config_scope"]["accepted"])
        self.assertEqual("local-config", payload["review_subject"]["kind"])
        self.assertTrue(payload["diff_check"]["skipped"])

    def test_local_config_subject_rejects_non_allowlisted_ignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            (project / ".gitignore").write_text("*.env\n", encoding="utf-8")
            (project / "secret.env").write_text("local-only\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                ReviewAttestation.local_config_subject(project, ["secret.env"])

    def test_local_config_subject_requires_an_ignored_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            config = project / ".codex/hooks.json"
            config.parent.mkdir(parents=True)
            config.write_text('{"hooks": {}}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not Git-ignored"):
                ReviewAttestation.local_config_subject(project, [".codex/hooks.json"])

            (project / ".gitignore").write_text(".codex/\n", encoding="utf-8")
            config.unlink()
            target = project / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            config.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "rejects symlinks"):
                ReviewAttestation.local_config_subject(project, [".codex/hooks.json"])

    def test_commit_range_resolves_exact_non_empty_subject_on_clean_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            base = commit(project, "base")
            subject.write_text("value = 2\n", encoding="utf-8")
            head = commit(project, "head")

            resolved = resolve_commit_range_subject(
                project,
                base,
                head,
                run_command,
            )

        self.assertEqual("commit-range", resolved["kind"])
        self.assertEqual(base, resolved["base_sha"])
        self.assertEqual(head, resolved["head_sha"])
        self.assertEqual(["subject.py"], resolved["changed_paths"])

    def test_commit_range_rejects_reversed_and_empty_subjects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            base = commit(project, "base")
            subject.write_text("value = 2\n", encoding="utf-8")
            head = commit(project, "head")

            with self.assertRaisesRegex(ValueError, "ancestor"):
                resolve_commit_range_subject(project, head, base, run_command)
            with self.assertRaisesRegex(ValueError, "no changed paths"):
                resolve_commit_range_subject(project, head, head, run_command)
            with self.assertRaisesRegex(ValueError, "does not resolve"):
                resolve_commit_range_subject(project, base, "missing-ref", run_command)

    def test_review_hook_runs_commit_range_checks_from_a_clean_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subject = project / "subject.py"
            subject.write_text("value = 1\n", encoding="utf-8")
            base = commit(project, "base")
            subject.write_text("value = 2\n", encoding="utf-8")
            head = commit(project, "head")
            outputs: list[dict[str, object]] = []

            def git_status(path: Path) -> tuple[dict[str, object], list[str]]:
                result = run_command(
                    ["git", "status", "--short", "--untracked-files=all"],
                    path,
                )
                return result, [line for line in str(result["stdout"]).splitlines() if line]

            def finish_with_result(
                name: str,
                success: bool,
                details: list[str],
                output: Path | None,
                payload: dict[str, object],
                repair_cycle: int,
                invocation_error: bool = False,
            ) -> int:
                outputs.append(
                    {
                        "name": name,
                        "success": success,
                        "details": details,
                        "payload": payload,
                        "invocation_error": invocation_error,
                    }
                )
                return 0 if success else 1

            args = SimpleNamespace(
                project=project,
                rules=ROOT,
                evidence=None,
                review_path=[],
                review_scope="commit-range",
                review_base=base,
                review_head=head,
                review_outcome="pass",
                code_review_evidence="reviewed the exact immutable commit diff",
                docs_freshness_evidence="no durable docs impact",
                structure_review_evidence="",
                boundary_plan_evidence="owned subject.py and its exact commit range",
                side_effect_audit_evidence="checked exact commit diff and side effects",
                allow_vibeguard_review="",
                max_changed_paths=25,
                max_source_file_lines=500,
                max_function_lines=120,
                max_added_lines=300,
                output=None,
                repair_cycle=0,
            )

            def successful_validation(
                _args: object,
                checks: dict[str, object],
                _failures: list[str],
            ) -> None:
                checks["workflow_validate"] = {"returncode": 0}

            def successful_vibeguard(
                _args: object,
                _runner: object,
                _command: object,
                _parser: object,
                _paths: object,
                checks: dict[str, object],
                _failures: list[str],
                audit_project: Path | None = None,
            ) -> None:
                self.assertIsNotNone(audit_project)
                self.assertNotEqual(project, audit_project)
                checks["vibeguard"] = {"returncode": 0, "overall": "Ready"}

            with (
                patch("agent_review_hook.record_review_prerequisite_readiness"),
                patch(
                    "agent_review_hook.record_review_workflow_validation",
                    side_effect=successful_validation,
                ),
                patch(
                    "agent_review_hook.record_review_vibeguard",
                    side_effect=successful_vibeguard,
                ),
                patch("agent_review_hook.record_successful_review_workflow_validation"),
                patch("agent_review_hook.record_review_gate"),
            ):
                result = review_hook(
                    args,
                    run_command,
                    git_status,
                    lambda _project, _rules: ["vibeguard", "audit", "."],
                    lambda output: "Ready" if "Ready" in output else "unknown",
                    finish_with_result,
                )

        self.assertEqual(0, result)
        self.assertTrue(outputs[0]["success"])
        payload = outputs[0]["payload"]
        self.assertEqual(1, payload["changed_path_count"])
        self.assertEqual("commit-range", payload["review_subject"]["kind"])
        self.assertEqual(
            ["git", "diff", "--check", base, head, "--"],
            payload["diff_check"]["command"],
        )
        self.assertEqual([], payload["full_git_status_before"]["stdout"].splitlines())

    def test_empty_scope_stops_before_review_and_does_not_record_failure(self) -> None:
        git_status_result = {
            "command": ["git", "status", "--short", "--untracked-files=all"],
            "cwd": str(ROOT),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }
        result_payload: dict[str, object] = {}

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            return git_status_result, []

        def unexpected_command(*_args: object, **_kwargs: object) -> object:
            self.fail("substantive review checks must not run for an empty review scope")

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            result_payload.update(
                name=name,
                success=success,
                details=details,
                invocation_error=invocation_error,
            )
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            evidence=None,
            review_path=[],
            review_scope="working-tree",
            max_changed_paths=25,
            output=None,
            repair_cycle=0,
        )

        with (
            patch("agent_review_hook.record_review_prerequisite_readiness"),
            patch("agent_review_hook.record_review_failure") as record_failure,
        ):
            result = review_hook(
                args,
                unexpected_command,
                git_status,
                unexpected_command,
                unexpected_command,
                finish_with_result,
            )

        self.assertEqual(1, result)
        self.assertFalse(result_payload["success"])
        self.assertTrue(result_payload["invocation_error"])
        self.assertTrue(
            any("no changed paths" in detail for detail in result_payload["details"])
        )
        self.assertTrue(
            any("before commit" in detail for detail in result_payload["details"])
        )
        record_failure.assert_not_called()

    def test_changed_path_limit_stops_before_review_and_does_not_record_failure(self) -> None:
        changed_paths = [f" M src/file_{index}.py" for index in range(26)]
        git_status_result = {
            "command": ["git", "status", "--short", "--untracked-files=all"],
            "cwd": str(ROOT),
            "returncode": 0,
            "stdout": "\n".join(changed_paths),
            "stderr": "",
        }
        result_payload: dict[str, object] = {}

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            return git_status_result, changed_paths

        def unexpected_command(*_args: object, **_kwargs: object) -> object:
            self.fail("substantive review checks must not run when the scope limit is exceeded")

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            result_payload.update(
                name=name,
                success=success,
                details=details,
                invocation_error=invocation_error,
            )
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            evidence=None,
            review_path=[],
            review_scope="working-tree",
            max_changed_paths=25,
            output=None,
            repair_cycle=0,
        )

        with (
            patch("agent_review_hook.record_review_prerequisite_readiness"),
            patch("agent_review_hook.record_review_failure") as record_failure,
        ):
            result = review_hook(
                args,
                unexpected_command,
                git_status,
                unexpected_command,
                unexpected_command,
                finish_with_result,
            )

        self.assertEqual(1, result)
        self.assertFalse(result_payload["success"])
        self.assertTrue(result_payload["invocation_error"])
        self.assertTrue(
            any("--max-changed-paths 26" in detail for detail in result_payload["details"])
        )
        record_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
