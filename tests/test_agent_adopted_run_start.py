"""What checkpoint a start writes when it adopts a run that already has one.

Split from ``tests/test_agent_hook_continuation.py``. The subject is the kind
chosen at the start of a run, and the drift that followed from always choosing
`initial`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import agent_hook_continuation as wiring

RUN_ID = "0123456789abcdef0123456789abcdef"


def _load_hook_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "agent-hook.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_hook_script("agent_hook_for_test_agent_adopted_run_start")


class AdoptedRunStartTests(unittest.TestCase):
    """A start does not always begin a run.

    When the runtime session already owns one, the evidence resolver adopts it,
    and an `initial` checkpoint is refused whenever a valid packet exists --
    which for an adopted run is always. The refusal is non-blocking, so the
    start reported SUCCESS while the packet stayed bound to the earlier start's
    HEAD, and `resume` then called that head_drift and rendered none of the
    saved work.
    """

    def _args(self, project: Path, evidence: Path, command: str = "task"):
        return Namespace(project=project, evidence=evidence, command=command)

    def test_a_run_with_a_packet_is_refreshed_not_initialised(self) -> None:
        from test_agent_runtime_session import RuntimeFixture

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)

            kind, work = wiring.start_checkpoint(
                self._args(fixture.project, fixture.evidence)
            )

        self.assertEqual("lifecycle", kind)
        self.assertIsNone(work)

    def test_the_refresh_keeps_the_objective_the_run_recorded(self) -> None:
        """The objective a start would write is the route enum.

        Overwriting a recorded one with that would lose exactly what the
        refresh exists to preserve.
        """

        from test_agent_runtime_session import RuntimeFixture

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            args = self._args(fixture.project, fixture.evidence)
            args.rules = fixture.rules

            kind, work = wiring.start_checkpoint(args)
            wiring.record_lifecycle_checkpoint(args, kind, work=work)

            packet = fixture.packet()

        self.assertEqual("resume safe work", packet["work"]["objective"])
        self.assertEqual(1, packet["generation"])

    def test_a_run_with_no_packet_yet_is_initialised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            kind, work = wiring.start_checkpoint(
                self._args(project, evidence, command="bugfix")
            )

        self.assertEqual("initial", kind)
        self.assertEqual({"objective": "bugfix workflow"}, work)

    def test_a_packet_free_run_is_still_asked_for_an_initial(self) -> None:
        """The writer refuses it anyway; the kind must not depend on that."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            kind, work = wiring.start_checkpoint(
                self._args(project, project / ".tao" / "preflight.json")
            )

        self.assertEqual("initial", kind)
        self.assertEqual({"objective": "task workflow"}, work)

    def test_a_real_adopted_start_rebinds_the_packet_to_the_new_head(self) -> None:
        """The end the fix is for: a restart after a commit leaves no drift."""

        import os
        import subprocess

        def git(project: Path, *arguments: str) -> None:
            subprocess.run(["git", *arguments], cwd=project, check=True,
                           capture_output=True)

        def start(project: Path, state: str) -> str:
            return subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "one request, twice",
                    "--read-only", "--runtime-session-id", "adopted-run-probe",
                ],
                cwd=project, capture_output=True, text=True,
                # Adoption binds a run to the runtime session in the
                # environment, not to `--runtime-session-id`, which binds the
                # intent envelope instead. Inheriting the outer session made
                # this pass inside a Claude session and fail in a clean shell
                # or on CI, where there is no session to adopt into and every
                # start records `initial` again.
                env={
                    **os.environ,
                    "TAO_STATE_HOME": state,
                    "CLAUDE_CODE_SESSION_ID": "adopted-run-probe",
                    "CODEX_THREAD_ID": "",
                },
            ).stdout

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            git(project, "init", "-q", ".")
            git(project, "config", "user.email", "probe@example.invalid")
            git(project, "config", "user.name", "probe")
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-q", "-m", "first", "--no-verify")

            first = start(project, state)

            (project / "NEXT.md").write_text("more\n", encoding="utf-8")
            git(project, "add", "NEXT.md")
            git(project, "commit", "-q", "-m", "second", "--no-verify")

            second = start(project, state)

            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            packets = list((project / ".tao" / "runs").glob("*/continuation.json"))
            packet = json.loads(packets[0].read_text(encoding="utf-8"))

        self.assertIn("continuation checkpoint: initial recorded", first)
        self.assertIn("continuation checkpoint: lifecycle recorded", second)
        self.assertNotIn("checkpoint_generation_changed", second)
        self.assertEqual(1, len(packets))
        self.assertEqual(head, packet["drift"]["project"]["head"])


if __name__ == "__main__":
    unittest.main()
