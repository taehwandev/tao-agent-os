"""Workflow labels follow successful work, not advisory prompt retrieval."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get("TAO_TEST_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_spill
from workflow_catalog import SPILL_ROUTE_LABELS

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

workflow = load("workflow_labels_cli", "workflow.py")
preflight = load("preflight_labels_cli", "agent-preflight.py")

class WorkflowLabelTests(unittest.TestCase):
    def call(self, argv, outcome=0):
        with patch.object(workflow, "_dispatch_action", return_value=outcome), \
             patch.object(workflow, "print_supported_values"), \
             patch.object(workflow, "write_spill_label") as writer, \
             contextlib.redirect_stdout(io.StringIO()):
            result = workflow.main(argv)
        return result, writer

    def test_each_prompt_advisory_preserves_actual_task_label(self):
        result, writer = self.call(["route", "triage", "--advisory", "--hook-stdin"])
        self.assertEqual(0, result)
        writer.assert_not_called()

    def test_successful_work_route_replaces_fallback(self):
        for command, expected in (("bugfix", ("debugging", "implement")),
                                  ("commit", ("git_commit", "implement")),
                                  ("review", ("code_review", "verify"))):
            with self.subTest(command=command):
                result, writer = self.call(["route", command, "--request", "Scoped work"])
                self.assertEqual(0, result)
                writer.assert_called_once_with(*expected, if_absent=False)

    def test_failed_route_does_not_change_context(self):
        result, writer = self.call(["route", "bugfix", "--request", "Scoped work"], 2)
        self.assertEqual(2, result)
        writer.assert_not_called()

    def test_discovery_keeps_active_workflow_label(self):
        result, writer = self.call(["list"])
        self.assertEqual(0, result)
        writer.assert_called_once_with("analysis", "classify", if_absent=True)

class PreflightLabelTests(unittest.TestCase):
    def call(self, command, failures, ledger_failure=False):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            project = Path(directory)
            evidence = project / "preflight.json"
            argv = ["agent-preflight.py", "--project", directory, "--rules", str(ROOT),
                    "--command", command, "--request", "Scoped local correction"]
            route = {"command": command, "gates": [], "required_docs": []}
            overrides = {
                "resolve_evidence_path": evidence,
                "active_runtime_label": "codex",
                "run_command": {"returncode": 0, "stdout": "", "stderr": ""},
                "is_git_status_review_only": False,
                "route_result": {"returncode": 0, "stdout": __import__("json").dumps(route)},
                "claim_worker_evidence_reservation": None,
                "cached_vibeguard": {"overall": {"status": "Ready"}},
                "skipped_vibeguard": {"overall": {"status": "Skipped"}},
                "lesson_summary": {"accepted": [], "promoted": [], "candidate_count": 0},
                "runtime_session": {"runtime": "codex", "session_id": "opaque"},
                "check_agent_hooks": ([], []),
                "collect_failures": failures,
                "create_preflight_snapshot": {},
                "_attach_project_route_docs": None,
                "reset_and_record_preflight_gate": None,
                "skill_backlog_summary": {},
                "format_skill_backlog": None,
            }
            for name, value in overrides.items():
                if name == "reset_and_record_preflight_gate" and ledger_failure:
                    stack.enter_context(patch.object(preflight, name, side_effect=RuntimeError("ledger initialization failed")))
                else:
                    stack.enter_context(patch.object(preflight, name, return_value=value))
            writer = stack.enter_context(patch.object(preflight, "write_spill_label"))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            result = preflight.main()
        return result, writer

    def test_in_process_start_labels_the_resolved_work_route(self):
        for command in ("bugfix", "commit", "review"):
            with self.subTest(command=command):
                result, writer = self.call(command, [])
                self.assertEqual(0, result)
                writer.assert_called_once_with(*SPILL_ROUTE_LABELS[command])

    def test_failed_preflight_preserves_previous_label(self):
        result, writer = self.call("bugfix", ["blocked preflight"])
        self.assertEqual(1, result)
        writer.assert_not_called()

    def test_ledger_initialization_failure_does_not_publish_task_label(self):
        result, writer = self.call("bugfix", [], ledger_failure=True)
        self.assertEqual(1, result)
        writer.assert_not_called()

class HelperLabelTests(unittest.TestCase):
    def test_runtime_and_priority_reach_the_real_helper_command(self):
        for tool in ("claude", "codex"):
            for fallback in (False, True):
                with self.subTest(tool=tool, fallback=fallback), tempfile.NamedTemporaryFile() as helper, \
                     patch.dict(os.environ, {"SPILL_AI_TOOL": tool}, clear=True), \
                     patch.object(workflow_spill, "spill_setup_helper_path", return_value=Path(helper.name)), \
                     patch.object(workflow_spill.subprocess, "run") as run:
                    workflow_spill.write_spill_label("debugging", "implement", if_absent=fallback)
                    command = run.call_args.args[0]
                    self.assertEqual(tool, command[command.index("--label") + 1])
                    self.assertEqual(fallback, "--if-absent" in command)
                    self.assertEqual(2, run.call_args.kwargs["timeout"])

    def test_missing_helper_is_optional(self):
        with patch.object(workflow_spill, "has_spill_setup_helper", return_value=False), \
             patch.object(workflow_spill, "spill_setup_helper_path", return_value=Path("/nonexistent/spill")), \
             patch.object(workflow_spill.subprocess, "run") as run:
            workflow_spill.write_spill_label("debugging", "implement")
        run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
