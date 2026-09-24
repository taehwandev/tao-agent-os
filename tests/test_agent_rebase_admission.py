import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.test_agent_publication_admission import PublicationAdmission, gate
from agent_rebase_admission import rebase_continuation_shape


class RebaseAdmissionTests(unittest.TestCase):
    flags = ["--no-update-refs", "--no-autostash", "--no-autosquash"]

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.main = Path(temp.name).resolve() / "main"
        self.main.mkdir()
        self.git(self.main, "init", "-qb", "main")
        self.git(self.main, "config", "user.name", "Test")
        self.git(self.main, "config", "user.email", "test@example.invalid")
        (self.main / ".gitignore").write_text(".tao/\n")
        (self.main / "base.txt").write_text("base")
        (self.main / "AGENTS.md").write_text("Uses tao-hook.\n")
        policy = self.main / gate.WORKTREE_POLICY_PATH
        policy.parent.mkdir(parents=True)
        policy.write_text(json.dumps({"schema_version": 1, "require_linked_worktree": True,
                                     "require_workflow_entry": True, "protected_branches": ["main"]}))
        self.git(self.main, "add", ".")
        self.git(self.main, "commit", "-qm", "base")
        self.root = self.main.parent / "task"
        self.git(self.main, "worktree", "add", "-qb", "task", str(self.root))
        (self.root / "task.txt").write_text("tested task")
        self.git(self.root, "add", ".")
        self.git(self.root, "commit", "-qm", "task")
        self.evidence = self.root / ".tao/runs/test/preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.evidence.write_text(json.dumps({"rules": str(self.root), "route": {
            "request_classification": {"intent_envelope": {
                "authority": "envelope", "schema_valid": True, "failures": [],
                "effective_effect": "git_write"}}}}))
        self.assertTrue(PublicationAdmission.record_finish(self.root, self.evidence))
        self.command = shlex.join(["git", "rebase", *self.flags, "main"])

    @staticmethod
    def git(root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout

    def admitted(self, command=None):
        with patch.object(gate, "finished_session_evidence", return_value=self.evidence):
            return gate.publishes_finished_command(self.root, "session", command or self.command, self.root)

    def test_unchanged_rebase_continues_without_new_finish(self):
        self.git(self.main, "commit", "--allow-empty", "-qm", "upstream metadata")
        self.assertTrue(self.admitted())
        self.git(self.root, "rebase", *self.flags, "main")
        self.assertTrue(PublicationAdmission.allows(self.root, self.evidence, "git_write"))

    def test_real_gate_admits_only_lone_rebase_with_current_receipt(self):
        from tests.test_claude_pretool_gate import _decide, gate as entry_gate
        with patch.object(entry_gate, "finished_session_evidence", return_value=self.evidence):
            payload = {"tool_name": "Bash", "cwd": str(self.root), "session_id": "session",
                       "tool_input": {"command": self.command}}
            self.assertIn('"permissionDecision": "allow"', _decide(payload)[1])
            payload["tool_input"]["command"] += " && git push"
            self.assertIn('"permissionDecision": "deny"', _decide(payload)[1])
            payload["tool_input"]["command"] = self.command
            self.evidence.with_name("publication.json").unlink()
            self.assertIn('"permissionDecision": "deny"', _decide(payload)[1])

    def test_changed_upstream_requires_new_review_after_rebase(self):
        (self.main / "base.txt").write_text("changed dependency")
        self.git(self.main, "add", ".")
        self.git(self.main, "commit", "-qm", "upstream input")
        self.assertTrue(self.admitted())
        self.git(self.root, "rebase", *self.flags, "main")
        self.assertEqual("project_changed", PublicationAdmission.refusal(self.root, self.evidence, "git_write"))

    def test_no_general_rebase_or_chained_publication_authority(self):
        for command in (
            "git rebase main", "git rebase --continue", "git rebase -i main",
            self.command + " && git push", self.command + " && git commit -am changed",
            self.command + " && " + self.command, self.command + " > output",
            "env GIT_CONFIG_COUNT=1 " + self.command,
            self.command + " another-branch", self.command.replace("--no-update-refs", "--update-refs"),
        ):
            with self.subTest(command=command):
                self.assertFalse(self.admitted(command))
        self.assertFalse(rebase_continuation_shape(self.main, [*self.flags, "task"], {"main"}))
        self.assertFalse(rebase_continuation_shape(self.root, [*self.flags, "main"], {"task"}))
        self.evidence.with_name("publication.json").unlink()
        self.assertFalse(self.admitted())

    def test_dirty_or_detached_worktree_is_not_admitted(self):
        (self.root / "new-file").write_text("unreviewed")
        self.assertFalse(self.admitted())
        (self.root / "new-file").unlink()
        self.git(self.root, "checkout", "--detach")
        self.assertFalse(self.admitted())
