"""Project-specific isolation scenarios at policy and PreToolUse boundaries."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import claude_pretool_gate as pretool
import claude_worktree_gate as gate


class ProjectWorktreePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def project(self, name: str) -> Path:
        root = self.base / name
        (root / ".git").mkdir(parents=True)
        (root / "AGENTS.md").write_text("Uses tao-hook.\n")
        return root

    def test_codex_refusal_explains_lost_workdir_without_restarting_a_bound_task(self):
        os.environ["TAO_PRETOOL_RUNTIME"] = "codex"
        reason = gate.worktree_deny_reason(self.base, "main")
        self.assertIn("workdir", reason)
        self.assertIn('git -C "<worktree>"', reason)
        self.assertIn('cd "<worktree>" && <command>', reason)
        self.assertNotIn("restart the workflow", reason)
        self.assertIn("sandbox", reason)

    def test_explicit_codex_worktree_command_targets_preserve_main_protection(self):
        os.environ["TAO_PRETOOL_RUNTIME"] = "codex"
        main = self.project("main")
        worktree = self.project("task with spaces")
        (worktree / ".git").rmdir()
        (worktree / ".git").write_text("gitdir: /unused/test-metadata\n")
        self.policy(main)
        self.policy(worktree)
        for command, allowed in (
            ("git add code.py", False),
            (f'git -C "{worktree}" add code.py', True),
            (f'cd "{worktree}" && python3 build.py', True),
            (f'git -C "{main}" add code.py', False),
            (f'cd "{worktree}" && python3 "{main}/mutate.py"', False),
        ):
            with self.subTest(command=command):
                output = io.StringIO()
                with redirect_stdout(output):
                    pretool.decide({
                        "tool_name": "Bash", "cwd": str(main),
                        "session_id": "codex-worktree",
                        # Codex 0.155.1 sends command only; exec workdir is lost.
                        "tool_input": {"command": command},
                    })
                if allowed:
                    self.assertEqual("", output.getvalue())
                else:
                    decision = json.loads(output.getvalue())["hookSpecificOutput"]
                    self.assertEqual("deny", decision["permissionDecision"])
                    self.assertIn("worktree gate", decision["permissionDecisionReason"])

    def policy(self, root: Path, *, linked=True, branches=None) -> dict:
        policy = {
            "schema_version": 1,
            "require_linked_worktree": linked,
            "protected_branches": ["main"] if branches is None else branches,
        }
        destination = root / gate.WORKTREE_POLICY_PATH
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(policy))
        return policy

    def test_launcher_alias_start_reads_shared_rules_without_allowing_main_writes(self):
        main = self.project("main")
        worktree = self.project("feature")
        (worktree / ".git").rmdir()
        (worktree / ".git").write_text("gitdir: /unused/test-metadata\n")
        self.policy(main)
        self.policy(worktree)
        launcher = gate.stable_launcher_path()
        for spelling in ("start", "agent-hook start"):
            base = f"{launcher} {spelling} --rules {main} --project"
            for command, allowed in (
                (f"{base} {worktree}", True),
                (f"cd {worktree} && {base} {worktree}", True),
                (f"{base} {main}", False),
                (f"{base} {worktree} --output {main}/evidence.json", False),
                (f"{base} {worktree} && touch {main}/code.py", False),
                (f"{base} {worktree} > {main}/output", False),
            ):
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        pretool.decide({
                            "tool_name": "Bash", "cwd": str(main),
                            "session_id": "alias-start",
                            "tool_input": {"command": command},
                        })
                    if allowed:
                        self.assertEqual("", output.getvalue())
                    else:
                        decision = json.loads(output.getvalue())["hookSpecificOutput"]
                        self.assertEqual("deny", decision["permissionDecision"])

    def edit(self, source: Path, target: Path) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            pretool.decide({
                "tool_name": "Edit", "cwd": str(source), "session_id": "policy-test",
                "tool_input": {"file_path": str(target / "code.py")},
            })
        return output.getvalue()

    def test_unbound_environment_does_not_impose_source_policy_on_external_project(self):
        target = self.project("external")
        os.environ[gate.REQUIRE_LINKED_WORKTREE_ENV] = "1"
        self.assertIsNone(gate.worktree_policy(target))
        self.assertIsNone(gate.worktree_denial(target))

    def test_bound_environment_still_protects_origin_but_not_another_project(self):
        source, target = self.project("source"), self.project("external")
        os.environ.update({gate.REQUIRE_LINKED_WORKTREE_ENV: "1", "CLAUDE_PROJECT_DIR": str(source)})
        self.assertIsNotNone(gate.worktree_denial(source))
        self.assertIsNone(gate.worktree_denial(target))

    def test_local_false_policy_overrides_environment_and_allows_feature_branch_edit(self):
        target = self.project("external")
        declared = self.policy(target, linked=False)
        os.environ.update({gate.REQUIRE_LINKED_WORKTREE_ENV: "1", "CLAUDE_PROJECT_DIR": str(target)})
        with patch.object(gate, "current_branch", return_value="feature/change"):
            self.assertEqual(declared, gate.worktree_policy(target))
            self.assertEqual("", self.edit(target, target))

    def test_false_isolation_keeps_target_protected_branch_restriction(self):
        target = self.project("external")
        self.policy(target, linked=False, branches=["release"])
        with patch.object(gate, "current_branch", return_value="release"):
            refusal = self.edit(target, target)
        self.assertIn("protected branch `release`", refusal)
        with patch.object(gate, "current_branch", return_value="main"):
            self.assertEqual("", self.edit(target, target))

    def test_project_can_explicitly_choose_no_worktree_or_branch_restrictions(self):
        target = self.project("external")
        declared = self.policy(target, linked=False, branches=[])
        with patch.object(gate, "current_branch", return_value="main"):
            self.assertEqual(declared, gate.worktree_policy(target))
            self.assertEqual("", self.edit(target, target))

    def test_explicit_edit_target_uses_its_policy_while_source_stays_protected(self):
        source, target = self.project("source"), self.project("external")
        self.policy(source)
        self.policy(target, linked=False)
        os.environ.update({gate.REQUIRE_LINKED_WORKTREE_ENV: "1", "CLAUDE_PROJECT_DIR": str(source)})
        with patch.object(gate, "current_branch", return_value="feature/change"):
            self.assertEqual("", self.edit(source, target))
            self.assertIn("worktree gate", self.edit(target, source))

    def test_malformed_false_values_still_fail_closed(self):
        for number, value in enumerate(("false", 0, None)):
            with self.subTest(value=value):
                target = self.project(f"invalid-{number}")
                self.policy(target, linked=value)
                self.assertEqual(gate.default_worktree_policy(), gate.worktree_policy(target))
                self.assertIn("worktree gate", self.edit(target, target))

    def test_false_isolation_does_not_waive_explicit_workflow_entry(self):
        target = self.project("external")
        declared = self.policy(target, linked=False)
        declared["require_workflow_entry"] = True
        (target / gate.WORKTREE_POLICY_PATH).write_text(json.dumps(declared))
        with patch.object(gate, "current_branch", return_value="feature/change"):
            refusal = self.edit(target, target)
        decision = json.loads(refusal)["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertNotIn("worktree gate", decision["permissionDecisionReason"])

    def test_workflow_start_from_protected_source_respects_explicit_target_policy(self):
        source, target = self.project("source"), self.project("external")
        self.policy(source)
        self.policy(target, linked=False)
        output = io.StringIO()
        with patch.object(gate, "current_branch", return_value="feature/change"), redirect_stdout(output):
            pretool.decide({
                "tool_name": "Bash", "cwd": str(source), "session_id": "policy-test",
                "tool_input": {
                    "command": f"{gate.stable_launcher_path()} start --project {target}",
                },
            })
        self.assertEqual("", output.getvalue())

    def test_explicit_ungoverned_target_is_not_forced_into_source_workflow(self):
        source = self.project("source")
        self.policy(source)
        target = self.base / "plain-project"
        (target / ".git").mkdir(parents=True)
        os.environ[gate.REQUIRE_LINKED_WORKTREE_ENV] = "1"
        self.assertEqual("", self.edit(source, target))

    def test_required_isolation_still_blocks_linked_checkout_on_protected_branch(self):
        target = self.project("source")
        self.policy(target)
        (target / ".git").rmdir()
        (target / ".git").write_text("gitdir: ../common/worktrees/task\n")
        with patch.object(gate, "current_branch", return_value="main"):
            self.assertIn("protected branch `main`", self.edit(target, target))
        with patch.object(gate, "current_branch", return_value="feature/change"):
            self.assertEqual("", self.edit(target, target))


if __name__ == "__main__":
    unittest.main()
