"""Regression checks for structural braces versus quoted/comment text."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_review_structure import large_block_failures


class BraceReviewTests(unittest.TestCase):
    def test_quoted_open_brace_does_not_absorb_following_file(self):
        lines = ["function parseCursor(value: string) {",
                 "  if (value.startsWith('{')) return null;", "  return value;", "}"]
        lines += ["const other = 1;"] * 130
        self.assertEqual([], large_block_failures(Path("cursor.ts"), lines, 120))

    def test_quoted_close_brace_cannot_hide_an_oversized_function(self):
        lines = ['function longTask() {', '  const delimiter = "}";']
        lines += ['  work();'] * 125 + ['}']
        findings = large_block_failures(Path("task.ts"), lines, 120)
        self.assertEqual(1, len(findings))
        self.assertIn("spans 128 lines", findings[0])

    def test_comments_and_escaped_quotes_preserve_real_block_span(self):
        lines = ['function task() {', '  // }', '  /* }', '  } */',
                 r'  const value = "escaped \" }";', "  const other = 'it\\\'s }';"]
        lines += ['  work();'] * 125 + ['}']
        self.assertEqual(1, len(large_block_failures(Path("task.ts"), lines, 120)))

    def test_comment_function_text_is_not_a_block(self):
        lines = ['/*', 'function fake() {'] + ['explanation'] * 130 + ['*/']
        self.assertEqual([], large_block_failures(Path("task.ts"), lines, 120))

    def test_object_literals_still_count_as_structural_braces(self):
        lines = ['function task() {', '  const value = { nested: { value: 1 } };']
        lines += ['  work();'] * 125 + ['}']
        self.assertEqual(1, len(large_block_failures(Path("task.ts"), lines, 120)))

    def test_template_interpolation_executable_body_is_not_masked(self):
        lines = ['function task() {', '  return `${(() => {']
        lines += ['    work();'] * 125 + ['  })()}`;', '}']
        self.assertEqual(1, len(large_block_failures(Path("task.ts"), lines, 120)))

    def test_comment_markers_inside_quotes_do_not_mask_code(self):
        lines = ['function task() {', '  const url = "https://example.test/{";',
                 "  const comment = '/* {';", '}'] + ['const other = 1;'] * 130
        self.assertEqual([], large_block_failures(Path("task.ts"), lines, 120))
