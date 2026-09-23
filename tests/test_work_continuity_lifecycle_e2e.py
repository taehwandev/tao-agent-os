"""The three concerns of a continued task, exercised through the real hook CLI.

Work continuity (may this action keep the work), action admission (is this
action authorized now) and verification validity (which recorded evidence still
holds) are separate questions, and every scenario here is a case where
answering one of them decided another by accident.

Nothing is simulated: each test runs `start`, the Claude Stop gate, `resume`,
`gate-batch` and `cancel` as separate processes against a real checkout, and
the nested cases run in a linked worktree under `<repo>/.tao/worktrees/<name>`
so ownership is proven by where the bytes land rather than by argument.
"""

from __future__ import annotations

import json
import os
import shutil
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

from agent_run_registry import transition_run

HOOK = SCRIPTS / "agent-hook.py"
STOP_GATE = SCRIPTS / "claude_stop_gate.py"
SESSION = "continuity-e2e-session"
TESTS_GATE = {
    "gate": "tests",
    "status": "SUCCESS",
    "fields": {
        "check": "python3 -m unittest discover -s tests",
        "result": "12 tests passed, exit 0",
    },
}


_STATE_HOME: list = []


def setUpModule() -> None:
    # Every start here opens a user-local work card, and `environment()` hands
    # os.environ to each hook process. Without this the suite fills the
    # developer's own ~/.tao/work-cards with cards for throwaway checkouts.
    directory = tempfile.TemporaryDirectory(prefix="tao-state-home-")
    patch = mock.patch.dict(os.environ, {"TAO_STATE_HOME": directory.name})
    patch.start()
    _STATE_HOME.extend((patch, directory))


def tearDownModule() -> None:
    patch, directory = _STATE_HOME
    patch.stop()
    directory.cleanup()
    _STATE_HOME.clear()


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True
    ).stdout


def environment(session: str) -> dict[str, str]:
    values = dict(os.environ)
    values.pop("CODEX_THREAD_ID", None)
    values["CLAUDE_CODE_SESSION_ID"] = session
    return values


def hook(
    project: Path, rules: Path, *arguments: str, session: str = SESSION
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK), *arguments, "--project", str(project), "--rules", str(rules)],
        capture_output=True,
        text=True,
        env=environment(session),
    )


def start(
    project: Path, rules: Path, request: str, *extra: str, session: str = SESSION
) -> subprocess.CompletedProcess:
    return hook(
        project,
        rules,
        "start",
        "--command",
        "bugfix",
        "--request",
        request,
        "--intent",
        "continuity_scenario",
        "--target-summary",
        "the sample module and its check",
        "--approved-effect",
        "git_write",
        *extra,
        session=session,
    )


def turn_boundary(project: Path, session: str = SESSION) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STOP_GATE)],
        input=json.dumps({"cwd": str(project), "session_id": session}),
        capture_output=True,
        text=True,
        env=environment(session),
    )


def detail(result: subprocess.CompletedProcess, prefix: str) -> str:
    for line in result.stdout.splitlines():
        if line.startswith(f"- {prefix}"):
            return line[2:].strip()
    return ""


def run_id(result: subprocess.CompletedProcess) -> str:
    return detail(result, "run id: ").split(": ", 1)[-1]


def remaining_gates(result: subprocess.CompletedProcess) -> list[str]:
    line = detail(result, "Remaining route gates: ")
    return json.loads(line.split(": ", 1)[1].replace("'", '"')) if line else []


def states(project: Path) -> list[str]:
    path = project / ".tao" / "run-registry.json"
    return [run["state"] for run in json.loads(path.read_text(encoding="utf-8"))["runs"]]


def record_gate(
    project: Path, rules: Path, payload: dict, session: str = SESSION
) -> subprocess.CompletedProcess:
    return hook(
        project, rules, "gate-batch", "--gate-record", json.dumps([payload]), session=session
    )


class PlainCheckout:
    """A small project whose rules root is this repository, read-only."""

    def __init__(self, directory: str) -> None:
        self.project = Path(directory).resolve() / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (self.project / "README.md").write_text("Baseline contract.\n", encoding="utf-8")
        git(self.project, "init", "-q")
        git(self.project, "config", "user.email", "continuity@example.invalid")
        git(self.project, "config", "user.name", "Continuity")
        git(self.project, "add", ".")
        git(self.project, "commit", "-qm", "fixture")


