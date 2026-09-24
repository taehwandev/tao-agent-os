"""Two false denials seen in one real session, each through the real `decide()`.

`gh pr merge` had no effect contract, so right after a finish that admitted
external_write -- and had just let `git push` and `gh pr create` through -- the
merge was answered "effect unknown" and the session opened a whole second run
for it. And while a run was open, every `for`/`while` loop was held as a
wrapper hiding its program, although each body was a plain read.

Split from `test_claude_pretool_gate.py`, which is over its size budget.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import test_claude_pretool_gate as base  # noqa: E402
from test_claude_pretool_gate import (  # noqa: E402
    gate,
    _attest_finished_publication,
    _decide,
    _opt_in_project,
    _reason,
    _require_linked_worktree,
    _write_preflight,
)
from agent_run_registry import transition_run  # noqa: E402
from agent_runtime_session import resolve_runtime_evidence  # noqa: E402


def setUpModule() -> None:
    base.setUpModule()


def tearDownModule() -> None:
    base.tearDownModule()


SESSION = "merge-and-loops-session"


def _project(base_dir: Path, *, finished: str = "") -> Path:
    """An opted-in linked worktree whose session run is open, or finished."""

    project = _opt_in_project(base_dir)
    _write_preflight(project, SESSION)
    _require_linked_worktree(project, linked=True)
    policy = project / gate.WORKTREE_POLICY_PATH
    declared = json.loads(policy.read_text(encoding="utf-8"))
    declared["require_workflow_entry"] = True
    policy.write_text(json.dumps(declared), encoding="utf-8")
    if finished:
        evidence = resolve_runtime_evidence(
            project, {"runtime": "claude", "session_id": SESSION}
        )
        assert evidence is not None
        transition_run(project, evidence, "completed")
        _attest_finished_publication(project, evidence, finished)
    return project


def _run(project: Path, command: str) -> tuple[int, str]:
    return _decide(
        {
            "tool_name": "Bash",
            "cwd": str(project),
            "session_id": SESSION,
            "tool_input": {"command": command},
        }
    )


class PullRequestMergeTests(unittest.TestCase):
    def test_external_write_finish_admits_the_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), finished="external_write")
            for command in (
                "gh pr merge 450 --merge",
                "gh pr merge 448 --squash --delete-branch",
                'gh pr merge 448 --merge --subject "Merge pull request #448"',
                "gh pr merge work --rebase -R owner/repo --auto",
                "gh pr merge 448 --merge && gh pr view 448 --json state -q .state",
            ):
                with self.subTest(command=command):
                    code, out = _run(project, command)
                    self.assertEqual(0, code)
                    self.assertIn("a successful finish", _reason(out), command)

    def test_git_write_finish_names_the_effect_the_merge_needs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), finished="git_write")
            code, out = _run(project, "gh pr merge 450 --merge")

        reason = _reason(out)
        self.assertEqual(0, code)
        self.assertNotIn("a successful finish", reason)
        self.assertNotIn("effect: unknown", reason)
        self.assertIn("--approved-effect external_write", reason)

    def test_merge_is_held_while_the_run_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            for command in ("gh pr merge 450 --merge", "gh pr merge 450 --admin"):
                with self.subTest(command=command):
                    code, out = _run(project, command)
                    self.assertEqual(0, code)
                    self.assertIn("still open", _reason(out), command)

    def test_an_unlisted_merge_option_is_not_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), finished="external_write")
            for command in (
                "gh pr merge 450 --admin",
                "gh pr merge 450 --merge --body-file notes.md",
                "gh pr merge 450 451 --merge",
            ):
                with self.subTest(command=command):
                    code, out = _run(project, command)
                    reason = _reason(out)
                    self.assertEqual(0, code)
                    self.assertNotIn("a successful finish", reason, command)
                    self.assertIn("admitted merge contract", reason, command)

    def test_without_any_run_the_merge_names_its_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project, linked=True)
            policy = project / gate.WORKTREE_POLICY_PATH
            declared = json.loads(policy.read_text(encoding="utf-8"))
            declared["require_workflow_entry"] = True
            policy.write_text(json.dumps(declared), encoding="utf-8")
            code, out = _run(project, "gh pr merge 450 --merge")

        reason = _reason(out)
        self.assertEqual(0, code)
        self.assertNotIn("effect: unknown", reason)
        self.assertIn("--approved-effect external_write", reason)


class LoopBodiesAreReadTests(unittest.TestCase):
    OBSERVED_READS = (
        'for u in https://www.keyflow.me/ https://www.keyflow.me/ko; do curl -q -s '
        '-o /dev/null -w "$u code=%{http_code}\\n" --compressed "$u"; done',
        "cd /tmp/scratch && grep -o '/_next/static/chunks/[^\"?]*\\.js' home.html "
        "| sort -u > chunks.txt; wc -l < chunks.txt; total=0; while read c; do "
        's=$(curl -q -s --compressed -o /dev/null -w "%{size_download}" '
        '"https://www.keyflow.me$c"); echo "$s $c"; done < chunks.txt | sort -rn '
        "> sizes.txt; head -12 sizes.txt",
        "for c in $(grep -o '/_next/[^\"?]*\\.css' home.html | sort -u); do "
        'curl -q -s "https://x$c" -o "css_$(basename $c)"; done',
        "if git status --short; then echo dirty; else echo clean; fi",
        'until s=$(gh api "repos/o/r/commits/abc/statuses" -q ".[0].state"); '
        "do sleep 20; done",
    )

    def test_observed_read_loops_are_not_held_while_the_run_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            for command in self.OBSERVED_READS:
                with self.subTest(command=command):
                    _code, out = _run(project, command)
                    self.assertNotIn("still open", out, command)

    def test_a_loop_body_that_publishes_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            for command in (
                "for b in a c; do git push origin $b; done",
                "while read b; do gh pr merge $b --merge; done < prs.txt",
                "for u in a; do echo $(git push); done",
                "if true; then git push; fi",
            ):
                with self.subTest(command=command):
                    code, out = _run(project, command)
                    self.assertEqual(0, code)
                    self.assertIn("still open", _reason(out), command)

    def test_a_hidden_program_is_still_unreadable(self) -> None:
        from claude_pretool_gate import publication_hold

        for command in (
            'eval "$cmd"',
            'bash -c "$cmd"',
            'sh -c "$cmd"',
            "$(echo git) push",
            "for u in a; do $cmd push; done",
            "for u in a; do `echo git` push; done",
            "git $action origin",
        ):
            with self.subTest(command=command):
                self.assertEqual("unreadable", publication_hold(command), command)

        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            code, out = _run(project, 'eval "$cmd"')
        self.assertEqual(0, code)
        self.assertIn("hides the program", _reason(out))


if __name__ == "__main__":
    unittest.main()
