"""Start guidance remains available after context loss and across workers."""

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

from agent_start_guidance import REVIEW_SCOPE_CHOICES, review_shape_line

HOOK = SCRIPTS / "agent-hook.py"
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
        (self.project / "src" / "module.py").write_text("value = 1\n")
        (self.project / ".gitignore").write_text(".tao/\n")
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
        outputs = (
            self.start(command, "fix the sample module value", "guidance-e2e-1"),
            self.start(command, "fix the sample module value again", "guidance-e2e-1"),
            self.start(command, "fix the sample module value once more", "guidance-e2e-2"),
        )
        for output in outputs:
            for paragraph in route_static + ["Work continuity:", "Reading boundary:",
                                              "later hooks in this runtime session", "- run id: ",
                                              f"- Route: {command} gates="]:
                self.assertIn(paragraph, output)
            self.assertNotIn("static paragraphs omitted", output)
        self.assertFalse((self.project / ".tao/start-guidance-shown.json").exists())

    def test_bugfix_route(self) -> None:
        self.check_route("bugfix", ["Closeout reuse:"])

    def test_commit_route(self) -> None:
        self.check_route("commit", ["Commit reuse:", "Publication continuity:"])


if __name__ == "__main__":
    unittest.main()
