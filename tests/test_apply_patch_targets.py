"""ApplyPatch uses its actual file targets, including every move destination."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_claude_pretool_gate import (
    gate, _decide, _opt_in_project, _require_linked_worktree, _write_preflight,
)
from support.global_state import STATE_HOME_ENV


class ApplyPatchTargetTests(unittest.TestCase):
    def decision(self, cwd, body):
        _, output = _decide({
            "tool_name": "ApplyPatch", "cwd": str(cwd),
            "session_id": "patch-target-test", "tool_input": body,
        })
        return json.loads(output)["hookSpecificOutput"]["permissionDecision"] if output else "allow"

    def test_scratch_patch_from_protected_checkout_needs_no_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp))
            _require_linked_worktree(root)
            text = f"*** Begin Patch\n*** Add File: {tmp}/scratch.py\n+pass\n*** End Patch\n"
            for body in (text, {"patch": text}, {"input": text}):
                with self.subTest(body=type(body).__name__):
                    self.assertEqual("allow", self.decision(root, body))

    def test_all_targets_and_move_destination_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp))
            _require_linked_worktree(root)
            outside = Path(tmp) / "scratch.py"
            inside = root / "source.py"
            for operation in (
                f"*** Add File: {inside}\n+pass",
                f"*** Update File: {inside}\n@@\n-old\n+new",
                f"*** Delete File: {inside}",
                f"*** Update File: {outside}\n*** Move to: {inside}\n@@\n-old\n+new",
            ):
                text = f"*** Begin Patch\n*** Add File: {outside}\n+pass\n{operation}\n*** End Patch"
                with self.subTest(operation=operation):
                    self.assertEqual("deny", self.decision(Path(tmp), {"patch": text}))

    def test_relative_target_resolves_against_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp))
            _require_linked_worktree(root)
            text = "*** Begin Patch\n*** Add File: source.py\n+pass\n*** End Patch"
            self.assertEqual("deny", self.decision(root, {"patch": text}))

    def test_conflicting_file_path_does_not_hide_patch_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp))
            _require_linked_worktree(root)
            text = f"*** Begin Patch\n*** Delete File: {root}/source.py\n*** End Patch"
            self.assertEqual("deny", self.decision(Path(tmp), {
                "file_path": f"{tmp}/scratch.py", "patch": text,
            }))

    def test_unresolved_patch_keeps_existing_checkout_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp))
            _require_linked_worktree(root)
            for body in ({}, {"patch": "invalid"}, {"patch": "*** Begin Patch\n*** End Patch"}):
                self.assertEqual("deny", self.decision(root, body))


class CodexPatchPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        environment = patch.dict(os.environ, {
            "TAO_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: str(self.base / "state"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.main = _opt_in_project(self.base / "main")
        _require_linked_worktree(self.main)
        policy = self.main / gate.WORKTREE_POLICY_PATH
        policy.write_text(json.dumps({**json.loads(policy.read_text()), "require_workflow_entry": True}))
        (self.main / ".gitignore").write_text(".tao/\n")
        self.worktree = self.base / "worktree"
        for args in (
            ("init", "-b", "main"),
            ("add", "AGENTS.md", ".gitignore", str(gate.WORKTREE_POLICY_PATH)),
            ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"),
            ("worktree", "add", str(self.worktree), "-b", "task"),
        ):
            subprocess.run(["git", "-C", str(self.main), *args], check=True, capture_output=True)
        self.session = "native-patch-session"

    def verdict(self, cwd, text, body=None):
        _, output = _decide({
            "tool_name": "apply_patch", "cwd": str(cwd), "session_id": self.session,
            "tool_input": {"command": text} if body is None else body,
        })
        return json.loads(output)["hookSpecificOutput"] if output else {}

    def test_native_patch_into_main_is_denied_from_main_and_elsewhere(self):
        text = f"*** Begin Patch\n*** Add File: {self.main}/source.py\n+pass\n*** End Patch"
        for cwd in (self.main, self.base, self.worktree):
            with self.subTest(cwd=cwd):
                verdict = self.verdict(cwd, text)
                self.assertEqual("deny", verdict.get("permissionDecision"))
                self.assertIn("worktree", verdict["permissionDecisionReason"])

    def test_each_patch_operation_and_move_destination_is_protected(self):
        _write_preflight(self.worktree, self.session, runtime="codex")
        inside, outside = self.main / "source.py", self.worktree / "source.py"
        for operation in (
            f"*** Add File: {inside}\n+pass",
            f"*** Update File: {inside}\n@@\n-old\n+new",
            f"*** Delete File: {inside}",
            f"*** Update File: {outside}\n*** Move to: {inside}\n@@\n-old\n+new",
        ):
            text = f"*** Begin Patch\n*** Add File: {outside}\n+pass\n{operation}\n*** End Patch"
            with self.subTest(operation=operation):
                self.assertEqual("deny", self.verdict(self.worktree, text).get("permissionDecision"))

    def test_missing_run_and_another_sessions_run_do_not_authorize_edits(self):
        text = "*** Begin Patch\n*** Add File: source.py\n+pass\n*** End Patch"
        self.assertEqual("deny", self.verdict(self.worktree, text).get("permissionDecision"))
        _write_preflight(self.worktree, "other-session", runtime="codex")
        self.assertEqual("deny", self.verdict(self.worktree, text).get("permissionDecision"))

    def test_valid_session_run_allows_native_patch_without_operator_question(self):
        _write_preflight(self.worktree, self.session, runtime="codex")
        text = "*** Begin Patch\n*** Add File: source.py\n+pass\n*** End Patch"
        self.assertEqual({}, self.verdict(self.worktree, text))

    def test_read_only_run_denies_native_patch(self):
        _write_preflight(self.worktree, self.session, runtime="codex", read_only=True)
        text = "*** Begin Patch\n*** Add File: source.py\n+pass\n*** End Patch"
        verdict = self.verdict(self.worktree, text)
        self.assertEqual("deny", verdict.get("permissionDecision"))
        self.assertIn("read-only", verdict["permissionDecisionReason"])

    def test_native_payload_shapes_resolve_actual_targets_over_file_path(self):
        text = f"*** Begin Patch\n*** Delete File: {self.main}/source.py\n*** End Patch"
        for body in (text, {"input": text}, {"patch": text}, {"command": text},
                     {"command": text, "file_path": str(self.base / "scratch.py")}):
            with self.subTest(body=body):
                self.assertEqual("deny", self.verdict(self.base, text, body).get("permissionDecision"))

    def test_scratch_patch_from_main_remains_allowed(self):
        text = f"*** Begin Patch\n*** Add File: {self.base}/scratch.py\n+pass\n*** End Patch"
        self.assertEqual({}, self.verdict(self.main, text))

    def test_malformed_patch_does_not_allow_main_edits(self):
        for body in ({}, {"command": "invalid"}, {"command": "*** Begin Patch\n*** End Patch"}):
            with self.subTest(body=body):
                self.assertEqual("deny", self.verdict(self.main, "", body).get("permissionDecision"))

    def test_codex_adapter_blocks_main_and_allows_the_bound_worktree(self):
        _write_preflight(self.worktree, self.session, runtime="codex")
        environment = {**os.environ, "CODEX_THREAD_ID": self.session}
        adapter = Path(__file__).resolve().parents[1] / "scripts" / "codex_pretool_gate.py"
        for cwd, target, expected in ((self.main, self.main, "deny"),
                                      (self.main, self.worktree, "allow")):
            payload = {"tool_name": "apply_patch", "cwd": str(cwd), "session_id": self.session,
                       "tool_input": {"command": f"*** Begin Patch\n*** Add File: {target}/source.py\n+pass\n*** End Patch"}}
            result = subprocess.run([sys.executable, str(adapter)], input=json.dumps(payload),
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            verdict = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else {}
            self.assertEqual(expected, verdict.get("permissionDecision", "allow"))
            self.assertNotIn("operator decision", result.stdout)
