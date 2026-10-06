"""Two more false "wrapper hides the program" holds seen in one real session.

While a run was open, `git diff -- $FILES > $OUT/p.patch` was held because the
redirect target was split off as if it were a command whose program is `$OUT`,
and `grep -l x *.xml | xargs grep -h y` was held because `xargs` was opaque
even when the program it runs can never publish. Each cost a re-spelled
command; neither can push, tag or open a pull request.

Split from `test_claude_pretool_merge_and_loops.py` to keep both under budget.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import test_claude_pretool_gate as base  # noqa: E402
from test_claude_pretool_gate import _reason  # noqa: E402
from test_claude_pretool_merge_and_loops import _project, _run  # noqa: E402


def setUpModule() -> None:
    base.setUpModule()


def tearDownModule() -> None:
    base.tearDownModule()


class RedirectTargetsAreDataTests(unittest.TestCase):
    RELEASED = (
        'SP=/tmp/s && MINE="a b" && git diff -- $MINE > $SP/p.patch && echo "$MINE" > $SP/m.txt',
        'echo done > "$OUT/log.txt"',
        "git status 2> $ERR",
        "git log --oneline >> ${LOG:-/tmp/log}",
        "sort < $IN > $OUT",
    )
    HELD = {
        "git push > $OUT": "publishes",
        "git 2>$ERR push": "publishes",
        "git >$OUT tag v1": "publishes",
        "echo x > >(git push)": "unreadable",
        "echo x > $(git push)": "publishes",
        "$cmd > $OUT": "unreadable",
    }

    def test_a_computed_redirect_target_does_not_hide_the_program(self) -> None:
        from claude_pretool_gate import publication_hold

        for command in self.RELEASED:
            with self.subTest(command=command):
                self.assertEqual("", publication_hold(command), command)

    def test_redirections_still_reveal_what_publishes(self) -> None:
        from claude_pretool_gate import publication_hold

        for command, verdict in self.HELD.items():
            with self.subTest(command=command):
                self.assertEqual(verdict, publication_hold(command), command)

    def test_the_observed_redirect_is_not_held_while_the_run_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _code, out = _run(project, self.RELEASED[0])
        self.assertNotIn("still open", out)


class XargsToLocalProgramsTests(unittest.TestCase):
    RELEASED = (
        'grep -l "<failure" *.xml | xargs grep -h -A8 "<failure" | head -20',
        'find . -name "*.tmp" -print0 | xargs -0 rm -f',
        "xargs -n 1 echo < list.txt",
        "xargs -P4 -n2 wc -l < files.txt",
        "ls | xargs -r --max-args=3 basename",
    )
    HELD = (
        "cat refs | xargs git push",
        "echo push | xargs git",
        "xargs -I{} git {} < commands.txt",
        "xargs --replace=X git X < commands.txt",
        'xargs sh -c "$x"',
        "xargs sed -e x",
        "xargs awk 1",
        "xargs --unknown-option grep x",
        "xargs $tool",
        "xargs",
    )

    def test_xargs_running_a_program_that_cannot_publish_is_read(self) -> None:
        from claude_pretool_gate import publication_hold

        for command in self.RELEASED:
            with self.subTest(command=command):
                self.assertEqual("", publication_hold(command), command)

    def test_xargs_running_anything_else_stays_unreadable(self) -> None:
        from claude_pretool_gate import publication_hold

        for command in self.HELD:
            with self.subTest(command=command):
                self.assertEqual("unreadable", publication_hold(command), command)

    def test_the_observed_xargs_read_is_not_held_while_the_run_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _code, released = _run(project, self.RELEASED[0])
            code, held = _run(project, "cat refs | xargs git push")
        self.assertNotIn("still open", released)
        self.assertEqual(0, code)
        self.assertIn("hides the program", _reason(held))


if __name__ == "__main__":
    unittest.main()
