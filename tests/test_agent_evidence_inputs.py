import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_agent_gate_reuse as fixture
from agent_evidence_inputs import EvidenceInputs


class EvidenceInputsTests(unittest.TestCase):
    def test_byte_budget_can_be_scoped_without_changing_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "input").write_text("reviewed")
            with self.assertRaisesRegex(ValueError, "input snapshot exceeds byte limit"):
                EvidenceInputs.capture(root, ["input"], max_bytes=1)
            self.assertEqual(64, len(EvidenceInputs.capture(root, ["input"])))

    def test_read_access_time_change_does_not_invalidate_capture(self):
        self._capture_with_stat_change("st_atime_ns", succeeds=True)

    def test_identity_or_write_time_change_invalidates_capture(self):
        for field in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"):
            with self.subTest(field=field):
                self._capture_with_stat_change(field, succeeds=False)

    def _capture_with_stat_change(self, field, *, succeeds):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "input"
            source.write_text("stable contents")
            expected = EvidenceInputs.capture(root, ["input"])
            baseline = source.stat()
            original_open, original_stat = Path.open, Path.stat
            read_started = False

            def open_file(path, *args, **kwargs):
                nonlocal read_started
                stream = original_open(path, *args, **kwargs)
                if path == source:
                    read_started = True
                return stream

            def stat_file(path, *args, **kwargs):
                if path == source:
                    values = {name: getattr(baseline, name) for name in dir(baseline) if name.startswith("st_")}
                    if read_started:
                        values[field] += 1
                    return SimpleNamespace(**values)
                return original_stat(path, *args, **kwargs)

            with patch.object(Path, "open", open_file), patch.object(Path, "stat", stat_file):
                if succeeds:
                    self.assertEqual(expected, EvidenceInputs.capture(root, ["input"]))
                else:
                    with self.assertRaisesRegex(ValueError, "input changed during capture"):
                        EvidenceInputs.capture(root, ["input"])

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
            # A symlink is identified by the target it names, as Git stores it,
            # and is never followed: refusing it made every repository holding
            # one unable to capture a scoped snapshot at all.
            (root / "link").symlink_to(root / "input")
            linked = EvidenceInputs.capture(root, ["link"])
            self.assertNotEqual(EvidenceInputs.capture(root, ["input"]), linked)
            (root / "link").unlink()
            (root / "link").symlink_to(root / "other")
            self.assertNotEqual(linked, EvidenceInputs.capture(root, ["link"]))
            (root / "directory").mkdir()
            (root / "directory" / "input").write_text("reached through a link")
            (root / "through").symlink_to(root / "directory")
            with self.assertRaises(ValueError):
                EvidenceInputs.capture(root, ["through/input"])

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
