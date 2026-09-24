"""Common read-only invocations pass the real gate; project code gets one clear remedy."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.global_state import STATE_HOME_ENV
from claude_bash_readonly import bash_command_kind, bash_invocation
from claude_command_effect import command_effect

_SPEC = importlib.util.spec_from_file_location(
    "claude_pretool_gate_inspection_under_test", ROOT / "scripts" / "claude_pretool_gate.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

ADMITTED = {
    "node syntax check": "node --check web/src/app.js",
    "node short syntax check": "node -c a.js b.js",
    "interpreter version": "python3 --version",
    "node version": "node --version",
    "json pretty-print": "python3 -m json.tool --sort-keys package.json",
    "unittest with warning filter": "python3 -W ignore -m unittest discover -q -s tests -t tests -p test_x.py",
    "unittest with attached warning filter": "python3 -B -Wignore -m unittest tests.test_x",
    "process listing": "pgrep -fl vite",
    "open ports": "lsof -i :5173",
    "archive listing": "tar -tzf backup.tgz .tao/run-registry.json",
    "git reflog": "git reflog -5",
    "git reflog show": "git -C . reflog show --oneline main",
    "checksum": "shasum -a 256 package.json",
    "byte compare": "cmp a.txt b.txt",
    "link target": "readlink -f a.txt",
}

# Project code keeps its fail-closed verdict, now with the one-line remedy.
PROJECT_CODE = {
    "inline python": "python3 -c 'print(1)'",
    "python script": "python3 .agents/skills/aura/aura_verify.py --files a.ts",
    "npm script": "npm run test:all",
    "path-invoked script": "./scripts/check.sh src",
    "node script": "node tools/label.mjs --label codex",
    "json.tool with an output file": "python3 -m json.tool in.json out.json",
    "unittest behind a script flag": "python3 -W ignore script.py",
}

# Neighbours of admitted grammars that write, run code, or signal.
STILL_REFUSED = {
    "node evaluation": "node -e 'require(\"fs\").writeFileSync(\"x\",\"\")'",
    "node check plus option": "node --check --require ./hook.js a.js",
    "json.tool unknown option": "python3 -m json.tool --output x a.json",
    "tar extract": "tar -xzf backup.tgz",
    "tar create": "tar -czf backup.tgz .tao",
    "tar list with program": "tar -tzf backup.tgz --to-command=sh",
    "reflog expire": "git reflog expire --all",
    "reflog delete": "git reflog delete HEAD@{1}",
    "redirected listing": "pgrep -fl vite > pids.txt",
    "chained write": "node --check a.js && rm -rf build",
    "unittest behind -c": "python3 -c 'x' -m unittest",
}


def effect(command: str) -> tuple[str, str]:
    _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
    return command_effect(tokens, simple, bash_command_kind(tokens, simple))


class ClassifierTests(unittest.TestCase):
    def test_admitted_grammars_are_read_only(self) -> None:
        for family, command in ADMITTED.items():
            with self.subTest(family=family):
                self.assertEqual("read_only", effect(command)[0])

    def test_neighbours_stay_unverified_or_writing(self) -> None:
        for family, command in {**PROJECT_CODE, **STILL_REFUSED}.items():
            with self.subTest(family=family):
                self.assertNotEqual("read_only", effect(command)[0])

    def test_known_writers_are_named_writers(self) -> None:
        for command in ("ln -s a b", "mktemp -d /tmp/x.XXXX", "kill 42", "git stash drop stash@{0}",
                        "tar -czf out.tgz src"):
            with self.subTest(command=command):
                self.assertEqual("mutating", effect(command)[0])


class GateTests(unittest.TestCase):
    """The real `decide()` in a governed project with no workflow run."""

    SESSION = "inspection-session"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._outer = os.environ.get(STATE_HOME_ENV)
        os.environ[STATE_HOME_ENV] = str(Path(self._tmp.name) / "state")
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".tao").mkdir(parents=True)
        (self.project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")

    def tearDown(self) -> None:
        if self._outer is None:
            os.environ.pop(STATE_HOME_ENV, None)
        else:
            os.environ[STATE_HOME_ENV] = self._outer
        self._tmp.cleanup()

    def decide(self, command: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = gate.decide({
                "tool_name": "Bash",
                "cwd": str(self.project),
                "session_id": self.SESSION,
                "tool_input": {"command": command},
            })
        return code, buffer.getvalue()

    def decision(self, out: str) -> tuple[str, str]:
        if not out.strip():
            return "defer", ""
        spec = json.loads(out)["hookSpecificOutput"]
        return spec.get("permissionDecision", ""), spec.get("permissionDecisionReason", "")

    def test_admitted_families_pass_without_a_run(self) -> None:
        for family, command in ADMITTED.items():
            with self.subTest(family=family):
                code, out = self.decide(command)
                self.assertEqual(0, code)
                self.assertNotEqual("deny", self.decision(out)[0])

    def test_project_code_is_denied_with_one_remedy(self) -> None:
        for family, command in PROJECT_CODE.items():
            with self.subTest(family=family):
                _, out = self.decide(command)
                verdict, reason = self.decision(out)
                self.assertEqual("deny", verdict)
                self.assertIn("Tao command effect: unknown", reason)
                self.assertIn("runs project code", reason)
                self.assertIn("do not retry reworded or split variants", reason)
                self.assertIn("run the workflow start hook once for this project", reason)

    def test_refused_neighbours_stay_denied(self) -> None:
        for family, command in STILL_REFUSED.items():
            with self.subTest(family=family):
                _, out = self.decide(command)
                self.assertEqual("deny", self.decision(out)[0])


if __name__ == "__main__":
    unittest.main()
