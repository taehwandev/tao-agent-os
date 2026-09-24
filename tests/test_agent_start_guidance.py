"""Start prints its static guidance once per runtime session and project.

The unit cases pin the collapse rule itself; the end-to-end cases run the real
`start` hook twice in one session, then once in another, for a code route and
the commit route, and check that nothing run-specific is ever dropped.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_start_guidance import (
    POINTER,
    REVIEW_SCOPE_CHOICES,
    STATE_FILE,
    collapse_repeated_guidance,
    review_shape_line,
)

HOOK = SCRIPTS / "agent-hook.py"
POINTER_LEAD = POINTER.split("(", 1)[0]
SESSION = {"runtime": "claude", "session_id": "guidance-session"}
STATIC = [
    "Reading boundary: reference docs are on demand.",
    "Work continuity: a goal iteration is not a new intake.",
    "Closeout reuse: review the final diff once.",
]
RUN_SPECIFIC = [
    "Route: bugfix gates=['tests', 'review hook']",
    "run id: 0123",
    "evidence: /x/.tao/runs/0123/preflight.json",
]


class CollapseRule(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name)
        self.details = [RUN_SPECIFIC[0], *STATIC, *RUN_SPECIFIC[1:]]

    def collapse(self, details: list[str], session: dict[str, str] = SESSION) -> list[str]:
        return collapse_repeated_guidance(self.project, session, list(details))

    def test_first_start_prints_everything(self) -> None:
        self.assertEqual(self.collapse(self.details), self.details)

    def test_repeat_start_replaces_static_block_with_one_pointer(self) -> None:
        self.collapse(self.details)
        second = self.collapse(self.details)
        for paragraph in STATIC:
            self.assertNotIn(paragraph, second)
        pointers = [line for line in second if line.startswith(POINTER_LEAD)]
        self.assertEqual(pointers, [POINTER.format(count=len(STATIC))])
        self.assertEqual([line for line in second if line not in pointers], RUN_SPECIFIC)

    def test_another_session_prints_everything(self) -> None:
        self.collapse(self.details)
        other = {"runtime": "claude", "session_id": "another-session"}
        self.assertEqual(self.collapse(self.details, other), self.details)

    def test_changed_paragraph_prints_again(self) -> None:
        self.collapse(self.details)
        changed = STATIC[1] + " Now reworded."
        second = self.collapse([RUN_SPECIFIC[0], STATIC[0], changed, STATIC[2], *RUN_SPECIFIC[1:]])
        self.assertIn(changed, second)
        self.assertNotIn(STATIC[0], second)
        self.assertIn(POINTER.format(count=2), second)

    def test_no_session_binding_fails_open(self) -> None:
        self.collapse(self.details, {})
        self.assertEqual(self.collapse(self.details, {}), self.details)
        self.assertFalse((self.project / STATE_FILE).exists())

    def test_unreadable_state_fails_open(self) -> None:
        state = self.project / STATE_FILE
        state.parent.mkdir(parents=True)
        state.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.collapse(self.details), self.details)

    def test_run_path_in_checkpoint_command_does_not_defeat_the_record(self) -> None:
        first = "copyable checkpoint command:\ntao checkpoint --evidence /p/.tao/runs/" + "a" * 32 + "/preflight.json"
        second = first.replace("a" * 32, "b" * 32)
        self.collapse([first])
        self.assertEqual(self.collapse([second]), [POINTER.format(count=1)])


class ReviewShape(unittest.TestCase):
    def test_scopes_are_the_parser_choices(self) -> None:
        spec = importlib.util.spec_from_file_location("agent_hook_for_shape", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parser = module.build_parser()
        with mock.patch.object(sys, "argv", ["agent-hook.py"]):
            for scope in REVIEW_SCOPE_CHOICES:
                args = parser.parse_args(["review", "--project", str(ROOT), "--rules", str(ROOT),
                                          "--review-scope", scope])
                self.assertEqual(args.review_scope, scope)
        line = review_shape_line(["--code-review-evidence"])
        for scope in REVIEW_SCOPE_CHOICES:
            self.assertIn(scope, line)

    def test_required_structure_flag_is_not_repeated_as_conditional(self) -> None:
        line = review_shape_line(["--code-review-evidence", "--structure-review-evidence"])
        self.assertEqual(line.count("--structure-review-evidence"), 1)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


class StartOutputEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        self.state_home = str(base / "state")
        self.project = base / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        _git(self.project, "init", "-q")
        _git(self.project, "config", "user.email", "guidance@example.invalid")
        _git(self.project, "config", "user.name", "Guidance")
        _git(self.project, "add", ".")
        _git(self.project, "commit", "-qm", "fixture")

    def start(self, command: str, request: str, session: str) -> str:
        env = dict(os.environ)
        env.pop("CODEX_THREAD_ID", None)
        env["CLAUDE_CODE_SESSION_ID"] = session
        env["TAO_STATE_HOME"] = self.state_home
        result = subprocess.run(
            [sys.executable, str(HOOK), "start", "--project", str(self.project), "--rules", str(ROOT),
             "--command", command, "--request", request, "--intent", "guidance_scenario",
             "--target-summary", "the sample module", "--approved-effect", "git_write"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def check_route(self, command: str, route_static: list[str]) -> None:
        first = self.start(command, "fix the sample module value", "guidance-e2e-1")
        repeat = self.start(command, "fix the sample module value again", "guidance-e2e-1")
        other = self.start(command, "fix the sample module value once more", "guidance-e2e-2")
        for paragraph in route_static + ["Work continuity:", "later hooks in this runtime session"]:
            self.assertIn(paragraph, first)
            self.assertNotIn(paragraph, repeat)
            self.assertIn(paragraph, other)
        self.assertNotIn(POINTER_LEAD, first)
        self.assertEqual(repeat.count(POINTER_LEAD), 1)
        for output in (first, repeat, other):
            for run_line in (f"- Route: {command} gates=", "- run id: ", "- evidence: ",
                             "- work id: ", "- VibeGuard overall: ", "- Required hooks: ",
                             "Required knowledge", "- Review shape: review --review-outcome "):
                self.assertIn(run_line, output)
        self.assertLess(len(repeat), len(first) // 2)

    def test_bugfix_route(self) -> None:
        self.check_route("bugfix", ["Reading boundary:", "Closeout reuse:"])

    def test_commit_route(self) -> None:
        self.check_route("commit", ["Commit reuse:", "Publication continuity:"])


if __name__ == "__main__":
    unittest.main()