class WorkContinuityTests(unittest.TestCase):
    """One task, several actions: the run must survive its own progress."""

    def continued(self, checkout: PlainCheckout, source: str, *extra: str, session: str = SESSION):
        return start(
            checkout.project,
            ROOT,
            "이어서 해줘",
            "--continue-from",
            source,
            *extra,
            session=session,
        )

    def test_scoped_evidence_is_carried_only_while_its_declared_inputs_hold(self) -> None:
        cases = {
            "unchanged": (None, ["tests"]),
            "unrelated file": (Path("notes.txt"), ["tests"]),
            "declared input": (Path("src/module.py"), []),
        }
        for label, (changed, carried) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                checkout = PlainCheckout(directory)
                first = start(checkout.project, ROOT, "src/module.py 의 가드를 고쳐줘")
                self.assertEqual(0, first.returncode, first.stdout)
                gate = record_gate(
                    checkout.project, ROOT, {**TESTS_GATE, "input_paths": ["src/module.py"]}
                )
                self.assertEqual(0, gate.returncode, gate.stdout)
                if changed is not None:
                    (checkout.project / changed).write_text("moved\n", encoding="utf-8")

                follow = self.continued(
                    checkout,
                    run_id(first),
                    "--reuse-inputs",
                    "same scope, toolchain, artifacts and external inputs",
                )

                self.assertEqual(0, follow.returncode, follow.stdout)
                self.assertEqual(
                    f"Carried local gates: {carried}", detail(follow, "Carried local gates")
                )
                self.assertNotIn("review hook", detail(follow, "Carried local gates"))

    def test_a_recorded_failure_is_never_carried_as_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = PlainCheckout(directory)
            first = start(checkout.project, ROOT, "src/module.py 의 가드를 고쳐줘")
            passed = record_gate(checkout.project, ROOT, TESTS_GATE)
            failed = record_gate(
                checkout.project,
                ROOT,
                {**TESTS_GATE, "status": "FAIL", "fields": {**TESTS_GATE["fields"], "result": "1 failed, exit 1"}},
            )
            self.assertEqual(0, passed.returncode, passed.stdout)
            self.assertEqual(0, failed.returncode, failed.stdout)

            follow = self.continued(
                checkout,
                run_id(first),
                "--reuse-inputs",
                "nothing changed since the failing run",
            )

            self.assertEqual(0, follow.returncode, follow.stdout)
            self.assertEqual("Carried local gates: []", detail(follow, "Carried local gates"))
            self.assertIn("tests", remaining_gates(follow))

    def test_another_session_cannot_continue_this_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = PlainCheckout(directory)
            first = start(checkout.project, ROOT, "src/module.py 의 가드를 고쳐줘")
            record_gate(checkout.project, ROOT, TESTS_GATE)

            follow = self.continued(
                checkout,
                run_id(first),
                "--reuse-inputs",
                "same inputs, different session",
                session="a-different-session",
            )

            self.assertEqual(1, follow.returncode)
            self.assertIn("session or registered source differs", follow.stdout)


