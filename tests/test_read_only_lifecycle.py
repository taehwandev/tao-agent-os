from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_read_only_test", "agent-hook.py")
agent_preflight = _load_script("agent_preflight_read_only_test", "agent-preflight.py")
agent_finish = _load_script("agent_finish_read_only_test", "agent-finish-check.py")

from agent_finish_check_steps import check_preflight_vibeguard, check_read_only_execution
from agent_finish_final_checks import _record_vibeguard_signal
from agent_execution_capsule_state import git_states_for_paths


class ReadOnlyLifecycleTests(unittest.TestCase):
    def test_analysis_preflight_is_intrinsically_read_only(self) -> None:
        self.assertTrue(agent_preflight.effective_read_only("analysis", False))
        self.assertTrue(agent_preflight.effective_read_only("product", True))
        self.assertFalse(agent_preflight.effective_read_only("product", False))

    def test_finish_recovers_legacy_analysis_evidence_as_read_only(self) -> None:
        self.assertTrue(
            agent_finish.effective_read_only(
                {"execution_mode": {"read_only": False}},
                {"command": "analysis"},
            )
        )
        self.assertFalse(
            agent_finish.effective_read_only(
                {"execution_mode": {"read_only": False}},
                {"command": "product"},
            )
        )

    def test_start_forwards_read_only_to_preflight(self) -> None:
        args = Namespace(
            project=Path("/tmp/project"),
            rules=ROOT,
            command="analysis",
            request="audit repository migration",
            request_classified=True,
            classification_evidence="explicit non-mutating audit",
            platform=[],
            concern=[],
            read_only=True,
            evidence=None,
            worker_reservation_token="",
            output=None,
            repair_cycle=0,
        )
        result = {"returncode": 1, "stdout": "", "stderr": ""}

        with (
            patch.object(agent_hook, "run_script_main", return_value=result) as runner,
            patch.object(agent_hook, "finish_with_result", return_value=1),
        ):
            agent_hook.start_hook(args)

        command = runner.call_args.args[1]
        self.assertIn("--read-only", command)

    def test_read_only_preflight_records_an_explicit_skip(self) -> None:
        result = agent_preflight.skipped_vibeguard(Path("/tmp/project"))

        self.assertTrue(result["skipped"])
        self.assertEqual(0, result["returncode"])
        self.assertEqual("Skipped", result["overall"]["status"])

    def test_finish_accepts_only_a_declared_read_only_skip(self) -> None:
        preflight = {
            "vibeguard": agent_preflight.skipped_vibeguard(Path("/tmp/project"))
        }
        failures: list[str] = []

        check_preflight_vibeguard(preflight, failures, read_only=True)

        self.assertEqual([], failures)

        check_preflight_vibeguard(preflight, failures, read_only=False)
        self.assertIn(
            "preflight VibeGuard was skipped without read-only execution mode",
            failures,
        )

    def test_finish_reports_read_only_vibeguard_as_skipped_success(self) -> None:
        signals: list[dict[str, str]] = []
        failures: list[str] = []

        _record_vibeguard_signal(
            agent_preflight.skipped_vibeguard(Path("/tmp/project")),
            None,
            signals,
            failures,
        )

        self.assertEqual([], failures)
        self.assertEqual("SUCCESS", signals[0]["signal"])
        self.assertEqual("skipped", signals[0]["status"])


