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
from support.claude_setup import (
    _merge_claude_pre_tool_gate,
    _merge_claude_user_prompt_submit,
)
from support.permission_entries import (
    EXECUTABLE_ENTRYPOINTS,
    agy_permission_entries,
    claude_permission_entries,
    codex_prefix_rule_entries,
)
from support.project_type_detection import detect_project_permissions
from support.spill_permissions import spill_helper_path_variants
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


class RuntimeSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_claude_user_prompt_hook_replaces_request_classified_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            old_command = (
                "SPILL_AI_TOOL=claude python3 '/tmp/tao-agent-os/scripts/workflow.py' "
                "route triage --request-classified"
            )
            target.write_text(json.dumps({
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": old_command, "timeout": 5}],
                        }
                    ]
                }
            }))
            new_command = (
                f"TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL=claude '{stable_launcher_path()}' workflow "
                "route triage --advisory"
            )

            status = _merge_claude_user_prompt_submit(target, new_command, dry_run=False)
            config = json.loads(target.read_text())
            commands = [
                hook["command"]
                for group in config["hooks"]["UserPromptSubmit"]
                for hook in group["hooks"]
            ]

        self.assertEqual("installed", status)
        self.assertNotIn(old_command, commands)
        self.assertIn(new_command, commands)

    def test_claude_hook_migration_preserves_neighboring_user_hooks(self) -> None:
        cases = (
            (
                "UserPromptSubmit",
                "SPILL_AI_TOOL=claude tao-hook workflow route triage "
                "--request-classified --classification-evidence safe",
                "SPILL_AI_TOOL=claude tao-hook workflow route triage "
                "--request-classified --classification-evidence safe",
                _merge_claude_user_prompt_submit,
                ".*",
            ),
            (
                "PreToolUse",
                "tao-hook claude-pretool-gate",
                "tao-hook claude-pretool-gate",
                _merge_claude_pre_tool_gate,
                "Edit|Write|MultiEdit|NotebookEdit",
            ),
        )
        for hook_name, old_command, new_command, merge, matcher in cases:
            with self.subTest(hook=hook_name), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "settings.json"
                target.write_text(json.dumps({
                    "hooks": {
                        hook_name: [
                            {
                                "matcher": "old-matcher",
                                "hooks": [
                                    {"type": "command", "command": old_command},
                                    {"type": "command", "command": "user-owned-command"},
                                ],
                            }
                        ]
                    }
                }))

                status = merge(target, new_command, dry_run=False)
                groups = json.loads(target.read_text())["hooks"][hook_name]
                commands = [hook["command"] for group in groups for hook in group["hooks"]]

                self.assertEqual("installed", status)
                self.assertIn("user-owned-command", commands)
                if old_command != new_command:
                    self.assertNotIn(old_command, commands)
                self.assertEqual(1, commands.count(new_command))
                self.assertTrue(any(group.get("matcher") == matcher for group in groups))

    def test_preflight_warns_for_retired_claude_classified_hook(self) -> None:
        config = {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "command": (
                                    "SPILL_AI_TOOL=claude python3 "
                                    "'/tmp/tao-agent-os/scripts/workflow.py' "
                                    "route triage --request-classified"
                                )
                            }
                        ]
                    }
                ]
            },
            "env": {"SPILL_AI_TOOL": "claude"},
        }

        warnings = _claude_spill_warnings(config, Path("/tmp/tao-agent-os"))

        self.assertTrue(any("--advisory" in warning for warning in warnings))

    def test_setup_permissions_include_new_workflow_helpers(self) -> None:
        entry_list = codex_prefix_rule_entries(ROOT / "scripts")
        entries = "\n".join(entry_list)

        self.assertEqual(18, len(EXECUTABLE_ENTRYPOINTS))
        self.assertTrue(all((ROOT / "scripts" / name).is_file() for name in EXECUTABLE_ENTRYPOINTS))
        for name in EXECUTABLE_ENTRYPOINTS:
            self.assertIn(str(ROOT / "scripts" / name), entries)
        self.assertNotIn("workflow_gate_policy.py", entries)
        self.assertNotIn("tests/", entries)
        self.assertNotIn("support/", entries)
        self.assertNotIn("agent-docs-read.py", entries)
        self.assertIn(
            f'prefix_rule(pattern=["python3", "{ROOT / "scripts" / "agent-hook.py"}"], decision="allow")',
            entries,
        )
        self.assertIn(
            f'prefix_rule(pattern=["{stable_launcher_path()}"], decision="allow")',
            entries,
        )
        self.assertEqual(55, len(entry_list))
        self.assertNotIn("$HOME", entries)
        self.assertNotIn("${HOME}", entries)
        self.assertNotIn("$TAO_HOME", entries)
        self.assertNotIn("~/", entries)
        self.assertNotIn('", "scripts/', entries)
        self.assertNotIn("--project", entries)
        self.assertNotIn("--request", entries)

    def test_setup_permissions_use_stable_launcher_for_claude(self) -> None:
        entry_list = claude_permission_entries(ROOT / "scripts", spill_available=True)
        entries = "\n".join(entry_list)

        self.assertIn(str(stable_launcher_path()), entries)
        self.assertIn("tao-hook", entries)
        self.assertNotIn(str(ROOT / "scripts"), entries)
        self.assertNotIn("$defaults", entry_list)
        self.assertNotIn("$HOME", entries)
        self.assertNotIn("${HOME}", entries)
        self.assertNotIn("~/", entries)
        self.assertEqual(78, len(entry_list))

    def test_setup_permissions_cover_python_verification_commands(self) -> None:
        # These are the verification kinds the repair hook accepts, so setup must
        # install them on every machine instead of relying on hand-added local rules.
        entries = claude_permission_entries(ROOT / "scripts", spill_available=False)

        for command in ("python3 -m unittest", "python3 -m pytest", "python3 -m py_compile"):
            self.assertIn(f"Bash({command} *)", entries)

    def test_python_edit_permissions_cover_script_style_repos(self) -> None:
        # Tao Agent OS ships no packaging manifest, so manifest-only detection
        # would leave its own 181 *.py files without an edit permission.
        self.assertIn("Edit(**/*.py)", detect_project_permissions(ROOT))

    def test_python_edit_permissions_skip_non_python_repos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "README.md").write_text("no python here\n")

            self.assertEqual([], detect_project_permissions(project))

    def test_packaged_python_repos_keep_toolchain_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "pyproject.toml").write_text("[project]\n")

            entries = detect_project_permissions(project)

            self.assertIn("Edit(**/*.py)", entries)
            self.assertIn("Bash(uv run *)", entries)

    def test_setup_permissions_use_stable_launcher_for_agy(self) -> None:
        entry_list = agy_permission_entries(ROOT / "scripts", spill_available=True)
        entries = "\n".join(entry_list)

        self.assertIn(str(stable_launcher_path()), entries)
        self.assertIn("tao-hook", entries)
        self.assertNotIn(str(ROOT / "scripts"), entries)
        self.assertNotIn("$HOME", entries)
        self.assertNotIn("${HOME}", entries)
        self.assertNotIn("~/", entries)
        self.assertEqual(78, len(entry_list))

    def test_spill_helper_uses_one_absolute_escaped_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            variants = spill_helper_path_variants(
                "spill-token-metering-setup.mjs",
                home=Path(temp_home),
            )

        self.assertEqual(1, len(variants))
        self.assertTrue(Path(temp_home).is_absolute())
        self.assertIn("Application\\ Support", variants[0])
        self.assertNotIn("$HOME", variants[0])
        self.assertNotIn("~/", variants[0])

    def test_agy_runtime_bridge_requires_project_discovery_entry(self) -> None:
        required = [
            "If the runtime starts outside the target repo or the target repo is not explicit, run Tao Agent OS agent-entry.py or project-discover.py before project work.",
            "If project discovery returns ambiguous or not_found, ask the user for the target project before routing, editing, testing, committing, or reporting completion.",
        ]
        block = _agy_runtime_bridge_block(ROOT)

        for phrase in required:
            self.assertIn(phrase, AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES)
            self.assertIn(phrase, PREFLIGHT_AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES)
            self.assertIn(phrase, block)

    def test_runtime_bridge_requires_graph_backed_document_routing(self) -> None:
        agy_block = _agy_runtime_bridge_block(ROOT)
        codex_block = runtime_bridge_block(ROOT, "Codex", "AGENTS.md")
        claude_required = runtime_bridge_required_phrases("Claude", "CLAUDE.md")

        for phrase in RUNTIME_BRIDGE_GRAPH_PHRASES:
            self.assertIn(phrase, AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES)
            self.assertIn(phrase, PREFLIGHT_AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES)
            self.assertIn(phrase, claude_required)
            self.assertIn(phrase, agy_block)
            self.assertIn(phrase, codex_block)

    def test_setup_hook_runtime_selection_is_scoped(self) -> None:
        from support.setup_agent_hooks_impl import _runtime_selected

        self.assertTrue(_runtime_selected("codex", set()))
        self.assertTrue(_runtime_selected("codex", {"codex"}))
        self.assertFalse(_runtime_selected("claude", {"codex"}))

    def test_spill_tool_label_prefers_codex_runtime_over_stale_spill_env(self) -> None:
        label = spill_tool_label({"CODEX_SANDBOX": "seatbelt", "SPILL_AI_TOOL": "claude"})

        self.assertEqual("codex", label)

    def test_spill_tool_label_allows_explicit_tao_override(self) -> None:
        label = spill_tool_label({"TAO_AI_TOOL": "agy", "CODEX_SANDBOX": "seatbelt"})

        self.assertEqual("antigravity", label)


