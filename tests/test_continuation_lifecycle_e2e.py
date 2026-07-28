"""Resume real work after a real `kill -9`, through the real hook CLI.

This is the control the whole feature exists for. A session that is killed
without a shutdown path must still be recoverable by a different process, so
nothing here simulates death: a child is spawned, orphaned onto init so it owns
its own run, made to run the real `start` and `gate` hooks, and then SIGKILLed.
A second process runs `resume --last` and gets the work back.

The negative control removes exactly one thing -- the lifecycle checkpoint call
-- from the same child, the same hooks and the same kill, and observes that the
resume then finds nothing. Everything else in the run is unchanged, which is
what makes it a control rather than a different experiment.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_run_registry import registry_path

REQUEST = "implement the resume list command in src/module.py with a unit test"
GATE = "source docs"
POLL_SECONDS = 0.005
DEADLINE_SECONDS = 120

CHILD = '''
import os, subprocess, sys, time
from pathlib import Path

root, project, rules, evidence, pidfile, readyfile, runner = sys.argv[1:8]

# Orphan this process onto init and give it its own session, so the run it
# starts records *this* pid as its owner. Without that the owner would be the
# still-living test process and the kill would prove nothing.
if os.fork():
    os._exit(0)
os.setsid()
# Detach from the launcher's pipes as well: a survivor holding them open would
# make the launcher's own wait hang forever on a process it no longer owns.
devnull = os.open(os.devnull, os.O_RDWR)
for descriptor in (0, 1, 2):
    os.dup2(devnull, descriptor)
while os.getppid() != 1:
    time.sleep(0.001)
Path(pidfile).write_text(str(os.getpid()), encoding="utf-8")

entry = [sys.executable, runner] if runner else [sys.executable, root + "/scripts/agent-hook.py"]


def hook(*arguments):
    return subprocess.run(
        [*entry, *arguments, "--project", project, "--rules", rules, "--evidence", evidence],
        capture_output=True,
        text=True,
    )


start = hook(
    "start",
    "--command", "bugfix",
    "--request", {request!r},
    "--request-classified",
    "--classification-evidence", "clear-scoped; blockers resolved",
)
gate = hook(
    "gate",
    "--gate-name", {gate!r},
    "--gate-evidence", "read the routed guidance before editing",
    "--field", "source=AGENTS.md",
    "--field", "takeaway=follow the routed lifecycle",
)
Path(readyfile).write_text(
    "start={{0}} gate={{1}}\\n{{2}}{{3}}{{4}}{{5}}".format(
        start.returncode, gate.returncode, start.stdout, start.stderr, gate.stdout, gate.stderr
    ),
    encoding="utf-8",
)
while True:
    time.sleep(0.05)
'''

RUNNER = '''
import importlib.util, sys
from unittest.mock import patch

sys.path.insert(0, {scripts!r})
spec = importlib.util.spec_from_file_location("agent_hook_no_checkpoint", {hook!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.argv = ["agent-hook.py", *sys.argv[1:]]
with (
    patch.object(module, "record_lifecycle_checkpoint", return_value="continuation wiring removed"),
    patch.object(module, "checkpoint_after_hook", side_effect=lambda args, code, *rest, **keywords: code),
):
    raise SystemExit(module.main())
'''


def wait_for(condition, message: str):
    """Poll a real condition to a bound; never sleep for a fixed duration."""

    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(POLL_SECONDS)
    raise AssertionError(message)


def pid_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


class Checkout:
    """A real Git checkout with one isolated run-id evidence directory."""

    def __init__(self, directory: str) -> None:
        self.project = Path(directory) / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        for command in (
            ("init", "-q"),
            ("config", "user.email", "resume@example.invalid"),
            ("config", "user.name", "Resume Test"),
            ("add", "."),
            ("commit", "-qm", "fixture"),
        ):
            subprocess.run(
                ["git", *command],
                cwd=self.project,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self.run_id = uuid.uuid4().hex
        self.evidence = self.project / ".tao" / "runs" / self.run_id / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.directory = Path(directory)

    def child_script(self, *, wired: bool) -> tuple[Path, str]:
        script = self.directory / "child.py"
        script.write_text(CHILD.format(request=REQUEST, gate=GATE), encoding="utf-8")
        if wired:
            return script, ""
        runner = self.directory / "runner.py"
        runner.write_text(
            RUNNER.format(scripts=str(SCRIPTS), hook=str(SCRIPTS / "agent-hook.py")),
            encoding="utf-8",
        )
        return script, str(runner)

    def kill_after_work(self, *, wired: bool) -> str:
        """Run the real lifecycle in an orphaned child, then SIGKILL it."""

        script, runner = self.child_script(wired=wired)
        pidfile = self.directory / "child.pid"
        readyfile = self.directory / "child.ready"
        launcher = subprocess.run(
            [
                sys.executable,
                str(script),
                str(ROOT),
                str(self.project),
                str(ROOT),
                str(self.evidence),
                str(pidfile),
                str(readyfile),
                runner,
            ],
            capture_output=True,
            text=True,
        )
        assert launcher.returncode == 0, launcher.stderr
        report = wait_for(
            lambda: readyfile.read_text(encoding="utf-8") if readyfile.is_file() else "",
            "the child never finished its lifecycle hooks",
        )
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGKILL)
        wait_for(lambda: pid_is_gone(pid), "the killed child never left the process table")
        return report

    def resume(self, mode: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "agent-hook.py"),
                "resume",
                mode,
                "--project",
                str(self.project),
                "--rules",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
        )

    def owner_pid(self) -> int:
        payload = json.loads(registry_path(self.project).read_text(encoding="utf-8"))
        return int((payload["runs"][-1].get("owner") or {}).get("pid") or 0)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "fork"), "requires POSIX process control")
class KillNineResumeTests(unittest.TestCase):
    def test_work_survives_a_kill_nine_and_is_resumed_by_another_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Checkout(directory)

            report = checkout.kill_after_work(wired=True)
            self.assertIn("start=0 gate=0", report)

            listed = checkout.resume("--list")
            resumed = checkout.resume("--last")

            self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
            self.assertIn(checkout.run_id, listed.stdout)
            self.assertIn("holder=free", listed.stdout)
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertIn("SUCCESS resume", resumed.stdout)
            self.assertIn("resume result: ready", resumed.stdout)
            self.assertIn(f"objective: {REQUEST}", resumed.stdout)
            # The gate the dead child recorded is complete, so the resumed
            # checkpoint is the next one -- proof the gate checkpoint ran too,
            # not only the initial one written by start.
            self.assertIn("resume checkpoint: documentation impact", resumed.stdout)

    def test_without_the_lifecycle_checkpoint_the_resume_finds_nothing(self) -> None:
        """The negative control: same run, same kill, no checkpoint call."""

        with tempfile.TemporaryDirectory() as directory:
            checkout = Checkout(directory)

            report = checkout.kill_after_work(wired=False)
            self.assertIn("start=0 gate=0", report)

            listed = checkout.resume("--list")
            resumed = checkout.resume("--last")

            self.assertIn("status=legacy_no_packet", listed.stdout)
            self.assertFalse(
                (checkout.project / ".tao" / "runs" / checkout.run_id / "continuation.json").exists()
            )
            self.assertEqual(1, resumed.returncode)
            self.assertIn("FAIL resume", resumed.stdout)
            self.assertIn("resume result: not_found", resumed.stdout)
            self.assertNotIn(REQUEST, resumed.stdout)


if __name__ == "__main__":
    unittest.main()