class ReadOnlyClaimEnforcementTests(unittest.TestCase):
    """Read-only buys a VibeGuard skip, so finish must hold the run to it.

    Scenario: an agent declares `--read-only` on a writing route, edits files,
    and reaches finish. The declaration was made at start, before any edit, so
    nothing in the recorded evidence contradicts it. Finish compares the
    worktree against the state start recorded and fails closed when it moved.
    """

    @staticmethod
    def _preflight(state: dict[str, str], rules: Path) -> dict:
        # These cases run project and rules from one root, so both fingerprints
        # are the same value; the point under test is the worktree comparison.
        return {
            "rules": str(rules),
            "read_only_execution_state": {"project": state, "rules": state},
        }

    @staticmethod
    def _init_repository(project: Path) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=project,
            check=True,
        )
        target = project / "tracked.txt"
        target.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=project, check=True)
        return target

    def test_unchanged_worktree_keeps_the_read_only_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._init_repository(project)
            state, _ = git_states_for_paths(project, project)
            failures: list[str] = []

            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )

        self.assertEqual([], failures)

    def test_same_bytes_with_changed_metadata_keeps_the_read_only_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = self._init_repository(project)
            target.write_text("dirty-a\n", encoding="utf-8")
            state, _ = git_states_for_paths(project, project)
            target.write_text("dirty-a\n", encoding="utf-8")
            failures: list[str] = []

            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )

        self.assertEqual([], failures)

    def test_same_status_byte_mutation_under_read_only_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = self._init_repository(project)
            target.write_text("dirty-a\n", encoding="utf-8")
            state, _ = git_states_for_paths(project, project)
            target.write_text("dirty-b\n", encoding="utf-8")
            failures: list[str] = []

            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )

        self.assertEqual(1, len(failures))
        self.assertIn("read-only execution was declared", failures[0])
        self.assertIn("rerun the lifecycle without --read-only", failures[0])

    def test_clean_head_advance_reports_stale_input_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = self._init_repository(project)
            state, _ = git_states_for_paths(project, project)
            target.write_text("concurrent revision\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "concurrent revision"],
                cwd=project,
                check=True,
            )
            failures: list[str] = []

            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )

        self.assertEqual(1, len(failures))
        self.assertIn("revision changed after start", failures[0])
        self.assertIn("stale-input evidence", failures[0])
        self.assertIn("regenerate start/preflight", failures[0])
        self.assertIn("first failed checkpoint", failures[0])

    def test_negative_control_writing_run_is_not_policed_by_this_check(self) -> None:
        """The control: the same mutation must pass when read-only was not claimed.

        A writing run earns its VibeGuard audit instead, so this check must stay
        silent there. If it fired unconditionally every ordinary run would fail.
        """

        failures: list[str] = []

        check_read_only_execution(
            {},
            Path("/workspace/does-not-need-to-exist"),
            failures,
            read_only=False,
            state_reader=lambda *_: (_ for _ in ()).throw(
                AssertionError("writing runs do not read the read-only fingerprint")
            ),
        )

        self.assertEqual([], failures)

    def test_non_git_workspace_uses_a_directory_content_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "draft.md"
            target.write_text("draft-a\n", encoding="utf-8")
            state, _ = git_states_for_paths(project, project)
            failures: list[str] = []

            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )
            self.assertEqual([], failures)

            target.write_text("draft-b\n", encoding="utf-8")
            check_read_only_execution(
                self._preflight(state, project),
                project,
                failures,
                read_only=True,
            )

        self.assertEqual(1, len(failures))
        self.assertIn("project root changed after start", failures[0])

    def test_git_inspection_error_fails_closed(self) -> None:
        failures: list[str] = []
        state = {
            "head": "abc",
            "worktree_fingerprint": "0" * 64,
            "worktree_signature": "1" * 64,
        }

        check_read_only_execution(
            self._preflight(state, Path("/tmp/project")),
            Path("/tmp/project"),
            failures,
            read_only=True,
            state_reader=lambda *_: (_ for _ in ()).throw(
                RuntimeError("dubious ownership")
            ),
        )

        self.assertEqual(1, len(failures))
        self.assertIn("could not be verified", failures[0])
        self.assertIn("fail closed", failures[0])

    def test_missing_strong_start_state_fails_closed(self) -> None:
        failures: list[str] = []

        check_read_only_execution(
            {},
            Path("/tmp/project"),
            failures,
            read_only=True,
            state_reader=lambda *_: ({}, {}),
        )

        self.assertEqual(1, len(failures))
        self.assertIn("missing its strong start-time workspace fingerprint", failures[0])

    def test_start_binds_read_only_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._init_repository(project)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps({"execution_mode": {"read_only": True}}),
                encoding="utf-8",
            )
            args = Namespace(project=project, rules=project, evidence=evidence_path)
            details: list[str] = []

            self.assertTrue(
                agent_hook._bind_read_only_execution_state(args, details)
            )
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))

        state = payload["read_only_execution_state"]
        self.assertEqual({"project", "rules"}, set(state))
        for root in ("project", "rules"):
            self.assertEqual(
                {"head", "worktree_fingerprint", "worktree_signature"},
                set(state[root]),
            )
        self.assertEqual(["read-only execution state: bound"], details)

    def test_start_fails_when_read_only_state_cannot_be_captured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence_path = project / "preflight.json"
            evidence_path.write_text(
                json.dumps({"execution_mode": {"read_only": True}}),
                encoding="utf-8",
            )
            args = Namespace(project=project, rules=project, evidence=evidence_path)
            details: list[str] = []

            with patch.object(
                agent_hook,
                "git_states_for_paths",
                side_effect=RuntimeError("git inspection failed"),
            ):
                success = agent_hook._bind_read_only_execution_state(args, details)

        self.assertFalse(success)
        self.assertEqual(
            ["read-only execution state: capture failed (git inspection failed)"],
            details,
        )