if __name__ == "__main__":
    unittest.main()


class SupersededManagedBlockTests(unittest.TestCase):
    """A renamed marker must migrate the old block, not duplicate beside it."""

    def test_write_managed_block_replaces_block_under_a_superseded_marker(self) -> None:
        from support.graphify_tracking import write_managed_block

        block = (
            "# tao-graphify-inputs:start\n"
            ".tao/\n"
            "# tao-graphify-inputs:end"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".graphifyignore"
            path.write_text(
                "node_modules/\n\n"
                "# oldname-graphify-inputs:start\n"
                ".oldname/\n"
                "# oldname-graphify-inputs:end\n\n"
                "dist/\n",
                encoding="utf-8",
            )

            self.assertEqual("installed", write_managed_block(path, block))

            updated = path.read_text(encoding="utf-8")
            self.assertIn("node_modules/", updated)
            self.assertIn("dist/", updated)
            self.assertNotIn("oldname-graphify-inputs", updated)
            self.assertNotIn(".oldname/", updated)
            self.assertEqual(1, updated.count("# tao-graphify-inputs:start"))

    def test_write_managed_block_is_idempotent_for_the_current_marker(self) -> None:
        from support.graphify_tracking import write_managed_block

        block = (
            "# tao-graphify-inputs:start\n"
            ".tao/\n"
            "# tao-graphify-inputs:end"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".graphifyignore"
            self.assertEqual("installed", write_managed_block(path, block))
            self.assertEqual("ok", write_managed_block(path, block))
            self.assertEqual(
                1, path.read_text(encoding="utf-8").count("# tao-graphify-inputs:start")
            )


class ManagedHookLauncherRenameTests(unittest.TestCase):
    """The managed hook must be recognized after the launcher is renamed."""

    def test_spill_bridge_command_matches_regardless_of_launcher_name(self) -> None:
        from support.claude_setup import _is_managed_claude_spill_bridge_command

        installed_under_a_previous_name = (
            "OLDNAME_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL=claude "
            "'/Users/someone/.oldname/bin/oldname-hook' workflow route triage "
            "--request-classified --classification-evidence 'evidence'"
        )
        installed_under_the_current_name = (
            "TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL=claude "
            "'/Users/someone/.tao/bin/tao-hook' workflow route triage "
            "--request-classified --classification-evidence 'evidence'"
        )

        self.assertTrue(
            _is_managed_claude_spill_bridge_command(installed_under_a_previous_name)
        )
        self.assertTrue(
            _is_managed_claude_spill_bridge_command(installed_under_the_current_name)
        )

    def test_unrelated_user_hook_is_not_claimed_as_managed(self) -> None:
        from support.claude_setup import _is_managed_claude_spill_bridge_command

        self.assertFalse(_is_managed_claude_spill_bridge_command("echo hello"))
        self.assertFalse(
            _is_managed_claude_spill_bridge_command(
                "SPILL_AI_TOOL=claude my-own-script.sh --verbose"
            )
        )
