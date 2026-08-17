"""The resume hook is the only way a session reaches a continuation packet."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_resume_test", "agent-hook.py")

from agent_continuation_store import continuation_path
from agent_run_registry import registry_path
from test_agent_continuation_checkpoint import Fixture
from test_agent_continuation_resume import age, free_fixture


def run_resume(project: Path, rules: Path, mode: str, *extra: str) -> tuple[int, str]:
    argv = [
        "agent-hook.py",
        "resume",
        mode,
        "--project",
        str(project),
        "--rules",
        str(rules),
        *extra,
    ]
    output = io.StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.dict("os.environ", {}, clear=True),
        redirect_stdout(output),
    ):
        code = agent_hook.main()
    return code, output.getvalue()


def project_bytes(project: Path) -> dict[str, bytes]:
    """Snapshot everything `--list` promises not to touch."""

    project = project.resolve()
    tracked = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".tao" not in path.relative_to(project).parts
    }
    for path in (
        registry_path(project),
        *sorted((project / ".tao" / "runs").rglob("continuation.json")),
        *sorted((project / ".tao" / "runs").rglob("gate-evidence.json")),
    ):
        if path.is_file():
            tracked[path.relative_to(project).as_posix()] = path.read_bytes()
    return tracked


class ListTests(unittest.TestCase):
    def test_the_listing_reports_the_packet_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "finish the lifecycle wiring")

            code, output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertIn("SUCCESS resume", output)
            self.assertIn("unfinished continuation packets: 1", output)
            self.assertIn(fixture.run_id, output)
            self.assertIn("finish the lifecycle wiring", output)
            self.assertIn("checkpoint=scope", output)

    def test_the_listing_changes_no_registry_packet_ledger_or_worktree_byte(self) -> None:
        """Discovery that mutates is not discovery; it is an unannounced claim.

        The heartbeat every other post-start hook writes would be enough to
        break this, which is why `resume` is excluded from it.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "list must not claim anything")
            fixture.gate("scope")
            before = project_bytes(fixture.project)

            code, _output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertEqual(before, project_bytes(fixture.project))
            self.assertGreaterEqual(len(before), 3)

    def test_an_invalid_packet_is_listed_without_rendering_its_prose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "prose that must never be rendered")
            path = continuation_path(fixture.project, fixture.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["notes"] = "a transcript"
            path.write_text(json.dumps(payload), encoding="utf-8")

            code, output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertIn("status=invalid_packet", output)
            self.assertNotIn("prose that must never be rendered", output)


class LastTests(unittest.TestCase):
    def test_the_newest_free_packet_is_claimed_and_reported_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "resume the wiring after a crash")

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(0, code)
            self.assertIn("SUCCESS resume", output)
            self.assertIn("resume result: ready", output)
            self.assertIn("resume checkpoint: scope", output)
            self.assertIn("objective: resume the wiring after a crash", output)
            self.assertIn(str(fixture.binding_path), output)

    def test_a_blocked_newest_packet_is_refused_and_no_older_one_is_offered(self) -> None:
        """The caller asking for the last thing they were doing has the least
        context in which to notice they were handed something else."""

        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "an older task that must not be resumed")
            newer = Fixture(directory, project=older.project, rules=older.rules)
            newer.checkpoint("initial", work={"objective": "the newest task, still held"})
            age(newer, minutes=0, owner_pid=1, run_id=newer.run_id)
            before = json.loads(registry_path(older.project).read_text(encoding="utf-8"))

            code, output = run_resume(older.project, older.rules, "--last")

            self.assertEqual(1, code)
            self.assertIn("FAIL resume", output)
            self.assertIn("resume result: live_owner_refused", output)
            self.assertIn(newer.run_id, output)
            self.assertNotIn(older.run_id, output)
            self.assertNotIn("an older task that must not be resumed", output)
            self.assertEqual(before, json.loads(registry_path(older.project).read_text(encoding="utf-8")))

    def test_a_refusal_renders_no_semantic_work_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "prose behind an invalid packet")
            path = continuation_path(fixture.project, fixture.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["work"]["objective"] = "x" * 400
            path.write_text(json.dumps(payload), encoding="utf-8")

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(1, code)
            self.assertIn("resume result: invalid_packet", output)
            self.assertNotIn("x" * 300, output)

    def test_an_empty_checkout_refuses_instead_of_inventing_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()

            code, output = run_resume(project, project, "--last")

            self.assertEqual(1, code)
            self.assertIn("resume result: not_found", output)
            self.assertIn("start a fresh run", output)


class NamedRunTests(unittest.TestCase):
    """Several sessions share one checkout, so the newest slot is not mine."""

    def test_naming_a_run_claims_it_while_another_session_holds_the_newest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "the task this session left behind")
            newer = Fixture(directory, project=mine.project, rules=mine.rules)
            newer.checkpoint("initial", work={"objective": "another session, still running"})
            age(newer, minutes=0, owner_pid=1, run_id=newer.run_id)

            blocked, _ = run_resume(mine.project, mine.rules, "--last")
            code, output = run_resume(mine.project, mine.rules, "--last", "--run-id", mine.run_id)

            self.assertEqual(1, blocked)
            self.assertEqual(0, code)
            self.assertIn("resume result: ready", output)
            self.assertIn(f"run: {mine.run_id}", output)
            self.assertIn("objective: the task this session left behind", output)
            self.assertNotIn("another session, still running", output)

    def test_naming_a_run_that_is_not_unfinished_claims_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "a task that must not be handed over")
            before = json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))

            code, output = run_resume(fixture.project, fixture.rules, "--last", "--run-id", "0" * 32)

            self.assertEqual(1, code)
            self.assertIn("resume result: not_found", output)
            self.assertIn("refusal reason: run_id_not_unfinished", output)
            self.assertNotIn("a task that must not be handed over", output)
            self.assertEqual(
                before, json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))
            )


class ModeTests(unittest.TestCase):
    def test_a_run_id_is_rejected_for_the_listing_it_cannot_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            argv = [
                "agent-hook.py",
                "resume",
                "--list",
                "--run-id",
                "0" * 32,
                "--project",
                str(project),
                "--rules",
                str(project),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.dict("os.environ", {}, clear=True),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    agent_hook.main()
            self.assertEqual(2, raised.exception.code)

    def test_exactly_one_mode_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for flags in ([], ["--list", "--last"]):
                argv = [
                    "agent-hook.py",
                    "resume",
                    "--project",
                    str(project),
                    "--rules",
                    str(project),
                    *flags,
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.dict("os.environ", {}, clear=True),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        agent_hook.main()
                self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
