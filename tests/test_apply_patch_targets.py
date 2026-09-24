"""ApplyPatch uses its actual file targets, including every move destination."""
import json
import tempfile
import unittest
from pathlib import Path

from test_claude_pretool_gate import _decide, _opt_in_project, _require_linked_worktree


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
