"""Scratch exemptions follow file destinations and retain ancestor ownership."""

from unittest.mock import patch

from tests.test_claude_temp_checkout_scratch import _Fixture, _git, syntax


class ScratchTargetTests(_Fixture):
    def patch_decision(self, operation):
        return self._decision({
            "tool_name": "ApplyPatch", "cwd": str(self.bench),
            "tool_input": {"patch": f"*** Begin Patch\n{operation}\n*** End Patch"},
        })

    def test_edit_tools_follow_a_file_link_to_the_original_project(self):
        link = self.bench / "linked.txt"
        link.symlink_to(self.project / "notes.txt")
        for tool, field in (("Write", "file_path"), ("Edit", "file_path"),
                            ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                self.assertEqual("deny", self._decision({
                    "tool_name": tool, "cwd": str(self.bench),
                    "tool_input": {field: str(link), "content": "changed"},
                }))
        self.assertEqual("n\n", (self.project / "notes.txt").read_text())

    def test_patch_writes_and_move_destinations_follow_file_links(self):
        (self.bench / "linked.txt").symlink_to(self.project / "notes.txt")
        for operation in (
            "*** Update File: linked.txt\n@@\n-n\n+changed",
            "*** Add File: linked.txt\n+changed",
            "*** Update File: notes.txt\n*** Move to: linked.txt\n@@\n-n\n+changed",
            "*** Add File: local.txt\n+local\n*** Update File: linked.txt\n@@\n-n\n+changed",
        ):
            with self.subTest(operation=operation):
                self.assertEqual("deny", self.patch_decision(operation))

    def test_deleting_a_scratch_file_link_does_not_write_its_referent(self):
        (self.bench / "linked.txt").symlink_to(self.project / "notes.txt")
        self.assertEqual("allow", self.patch_decision("*** Delete File: linked.txt"))

    def test_dangling_link_into_original_project_is_still_governed(self):
        link = self.bench / "linked.txt"
        link.symlink_to(self.project / "new.txt")
        self.assertEqual("deny", self._edit(link, cwd=self.bench))
        self.assertEqual("deny", self.patch_decision("*** Add File: linked.txt\n+changed"))

    def test_links_within_scratch_and_plain_scratch_writes_still_work(self):
        link = self.bench / "linked.txt"
        link.symlink_to(self.bench / "notes.txt")
        self.assertEqual("allow", self._edit(link, cwd=self.bench))
        self.assertEqual("allow", self.patch_decision("*** Update File: linked.txt\n@@\n-n\n+changed"))
        self.assertEqual("allow", self._edit(self.bench / "new.txt", cwd=self.bench))

    def test_unresolved_edits_do_not_acquire_the_scratch_exemption(self):
        first, second = self.bench / "first", self.bench / "second"
        first.symlink_to(second)
        second.symlink_to(first)
        self.assertEqual("deny", self._edit(first, cwd=self.bench))
        self.assertEqual("deny", self.patch_decision("*** Update File: first\n@@\n-a\n+b"))
        self.assertEqual("deny", self._decision({
            "tool_name": "ApplyPatch", "cwd": str(self.bench),
            "tool_input": {"patch": "unreadable"},
        }))

    def test_temp_root_inside_a_project_cannot_hide_ancestor_ownership(self):
        nested_temp = self.project / "scratch"
        nested_temp.mkdir()
        nested = nested_temp / "bench"
        _git("worktree", "add", "--detach", str(nested), cwd=self.project)
        with patch.object(syntax, "scratch_roots", lambda: [nested_temp]):
            self.assertFalse(syntax.scratch_write_target(str(nested / "notes.txt"), nested))
            self.assertEqual("deny", self._edit(nested / "notes.txt", cwd=nested))
            self.assertEqual("deny", self.patch_decision(f"*** Add File: {nested / 'new.txt'}\n+changed"))