class NestedWorktreeContinuityTests(unittest.TestCase):
    """A linked worktree at `<repo>/.tao/worktrees/<name>` owns its own state."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name).resolve()
        cls.rules = cls.root / "checkout"
        shutil.copytree(
            ROOT,
            cls.rules,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", ".tao", "__pycache__", ".pytest_cache"),
        )
        git(cls.rules, "init", "-q")
        git(cls.rules, "config", "user.email", "continuity@example.invalid")
        git(cls.rules, "config", "user.name", "Continuity")
        git(cls.rules, "add", "-A")
        git(cls.rules, "commit", "-qm", "rules fixture")
        # An ancestor workspace directory that no lifecycle write may reach.
        cls.ancestor = cls.root / ".tao"
        cls.ancestor.mkdir()
        os.chmod(cls.ancestor, 0o500)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chmod(cls.ancestor, 0o700)
        cls._temporary.cleanup()

    def worktree(self, name: str) -> Path:
        path = self.rules / ".tao" / "worktrees" / name
        git(self.rules, "worktree", "add", "-q", str(path), "-b", f"fix/{name}")
        return path

    @staticmethod
    def files(root: Path) -> dict[str, int]:
        if not root.exists():
            return {}
        return {
            str(path): path.stat().st_mtime_ns
            for path in root.rglob("*")
            if path.is_file() and "/worktrees/" not in str(path)
        }

    def test_the_worktree_owns_every_lifecycle_write(self) -> None:
        worktree = self.worktree("ownership")
        before = self.files(self.rules / ".tao")

        started = start(worktree, self.rules, "src/module.py 의 가드를 고쳐줘")

        self.assertEqual(0, started.returncode, started.stdout)
        self.assertEqual(before, self.files(self.rules / ".tao"))
        self.assertEqual({}, self.files(self.ancestor))
        self.assertTrue(
            (worktree / ".tao" / "runs" / run_id(started) / "preflight.json").is_file()
        )
        self.assertIn(
            str(worktree / ".tao"), detail(started, "evidence: ")
        )

    def test_a_turn_boundary_and_an_advancing_rules_root_keep_one_run(self) -> None:
        worktree = self.worktree("continuity")
        started = start(worktree, self.rules, "src/module.py 의 가드를 고쳐줘")
        self.assertEqual(0, started.returncode, started.stdout)
        run = run_id(started)

        (worktree / "src").mkdir(exist_ok=True)
        (worktree / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
        self.assertEqual(0, turn_boundary(worktree).returncode)
        self.assertEqual(["interrupted"], states(worktree))
        # Another session lands an unrelated commit on the rules checkout.
        (self.rules / "NOTES.md").write_text("landed elsewhere\n", encoding="utf-8")
        git(self.rules, "add", "NOTES.md")
        git(self.rules, "commit", "-qm", "unrelated advance")

        resumed = hook(
            worktree,
            self.rules,
            "resume",
            "--last",
            "--runtime",
            "claude",
            "--runtime-session-id",
            SESSION,
            "--run-id",
            run,
        )

        self.assertEqual(0, resumed.returncode, resumed.stdout)
        self.assertIn("resume result: ready", resumed.stdout)
        self.assertIn("reconciled drift:", resumed.stdout)
        self.assertIn("rules_worktree", detail(resumed, "reconciled drift"))
        self.assertIn(f"run: {run}", resumed.stdout)
        self.assertEqual(["running"], states(worktree))
        # The continued run still owns its ledger: no second start was needed.
        gate = record_gate(worktree, self.rules, TESTS_GATE)
        self.assertEqual(0, gate.returncode, gate.stdout)
        self.assertNotIn("tests", remaining_gates(gate))
        self.assertEqual(["running"], states(worktree))

    def test_a_superseded_worktree_run_is_settled_by_its_replacement(self) -> None:
        worktree = self.worktree("superseded")
        superseded = start(worktree, self.rules, "같은 작업을 메인에서 끝냈어")
        replacement = start(self.rules, self.rules, "같은 작업을 메인에서 끝냈어")
        self.assertEqual(0, superseded.returncode, superseded.stdout)
        self.assertEqual(0, replacement.returncode, replacement.stdout)
        replacement_evidence = Path(detail(replacement, "evidence: ").split(": ", 1)[1])
        transition_run(
            self.rules, replacement_evidence, "completed", run_id=run_id(replacement)
        )

        settled = hook(
            worktree,
            self.rules,
            "cancel",
            "--evidence",
            str(worktree / ".tao" / "runs" / run_id(superseded) / "preflight.json"),
            "--replacement-evidence",
            str(replacement_evidence),
        )

        self.assertEqual(0, settled.returncode, settled.stdout)
        self.assertIn("settled as cancelled", settled.stdout)
        self.assertEqual(["cancelled"], states(worktree))


class StrandedRunTests(unittest.TestCase):
    """The hook that settles a stranded run must not need it to be active."""

    def test_cancel_without_evidence_names_the_stopped_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = PlainCheckout(directory)
            started = start(checkout.project, ROOT, "아무 변경도 필요없었어")
            self.assertEqual(0, started.returncode, started.stdout)
            self.assertEqual(0, turn_boundary(checkout.project).returncode)
            self.assertEqual(["interrupted"], states(checkout.project))

            settled = hook(
                checkout.project,
                ROOT,
                "cancel",
                "--no-change-evidence",
                "the reported defect was a deliberate guard",
            )

            self.assertNotIn("Traceback", settled.stderr)
            self.assertEqual(0, settled.returncode, settled.stdout + settled.stderr)
            self.assertEqual(["cancelled"], states(checkout.project))

    def test_cancel_without_a_resolvable_run_is_a_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = PlainCheckout(directory)
            started = start(checkout.project, ROOT, "아무 변경도 필요없었어")
            hook(
                checkout.project,
                ROOT,
                "cancel",
                "--no-change-evidence",
                "nothing needed changing",
            )
            self.assertEqual(0, started.returncode, started.stdout)

            again = hook(
                checkout.project,
                ROOT,
                "cancel",
                "--no-change-evidence",
                "nothing needed changing",
            )

            self.assertNotIn("Traceback", again.stderr)
            self.assertEqual(1, again.returncode)
            self.assertIn("no single settleable run", again.stdout)


if __name__ == "__main__":
    unittest.main()
