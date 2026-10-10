"""A finished worktree run admits the push of its commit from the main checkout.

A session finishes in a linked worktree with publication authority,
fast-forwards main to that commit, and pushes from the main checkout. The
pushing checkout holds no finished run, so the push used to need a second
lifecycle there for a commit already reviewed and attested.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_pretool_finished_admission as admission
import claude_pretool_gate as gate
from agent_publication_admission import PublicationAdmission


class FinishedCheckoutPushTests(unittest.TestCase):
    SESSION = "cross-checkout-push-session"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.main = Path(self.temp.name).resolve() / "main"
        self.main.mkdir()
        self.git(self.main, "init", "-q", "-b", "main")
        self.git(self.main, "config", "user.email", "test@example.invalid")
        self.git(self.main, "config", "user.name", "Test")
        (self.main / ".gitignore").write_text(".tao/\n")
        (self.main / "source").write_text("original")
        self.git(self.main, "add", ".")
        self.git(self.main, "commit", "-qm", "base")
        self.worktree = self.main / ".tao" / "worktrees" / "slice"
        self.git(self.main, "worktree", "add", "-q", "-b", "slice", str(self.worktree))
        self.worktree = self.worktree.resolve()
        (self.worktree / ".tao").mkdir(exist_ok=True)
        (self.worktree / ".tao" / "run-registry.json").write_text('{"runs": []}')
        self.evidence = self.worktree / ".tao" / "runs" / "example" / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.main_evidence: "Path | None" = None
        self.session = self.SESSION

    def git(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True,
        ).stdout

    def finish(self, project: Path, evidence: Path, effect: str) -> None:
        evidence.write_text(json.dumps({
            "rules": str(project),
            "route": {"request_classification": {"intent_envelope": {
                "authority": "envelope", "schema_valid": True,
                "failures": [], "effective_effect": effect,
            }}},
        }))
        assert PublicationAdmission.record_finish(project, evidence)

    def finish_slice_and_integrate(self, effect: str = "external_write") -> str:
        (self.worktree / "source").write_text("reviewed change")
        self.finish(self.worktree, self.evidence, effect)
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-qm", "slice work")
        self.git(self.main, "merge", "-q", "--ff-only", "slice")
        return self.git(self.worktree, "rev-parse", "HEAD").strip()

    def lookup(self, root: Path, session_id: str) -> "Path | None":
        if session_id != self.session:
            return None
        if Path(root).resolve() == self.worktree:
            return self.evidence
        if Path(root).resolve() == self.main:
            return self.main_evidence
        return None

    def admits(self, command: str) -> bool:
        with patch.object(gate, "finished_session_evidence", self.lookup):
            return gate.publishes_finished_command(self.main, self.SESSION, command, self.main)

    def test_push_of_the_worktree_finished_commit_is_admitted(self) -> None:
        self.finish_slice_and_integrate()
        self.assertTrue(self.admits("git push origin main"))
        note = admission.cross_checkout_note()
        self.assertIn("run example", note)
        self.assertIn(str(self.worktree), note)

    def test_plain_push_and_explicit_destination_name_the_same_commit(self) -> None:
        self.finish_slice_and_integrate()
        for command in ("git push", "git push origin", "git push -u origin main:main",
                        "git push origin main && git status"):
            with self.subTest(command=command):
                self.assertTrue(self.admits(command))

    def test_an_extra_unattested_commit_on_main_is_refused(self) -> None:
        self.finish_slice_and_integrate()
        (self.main / "other").write_text("unreviewed")
        self.git(self.main, "add", "-A")
        self.git(self.main, "commit", "-qm", "extra")
        self.assertFalse(self.admits("git push origin main"))

    def test_a_finish_without_external_write_is_refused(self) -> None:
        self.finish_slice_and_integrate(effect="git_write")
        self.assertFalse(self.admits("git push origin main"))

    def test_another_session_cannot_reuse_the_finish(self) -> None:
        self.finish_slice_and_integrate()
        self.session = "another-session"
        self.assertFalse(self.admits("git push origin main"))

    def test_a_stale_finish_is_refused(self) -> None:
        self.finish_slice_and_integrate()
        os.utime(self.evidence.with_name("publication.json"), (0, 0))
        self.assertFalse(self.admits("git push origin main"))

    def test_an_edit_in_the_worktree_after_finish_is_refused(self) -> None:
        self.finish_slice_and_integrate()
        (self.worktree / "source").write_text("edited after finish")
        self.assertFalse(self.admits("git push origin main"))

    def test_other_push_shapes_are_refused(self) -> None:
        self.finish_slice_and_integrate()
        for command in ("git push --force origin main", "git push origin +main",
                        "git push --tags origin", "git push origin 'main*'",
                        "git push origin main slice", "git push origin HEAD~1",
                        "git -C . push origin main", "git push --all origin"):
            with self.subTest(command=command):
                self.assertFalse(self.admits(command))

    def test_the_same_checkout_admission_is_unchanged(self) -> None:
        self.main_evidence = self.main / ".tao" / "runs" / "own" / "preflight.json"
        self.main_evidence.parent.mkdir(parents=True)
        (self.main / "source").write_text("main change")
        self.finish(self.main, self.main_evidence, "external_write")
        self.assertTrue(self.admits("git push origin main"))
        self.assertEqual(admission.cross_checkout_note(), "")


if __name__ == "__main__":
    unittest.main()
