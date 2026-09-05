from __future__ import annotations

import json
import io
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_common import requires_retrospective
from agent_finish_gate_policy import (
    PLATFORM_SELECTION_GATE,
    PRD_DRAFT_GATE,
    REVIEW_READINESS_GATE,
    VALIDATED_GATES,
    validate_gate_evidence,
)
from agent_finish_check_steps import (
    check_request_intake,
    check_required_gates,
    validate_grill_me_skill_evidence,
)
from agent_gate_evidence import (
    gate_evidence_path_for_preflight,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    record_many_gate_evidence,
    reset_gate_evidence_ledger,
    synthesize_gate_evidence,
)
from agent_worker_evidence import worker_reservation_matches
from agent_delegation_plan import validate_delegation_plan_evidence
from agent_global_lessons import (
    lesson_summary,
    retrospective_candidate,
    write_retrospective_candidate,
)
from agent_lesson_store import upsert_retrospective_candidate
from agent_hook_runtime import hook_failure_policy, repair_context_failures
import agent_skill_hooks
from agent_preflight_runtime import (
    AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES as PREFLIGHT_AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES,
    _claude_spill_warnings,
)
from agent_review_hook import review_hook, review_vibeguard_command, workflow_validate_failure_detail
from agent_review_structure import structure_review
from agent_vibeguard_cache import cached_vibeguard
from support.agy_setup import AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES, _agy_runtime_bridge_block
from support.claude_setup import _merge_claude_user_prompt_submit
from support.permission_entries import agy_permission_entries, claude_permission_entries, codex_prefix_rule_entries
from support.runtime_bridge import (
    CODEX_DISPATCH_BRIDGE_PHRASE,
    RUNTIME_BRIDGE_GRAPH_PHRASES,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.stable_launcher import stable_launcher_path
from workflow_catalog import COMMANDS, CONCERNS, SPILL_ACTION_LABELS
from workflow_gate_policy import (
    AGENTIC_RUN_STATE_GATE,
    AMBIGUITY_GATE,
    ALIGNMENT_BRIEF_GATE,
    BOUNDARY_PLAN_GATE,
    CYCLE_CONTRACT_GATE,
    DOCUMENTATION_IMPACT_GATE,
    DOCUMENTATION_GATE,
    MULTI_AGENT_GATE,
    PRODUCT_REENTRY_GATE,
    PRODUCT_REENTRY_COMMANDS,
    SKILL_FEEDBACK_HOOK,
    SIDE_EFFECT_AUDIT_GATE,
    SOURCE_DOCS_GATE,
    SOURCE_DOCS_COMMANDS,
    TEST_GATE,
    ALIGNMENT_BRIEF_COMMANDS,
    WORK_PRODUCING_COMMANDS,
)
from workflow_request import infer_concerns_from_request
from workflow_request import classify_request
from workflow_request import classified_route_block_reason
from workflow_request import route_block_reason
from workflow_dispatch import (
    build_dispatch_manifest,
    execute_dispatch_manifest,
    print_dispatch_manifest,
)
from workflow_dispatch_profiles import profile_for_work_kind, select_work_kind
from workflow_doc_surfaces import (
    extract_request_surface_paths,
    git_status_surface_paths,
    infer_surface_docs,
    load_doc_surface_rules,
    surface_rule_doc_refs,
)
from workflow_doc_graph import (
    clear_doc_graph_cache,
    expand_doc_matches,
    graph_required_docs,
)
from workflow_parallel_validate import validate_parallel_execution_plan
from workflow_route import resolve_docs, route_hooks
from workflow_search import SearchOutcome, search_docs, search_docs_outcome
from workflow_skill_paths import canonical_doc_path
from workflow_spill import spill_tool_label, validate_spill_label_contracts
from workflow import build_parser, print_dispatch
from workflow_validate import (
    STRICT_CARD_REQUIRED_HEADINGS,
    markdown_files_to_validate,
    removed_cli_option_failures,
)


_PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "agent_preflight_under_test", ROOT / "scripts" / "agent-preflight.py"
)
assert _PREFLIGHT_SPEC and _PREFLIGHT_SPEC.loader
agent_preflight = importlib.util.module_from_spec(_PREFLIGHT_SPEC)
_PREFLIGHT_SPEC.loader.exec_module(agent_preflight)

