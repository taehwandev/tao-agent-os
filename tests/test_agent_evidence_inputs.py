import tempfile
import unittest
from pathlib import Path

from tests import test_agent_gate_reuse as fixture
from agent_evidence_inputs import EvidenceInputs


class EvidenceInputsTests(unittest.TestCase):
    def test_safe_paths_absence_and_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            absent = EvidenceInputs.capture(root, ["input"])
            (root / "input").write_text("")
            self.assertNotEqual(absent, EvidenceInputs.capture(root, ["input"]))
            before = EvidenceInputs.capture(root, ["input"])
            (root / "input").write_text("changed")
            self.assertNotEqual(before, EvidenceInputs.capture(root, ["input"]))
            for invalid in (["../escape"], [str(root / "input")], [".git/config"], ["."]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    EvidenceInputs.capture(root, invalid)
            (root / "link").symlink_to(root / "input")
            with self.assertRaises(ValueError):
                EvidenceInputs.capture(root, ["link"])

    def test_delete_commit_does_not_change_final_content_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            git = fixture.GateEvidenceReuseTests.git
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "user.name", "Test")
            (root / "input").write_text("old")
            git(root, "add", ".")
            git(root, "commit", "-qm", "baseline")
            (root / "input").unlink()
            before = EvidenceInputs.capture(root, [])
            git(root, "add", "-u")
            git(root, "commit", "-qm", "deletion")
            self.assertEqual(before, EvidenceInputs.capture(root, []))