class ReadOnlyRulesRootTests(unittest.TestCase):
    """Read-only must fingerprint the rules root, not the project twice.

    A read-only run against a separate rules checkout can still edit that
    checkout. Capturing the project state under both keys made the comparison
    trivially true for rules, so edits to shared guidance finished unnoticed.
    """

    @staticmethod
    def _state(head: str) -> dict:
        return {
            "head": head,
            "worktree_fingerprint": "a" * 64,
            "worktree_signature": "b" * 64,
        }

    def _preflight(self) -> dict:
        return {
            "rules": "/rules",
            "read_only_execution_state": {
                "project": self._state("project-head"),
                "rules": self._state("rules-head"),
            },
        }

    def test_unchanged_project_and_rules_pass(self) -> None:
        failures: list[str] = []

        check_read_only_execution(
            self._preflight(),
            Path("/project"),
            failures,
            read_only=True,
            state_reader=lambda project, rules: (
                self._state("project-head"),
                self._state("rules-head"),
            ),
        )

        self.assertEqual([], failures)

    def test_changed_rules_root_fails_closed(self) -> None:
        failures: list[str] = []

        check_read_only_execution(
            self._preflight(),
            Path("/project"),
            failures,
            read_only=True,
            state_reader=lambda project, rules: (
                self._state("project-head"),
                self._state("rules-moved"),
            ),
        )

        self.assertEqual(1, len(failures))
        self.assertIn("rules revision changed after start", failures[0])
        self.assertIn("regenerate start/preflight", failures[0])

    def test_negative_control_changed_project_still_fails(self) -> None:
        """The control: widening to two roots must not drop the project check."""

        failures: list[str] = []

        check_read_only_execution(
            self._preflight(),
            Path("/project"),
            failures,
            read_only=True,
            state_reader=lambda project, rules: (
                self._state("project-moved"),
                self._state("rules-head"),
            ),
        )

        self.assertEqual(1, len(failures))
        self.assertIn("project revision changed after start", failures[0])
        self.assertIn("regenerate start/preflight", failures[0])

    def test_reader_receives_the_recorded_rules_root(self) -> None:
        seen: list[tuple] = []

        def reader(project, rules):
            seen.append((project, rules))
            return self._state("project-head"), self._state("rules-head")

        check_read_only_execution(
            self._preflight(), Path("/project"), [], read_only=True, state_reader=reader
        )

        self.assertEqual([(Path("/project"), Path("/rules"))], seen)

    def test_legacy_single_root_state_fails_closed(self) -> None:
        failures: list[str] = []

        check_read_only_execution(
            {"rules": "/rules", "read_only_execution_state": self._state("only-project")},
            Path("/project"),
            failures,
            read_only=True,
            state_reader=lambda project, rules: (
                self._state("only-project"),
                self._state("only-project"),
            ),
        )

        self.assertEqual(1, len(failures))
        self.assertIn("project and rules roots", failures[0])


if __name__ == "__main__":
    unittest.main()