_FINISH_CHECK_SPEC = importlib.util.spec_from_file_location(
    "agent_finish_check_under_test", ROOT / "scripts" / "agent-finish-check.py"
)
assert _FINISH_CHECK_SPEC and _FINISH_CHECK_SPEC.loader
agent_finish_check = importlib.util.module_from_spec(_FINISH_CHECK_SPEC)
_FINISH_CHECK_SPEC.loader.exec_module(agent_finish_check)

_AGENT_HOOK_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_under_test", ROOT / "scripts" / "agent-hook.py"
)
assert _AGENT_HOOK_SPEC and _AGENT_HOOK_SPEC.loader
agent_hook = importlib.util.module_from_spec(_AGENT_HOOK_SPEC)
_AGENT_HOOK_SPEC.loader.exec_module(agent_hook)


def route_doc(path: str) -> str:
    return canonical_doc_path(path)


class VibeguardCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_vibeguard_cache_reuses_same_git_state_and_invalidates_on_status_change(self) -> None:
        calls: list[list[str]] = []
        state = {"status": ""}

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "abc123\n",
                    "stderr": "",
                }
            if command[:2] == ["git", "status"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": state["status"],
                    "stderr": "",
                }
            if command == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "Overall: Ready\n",
                    "stderr": "",
                }
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            rules = project
            command = lambda _project, _rules: ["vibeguard", "audit", "."]
            parse = lambda output: "Ready" if "Ready" in output else "unknown"

            first = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            second = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            (project / "app.py").write_text("changed\n", encoding="utf-8")
            state["status"] = " M app.py\0"
            third = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )

        audit_calls = [command for command in calls if command == ["vibeguard", "audit", "."]]
        self.assertEqual(2, len(audit_calls))
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertFalse(third["cached"])
        status_calls = [command for command in calls if command[:2] == ["git", "status"]]
        self.assertEqual(3, len(status_calls))
        self.assertTrue(all("-z" in command for command in status_calls))

    def test_supplied_short_status_does_not_replace_current_nul_listing(self) -> None:
        from agent_vibeguard_cache import _git_state

        calls: list[list[str]] = []
        listing = " M app.py\0"

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            if command[:2] == ["git", "rev-parse"]:
                return {"returncode": 0, "stdout": "abc\n"}
            self.assertEqual(
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], command
            )
            return {"returncode": 0, "stdout": listing}

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "app.py").write_text("same bytes\n", encoding="utf-8")
            state = _git_state(project, run_command, {"returncode": 0, "stdout": ""})
            # Staging changes status without changing bytes. Identity must come
            # from the fresh listing even if the caller repeats stale context.
            listing = "M  app.py\0"
            staged = _git_state(project, run_command, {"returncode": 0, "stdout": ""})

        self.assertEqual(" M app.py\0", state["status"])
        self.assertEqual(state["dirty_content"], staged["dirty_content"])
        self.assertNotEqual(state, staged)
        self.assertEqual(4, len(calls))  # HEAD plus one listing for each state.

    def test_failed_listing_or_unreadable_path_never_reuses_or_writes_cache(self) -> None:
        for result in (
            {"returncode": 1, "stdout": ""},
            {"returncode": 0, "stdout": " M missing.py\0"},
        ):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temp_dir:
                calls: list[list[str]] = []

                def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                    calls.append(command)
                    if command[:2] == ["git", "rev-parse"]:
                        return {"returncode": 0, "stdout": "abc\n"}
                    if command[:2] == ["git", "status"]:
                        return result
                    return {"returncode": 0, "stdout": "Overall: Ready\n", "stderr": ""}

                project = Path(temp_dir)
                with patch("agent_vibeguard_cache._read_cache") as read_cache, patch(
                    "agent_vibeguard_cache._write_cache"
                ) as write_cache:
                    audit = cached_vibeguard(
                        project=project, rules=project, run_command=run_command,
                        vibeguard_command=lambda _p, _r: ["vibeguard", "audit", "."],
                        parse_overall=lambda output: "Ready",
                    )
                read_cache.assert_not_called()
                write_cache.assert_not_called()
                self.assertFalse(audit["cached"])
                self.assertEqual(1, calls.count(["vibeguard", "audit", "."]))

    def test_a_second_edit_of_the_same_file_is_audited_again(self) -> None:
        """The key has to see the bytes, not only which paths differ.

        `git status --short` prints ` M app.py` for every edit of that file, so
        HEAD plus the status text was identical before and after a second edit.
        The cache returned the first edit's verdict for content no audit had
        ever read -- a clean result standing in for unreviewed bytes.
        """

        audits: list[str] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            target = project / "app.py"
            target.write_text("SAFE = 1\n", encoding="utf-8")

            def run_command(command: list[str], cwd: Path) -> dict[str, object]:
                base = {"command": command, "cwd": str(cwd), "stderr": ""}
                if command[:3] == ["git", "rev-parse", "--verify"]:
                    return {**base, "returncode": 0, "stdout": "abc123\n"}
                if command[:2] == ["git", "status"]:
                    listing = " M app.py\0" if "-z" in command else " M app.py\n"
                    return {**base, "returncode": 0, "stdout": listing}
                if command == ["vibeguard", "audit", "."]:
                    audits.append(target.read_text(encoding="utf-8"))
                    return {**base, "returncode": 0, "stdout": "Overall: Ready\n"}
                raise AssertionError(command)

            def audit() -> dict:
                return cached_vibeguard(
                    project=project,
                    rules=project,
                    run_command=run_command,
                    vibeguard_command=lambda _project, _rules: ["vibeguard", "audit", "."],
                    parse_overall=lambda output: "Ready" if "Ready" in output else "unknown",
                )

            first = audit()
            cached = audit()
            target.write_text("AWS_SECRET_ACCESS_KEY = 'AKIAEXAMPLE'\n", encoding="utf-8")
            after_edit = audit()
            second_cached = audit()

        self.assertFalse(first["cached"])
        # Nothing changed between these two, so the cache is still worth having.
        self.assertTrue(cached["cached"])
        # The bytes changed while the status text did not: audit again.
        self.assertFalse(after_edit["cached"])
        # And the new content is cached in its turn, so the fix costs one audit
        # per distinct content rather than one per call.
        self.assertTrue(second_cached["cached"])
        self.assertEqual(
            ["SAFE = 1\n", "AWS_SECRET_ACCESS_KEY = 'AKIAEXAMPLE'\n"], audits
        )

    def test_an_unreadable_changed_path_yields_no_key(self) -> None:
        """A path the digest cannot open is a path the key cannot vouch for.

        This used to record a fixed "unreadable" marker instead. The marker was
        stable across every edit of the file behind it, so a name git had
        escaped -- which resolved to nothing on disk -- keyed one verdict for
        all its contents. No key means no cache read and no write.
        """

        from agent_vibeguard_cache import _dirty_content_digest

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            absent = _dirty_content_digest(project, " M gone.py\0")
            (project / "gone.py").write_text("x = 1\n", encoding="utf-8")
            present = _dirty_content_digest(project, " M gone.py\0")

        self.assertIsNone(absent)
        self.assertIsInstance(present, str)

    def test_a_renamed_path_is_digested_at_its_destination(self) -> None:
        """A `-z` rename record is `RM new\\0old\\0`; the bytes live at `new`."""

        from agent_vibeguard_cache import _dirty_content_digest

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "new.py").write_text("first\n", encoding="utf-8")
            before = _dirty_content_digest(project, "RM new.py\0old.py\0")
            (project / "new.py").write_text("second\n", encoding="utf-8")
            after = _dirty_content_digest(project, "RM new.py\0old.py\0")

        self.assertIsInstance(before, str)
        self.assertNotEqual(before, after)

    def test_a_file_whose_name_git_escapes_is_keyed_by_its_content(self) -> None:
        """Git itself produces the escaping here; nothing in this test fakes it.

        `git status --short` prints a Korean file name as `"\\354\\204\\244..."`,
        and the previous digest took that spelling as the path. It opened
        nothing, recorded the fixed unreadable marker, and two different
        contents of the file shared one key -- the exact hole the digest was
        added to close, reopened for every non-ASCII name.
        """

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            done = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            return {
                "command": command,
                "cwd": str(cwd),
                "returncode": done.returncode,
                "stdout": done.stdout,
                "stderr": done.stderr,
            }

        audits: list[str] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            run_command(["git", "init", "-q", str(project)], project.parent)
            run_command(["git", "config", "user.email", "t@example.com"], project)
            run_command(["git", "config", "user.name", "T"], project)
            target = project / "설정.py"
            target.write_text("SAFE = 1\n", encoding="utf-8")
            run_command(["git", "add", "."], project)
            run_command(["git", "commit", "-qm", "base"], project)

            short = run_command(["git", "status", "--short"], project)

            def vibeguard(command: list[str], cwd: Path) -> dict[str, object]:
                if command[:1] == ["vibeguard"]:
                    audits.append(target.read_text(encoding="utf-8"))
                    return {"command": command, "cwd": str(cwd), "returncode": 0,
                            "stdout": "Overall: Ready\n", "stderr": ""}
                return run_command(command, cwd)

            def audit() -> dict:
                return cached_vibeguard(
                    project=project,
                    rules=project,
                    run_command=vibeguard,
                    vibeguard_command=lambda _p, _r: ["vibeguard", "audit", "."],
                    parse_overall=lambda output: "Ready" if "Ready" in output else "unknown",
                )

            target.write_text("SAFE = 2\n", encoding="utf-8")
            escaped = run_command(["git", "status", "--short"], project)["stdout"]
            first = audit()
            target.write_text("AWS_SECRET_ACCESS_KEY = 'AKIAEXAMPLE'\n", encoding="utf-8")
            second = audit()

        # The premise: git really does escape the name in the line listing.
        self.assertIn("\\354", escaped, escaped)
        self.assertEqual("", short["stdout"])
        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])
        self.assertEqual(["SAFE = 2\n", "AWS_SECRET_ACCESS_KEY = 'AKIAEXAMPLE'\n"], audits)

    def test_vibeguard_cache_invalidates_on_rules_git_state_change(self) -> None:
        calls: list[tuple[Path, list[str]]] = []
        states = {"project": "", "rules": ""}

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append((cwd, command))
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": f"{cwd.name}-head\n",
                    "stderr": "",
                }
            if command[:2] == ["git", "status"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": states[cwd.name],
                    "stderr": "",
                }
            if command == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "Overall: Ready\n",
                    "stderr": "",
                }
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            rules = root / "rules"
            project.mkdir()
            rules.mkdir()
            command = lambda _project, _rules: ["vibeguard", "audit", "."]
            parse = lambda output: "Ready" if "Ready" in output else "unknown"

            first = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            second = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            (rules / "rules.md").write_text("changed\n", encoding="utf-8")
            states["rules"] = " M rules.md\0"
            third = cached_vibeguard(
                project=project,
                rules=rules,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )

        audit_calls = [command for _cwd, command in calls if command == ["vibeguard", "audit", "."]]
        self.assertEqual(2, len(audit_calls))
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertFalse(third["cached"])

    def test_vibeguard_cache_does_not_store_failed_invocations(self) -> None:
        calls: list[list[str]] = []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "abc\n", "stderr": ""}
            if command[:2] == ["git", "status"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "temporary failure",
                }
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            command = lambda _project, _rules: ["vibeguard", "audit", "."]
            parse = lambda output: "Ready" if "Ready" in output else "unknown"

            first = cached_vibeguard(
                project=project,
                rules=project,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            second = cached_vibeguard(
                project=project,
                rules=project,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )

        audit_calls = [command for command in calls if command == ["vibeguard", "audit", "."]]
        self.assertEqual(2, len(audit_calls))
        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])

    def test_vibeguard_cache_write_permission_failure_does_not_hide_successful_audit(self) -> None:
        calls: list[list[str]] = []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "abc\n",
                    "stderr": "",
                }
            if command[:2] == ["git", "status"]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
            if command == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "Overall: Ready\n",
                    "stderr": "",
                }
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            command = lambda _project, _rules: ["vibeguard", "audit", "."]
            parse = lambda output: "Ready" if "Ready" in output else "unknown"

            with patch(
                "agent_vibeguard_cache._write_cache",
                side_effect=PermissionError("cache is read-only"),
            ):
                result = cached_vibeguard(
                    project=project,
                    rules=project,
                    run_command=run_command,
                    vibeguard_command=command,
                    parse_overall=parse,
                )

        self.assertEqual(0, result["returncode"])
        self.assertEqual("Ready", result["overall"])
        self.assertFalse(result["cached"])
        self.assertEqual("PermissionError", result["cache"]["write_error"])
        self.assertEqual(1, calls.count(["vibeguard", "audit", "."]))

    def test_vibeguard_cache_does_not_swallow_non_io_write_failures(self) -> None:
        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            if command[:3] == ["git", "rev-parse", "--verify"]:
                stdout = "abc\n"
            elif command[:2] == ["git", "status"]:
                stdout = ""
            elif command == ["vibeguard", "audit", "."]:
                stdout = "Overall: Ready\n"
            else:
                raise AssertionError(command)
            return {
                "command": command,
                "cwd": str(cwd),
                "returncode": 0,
                "stdout": stdout,
                "stderr": "",
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            with patch(
                "agent_vibeguard_cache._write_cache",
                side_effect=RuntimeError("unexpected cache bug"),
            ):
                with self.assertRaisesRegex(RuntimeError, "unexpected cache bug"):
                    cached_vibeguard(
                        project=project,
                        rules=project,
                        run_command=run_command,
                        vibeguard_command=lambda _project, _rules: [
                            "vibeguard",
                            "audit",
                            ".",
                        ],
                        parse_overall=lambda output: (
                            "Ready" if "Ready" in output else "unknown"
                        ),
                    )

    def test_vibeguard_cache_ignores_preexisting_failed_cache_entry(self) -> None:
        calls: list[list[str]] = []

        def run_command(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(command)
            if command[:3] == ["git", "rev-parse", "--verify"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "abc\n", "stderr": ""}
            if command[:2] == ["git", "status"]:
                return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout": "", "stderr": ""}
            if command == ["vibeguard", "audit", "."]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 0,
                    "stdout": "Overall: Ready\n",
                    "stderr": "",
                }
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            command = lambda _project, _rules: ["vibeguard", "audit", "."]
            parse = lambda output: "Ready" if "Ready" in output else "unknown"

            first = cached_vibeguard(
                project=project,
                rules=project,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )
            cache_path = project / ".tao" / "vibeguard-cache.json"
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["result"]["returncode"] = 1
            payload["result"]["stderr"] = "old failure"
            cache_path.write_text(json.dumps(payload), encoding="utf-8")

            second = cached_vibeguard(
                project=project,
                rules=project,
                run_command=run_command,
                vibeguard_command=command,
                parse_overall=parse,
            )

        audit_calls = [command for command in calls if command == ["vibeguard", "audit", "."]]
        self.assertEqual(2, len(audit_calls))
        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])


if __name__ == "__main__":
    unittest.main()
