from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "claude_stop_gate_under_test", ROOT / "scripts" / "claude_stop_gate.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

_FINISH_SPEC = importlib.util.spec_from_file_location(
    "agent_finish_check_under_test", ROOT / "scripts" / "agent-finish-check.py"
)
assert _FINISH_SPEC and _FINISH_SPEC.loader
finish_check = importlib.util.module_from_spec(_FINISH_SPEC)
_FINISH_SPEC.loader.exec_module(finish_check)

from support.claude_setup import _merge_claude_stop_gate
from support.setup_config_files import read_json


def _decide(payload: dict) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = gate.decide(payload)
    return code, buffer.getvalue()


def _blocked(out: str) -> bool:
    return bool(out) and json.loads(out).get("decision") == "block"


def _opt_in_project(base: Path) -> Path:
    project = base / "proj"
    (project / ".tao" / gate.SESSION_MARKER_DIR).mkdir(parents=True)
    (project / "AGENTS.md").write_text("uses tao\n", encoding="utf-8")
    return project


def _record_edit(project: Path, session_id: str, *, newer_than: Path | None = None) -> None:
    marker = gate.edit_activity_marker(project, session_id)
    marker.write_text("", encoding="utf-8")
    if newer_than is not None:
        # Filesystem timestamp granularity can tie these two writes; the gate
        # compares them, so make the ordering explicit rather than racy.
        stamp = newer_than.stat().st_mtime + 1
        os.utime(marker, (stamp, stamp))


def _age(marker: Path, seconds: float) -> None:
    """Backdate a marker so later real writes are unambiguously newer."""
    stamp = time.time() - seconds
    os.utime(marker, (stamp, stamp))


def _record_finish(project: Path, session_id: str, *, newer_than: Path | None = None) -> None:
    marker = gate.finished_marker(project, session_id)
    marker.write_text("", encoding="utf-8")
    if newer_than is not None:
        stamp = newer_than.stat().st_mtime + 1
        os.utime(marker, (stamp, stamp))


def _write_finish(project: Path, session_id: str | None = None) -> None:
    payload: dict = {}
    if session_id is not None:
        payload["runtime_session"] = {"runtime": "claude", "session_id": session_id}
    (project / ".tao" / "finish.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _payload(project: Path, session_id: str, **extra) -> dict:
    return {"session_id": session_id, "cwd": str(project), **extra}


class ClaudeStopGateTests(unittest.TestCase):
    def test_read_only_session_may_stop(self) -> None:
        # Nothing was mutated, so there is nothing to finish.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_editing_session_without_finish_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertTrue(_blocked(out))
        self.assertIn("finish", json.loads(out)["reason"])

    def test_finish_from_another_session_does_not_release_the_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _write_finish(project, "some-other-session")

            _, out = _decide(_payload(project, "s1"))

        self.assertTrue(_blocked(out))

    def test_failed_finish_does_not_release_the_stop(self) -> None:
        # `finish` stamps its session only when it records no failures, so a
        # failed run leaves no stamp and the gate stays closed.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _write_finish(project)

            _, out = _decide(_payload(project, "s1"))

        self.assertTrue(_blocked(out))

    def test_passing_finish_this_session_allows_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _write_finish(project, "s1")

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_per_session_record_survives_a_clobbered_finish_file(self) -> None:
        # Regression, observed live: a Codex re-verification run overwrote
        # finish.json, erasing the stamp from a passing Claude finish, and this
        # gate then blocked work that was properly completed.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            gate.finished_marker(project, "s1").write_text("", encoding="utf-8")
            _write_finish(project)  # another agent's finish, no session stamp

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_edits_after_a_finish_rearm_the_gate(self) -> None:
        # Regression, observed live: session b834fc2b had `.edited` more than an
        # hour after `.finished` and no `.stop-blocked` marker at all. The
        # finished marker was treated as a permanent pass, so one passing finish
        # made the gate silent for the rest of the session -- a whole second
        # task could be edited to completion and never gated again.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_finish(project, "s1")
            _record_edit(project, "s1", newer_than=gate.finished_marker(project, "s1"))

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertTrue(_blocked(out))
        self.assertIn("finish", json.loads(out)["reason"])

    def test_finish_after_its_edits_still_allows_the_stop(self) -> None:
        # The finish vouches for every edit that already existed when it ran.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _record_finish(project, "s1", newer_than=gate.edit_activity_marker(project, "s1"))

            code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_shared_finish_fallback_is_also_time_aware(self) -> None:
        # The finish.json fallback exists for finishes written before per-session
        # markers, so it must age the same way rather than becoming a loophole.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_finish(project, "s1")
            _record_edit(project, "s1", newer_than=project / ".tao" / "finish.json")

            _, out = _decide(_payload(project, "s1"))

        self.assertTrue(_blocked(out))

    def test_a_second_task_after_a_finish_is_gated_once(self) -> None:
        # End to end: finish the first task, edit again, and the gate must block
        # exactly once for the new batch -- not never, and not on every stop.
        # Markers are dated into the past so the block this records lands after
        # them, the way it does when the events are actually spaced out in time.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _age(gate.edit_activity_marker(project, "s1"), 300)
            _record_finish(project, "s1")
            _age(gate.finished_marker(project, "s1"), 200)

            _, after_finish = _decide(_payload(project, "s1"))
            _record_edit(project, "s1")
            _age(gate.edit_activity_marker(project, "s1"), 100)
            _, second_task = _decide(_payload(project, "s1"))
            _, asking_a_question = _decide(_payload(project, "s1"))

            self.assertEqual("", after_finish)
            self.assertTrue(_blocked(second_task))
            self.assertEqual("", asking_a_question)

    def test_finish_writes_the_per_session_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            finish_check.record_session_finished(
                project, {"runtime": "claude", "session_id": "s1"}
            )

            self.assertTrue(gate.finished_marker(project, "s1").exists())

    def test_finish_records_nothing_without_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            finish_check.record_session_finished(project, {})

            marker_dir = project / ".tao" / gate.SESSION_MARKER_DIR
            self.assertEqual([], list(marker_dir.iterdir()))

    def test_second_stop_without_new_edits_is_not_blocked_again(self) -> None:
        # A stop is not always a completion report: a session also stops to ask
        # the user a question. Blocking that a second time costs a round trip
        # and adds no enforcement, since the gate already reported the work.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")

            _, first = _decide(_payload(project, "s1"))
            _, second = _decide(_payload(project, "s1"))

            self.assertTrue(_blocked(first))
            self.assertEqual("", second)

    def test_further_edits_rearm_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")
            _decide(_payload(project, "s1"))

            _, quiet = _decide(_payload(project, "s1"))
            _record_edit(project, "s1", newer_than=gate.blocked_marker(project, "s1"))
            _, rearmed = _decide(_payload(project, "s1"))

            self.assertEqual("", quiet)
            self.assertTrue(_blocked(rearmed))

    def test_stop_checks_every_project_the_session_edited(self) -> None:
        # Regression: the Stop gate only looked at the cwd project. With a
        # finish there, it allowed a stop while another edited project had none.
        with tempfile.TemporaryDirectory() as tmp:
            here = _opt_in_project(Path(tmp) / "here")
            there = _opt_in_project(Path(tmp) / "there")
            _record_edit(here, "s1")
            gate.finished_marker(here, "s1").write_text("", encoding="utf-8")
            _record_edit(there, "s1")

            with patch.object(gate, "session_projects", lambda sid, cwd_root: [here, there]):
                _, out = _decide(_payload(here, "s1"))

        self.assertTrue(_blocked(out))

    def test_stop_hook_active_never_blocks_again(self) -> None:
        # The gate already blocked once and the model continued; blocking a
        # second time would trap the session in a loop.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")

            code, out = _decide(_payload(project, "s1", stop_hook_active=True))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_env_kill_switch_disables_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")

            with patch.dict("os.environ", {"TAO_CLAUDE_STOP_GATE": "0"}):
                code, out = _decide(_payload(project, "s1"))

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_non_tao_project_is_never_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _decide({"session_id": "s1", "cwd": tmp})

        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_malformed_stdin_fails_open(self) -> None:
        with patch.object(sys, "stdin", io.StringIO("not json{{")):
            code = gate.main()

        self.assertEqual(0, code)

    def test_block_reason_uses_resolved_absolute_launcher_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _record_edit(project, "s1")

            _, out = _decide(_payload(project, "s1"))

        reason = json.loads(out)["reason"]
        self.assertIn(str(gate.stable_launcher_path()), reason)
        self.assertNotIn("~/.tao", reason)

    def test_setup_installs_stop_gate_without_removing_user_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            user_hook = {"type": "command", "command": "my-own-stop-notifier"}
            target.write_text(json.dumps({
                "hooks": {"Stop": [{"matcher": "", "hooks": [user_hook]}]}
            }))
            command = "TAO_HOOK_SOFT_FAIL=1 /abs/tao-hook claude-stop-gate"

            status = _merge_claude_stop_gate(target, command, dry_run=False)
            commands = [
                hook["command"]
                for group in read_json(target)["hooks"]["Stop"]
                for hook in group["hooks"]
            ]

        self.assertEqual("installed", status)
        self.assertIn(command, commands)
        self.assertIn("my-own-stop-notifier", commands)

    def test_setup_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            target.write_text(json.dumps({"hooks": {}}))
            command = "TAO_HOOK_SOFT_FAIL=1 /abs/tao-hook claude-stop-gate"

            first = _merge_claude_stop_gate(target, command, dry_run=False)
            after_first = target.read_text()
            second = _merge_claude_stop_gate(target, command, dry_run=False)

            self.assertEqual("installed", first)
            self.assertEqual("ok", second)
            self.assertEqual(after_first, target.read_text())


_PRETOOL_SPEC = importlib.util.spec_from_file_location(
    "claude_pretool_gate_global_state_test", ROOT / "scripts" / "claude_pretool_gate.py"
)
assert _PRETOOL_SPEC and _PRETOOL_SPEC.loader
pretool = importlib.util.module_from_spec(_PRETOOL_SPEC)
_PRETOOL_SPEC.loader.exec_module(pretool)

_PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "agent_preflight_global_state_test", ROOT / "scripts" / "agent-preflight.py"
)
assert _PREFLIGHT_SPEC and _PREFLIGHT_SPEC.loader
agent_preflight = importlib.util.module_from_spec(_PREFLIGHT_SPEC)
_PREFLIGHT_SPEC.loader.exec_module(agent_preflight)

from support.global_state import STATE_HOME_ENV


def _make_global_state_dir(home: Path) -> Path:
    """Build a .tao that looks like the global install, not project state."""
    state = home / ".tao"
    (state / "bin").mkdir(parents=True)
    (state / "bin" / "tao-hook").write_text("#!/usr/bin/env python3\n")
    (state / "tao-root").write_text("/somewhere/tao-agent-os\n")
    (state / "projects.json").write_text("{}")
    (state / "claude-session-projects").mkdir()
    return state


class SessionStampReaderTests(unittest.TestCase):
    """This gate runs at every turn end, so what it loads is what it costs.

    Reading the session stamp used to be imported from `agent_runtime_session`,
    which pulls the run registry, the worker evidence, the execution capsule and
    the worktree fingerprints -- 19.5ms of the gate's 25.6ms of imports -- to
    supply two dictionary lookups the file's own broken-install fallback already
    contained verbatim.
    """

    CHAIN = ("agent_runtime_session", "agent_run_registry")

    def test_the_stop_gate_does_not_load_the_run_evidence_chain(self) -> None:
        probe = "\n".join(
            [
                "import sys",
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r})",
                "import json",
                "import claude_stop_gate",
                f"print(json.dumps([m for m in {self.CHAIN!r} if m in sys.modules]))",
            ]
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, check=True,
        )

        self.assertEqual([], json.loads(completed.stdout))

    def test_the_local_reader_matches_the_stamp_that_is_written(self) -> None:
        """The copy has to keep answering the shape `runtime_session()` makes."""

        from agent_runtime_session import recorded_session_id, runtime_session

        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s-42"}, clear=False):
            stamped = {"runtime_session": runtime_session()}

        self.assertEqual("s-42", gate.recorded_session_id(stamped))
        self.assertEqual(
            recorded_session_id(stamped), gate.recorded_session_id(stamped)
        )
        for malformed in ({}, {"runtime_session": None}, {"runtime_session": {}}, "x"):
            with self.subTest(payload=malformed):
                self.assertEqual(
                    recorded_session_id(malformed),
                    gate.recorded_session_id(malformed),
                )


class GlobalInstallIsNotAProjectTests(unittest.TestCase):
    """`.tao` names both the global install and per-project state.

    Both gates classified any directory containing a `.tao` as a project, so the
    home directory hosting the global install always classified as one. A
    harness write under `$HOME` (Claude's plan mode writes `~/.claude/plans/*.md`)
    then registered `$HOME` as a session project, and the Stop gate demanded a
    finish for `$HOME` that can never pass -- auditing `~` dies on `~/.Trash`.
    """

    def setUp(self) -> None:
        self._old_state_home = os.environ.get(STATE_HOME_ENV)

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop(STATE_HOME_ENV, None)
        else:
            os.environ[STATE_HOME_ENV] = self._old_state_home

    def test_global_install_directory_does_not_classify_as_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            state = _make_global_state_dir(home)
            os.environ[STATE_HOME_ENV] = str(state)

            self.assertFalse(gate.opts_in(home))
            self.assertFalse(pretool.opts_in(home))

    def test_global_markers_win_even_when_state_home_points_elsewhere(self) -> None:
        # A relocated or differently-rooted install must still be recognised, so
        # the discriminator cannot rely on the environment alone.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            _make_global_state_dir(home)
            os.environ[STATE_HOME_ENV] = str(Path(tmp) / "elsewhere" / ".tao")

            self.assertFalse(gate.opts_in(home))
            self.assertFalse(pretool.opts_in(home))

    def test_real_project_state_still_classifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ[STATE_HOME_ENV] = str(_make_global_state_dir(home))

            project = home / "git" / "repo"
            state = project / ".tao"
            state.mkdir(parents=True)
            (state / "preflight.json").write_text("{}")

            self.assertTrue(gate.opts_in(project))
            self.assertTrue(pretool.opts_in(project))

    def test_fresh_project_without_state_still_opts_in_by_marker_file(self) -> None:
        # A repo that has never run `start` has no .tao yet; the opt-in file is
        # what must keep working, or a fresh project can never begin.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ[STATE_HOME_ENV] = str(_make_global_state_dir(home))

            project = home / "git" / "fresh"
            project.mkdir(parents=True)
            (project / "AGENTS.md").write_text("# Tao Agent OS project\n")

            self.assertFalse((project / ".tao").exists())
            self.assertTrue(gate.opts_in(project))
            self.assertTrue(pretool.opts_in(project))

    def test_harness_plan_path_does_not_register_home_as_a_session_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            state = _make_global_state_dir(home)
            os.environ[STATE_HOME_ENV] = str(state)
            plans = home / ".claude" / "plans"
            plans.mkdir(parents=True)

            with patch.object(pretool.Path, "home", staticmethod(lambda: home)):
                self.assertIsNone(pretool.find_project_root(plans))
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = pretool.decide(
                        {
                            "tool_name": "Write",
                            "cwd": str(home),
                            "session_id": "harness-session",
                            "tool_input": {"file_path": str(plans / "x.md")},
                        }
                    )
                index = pretool.session_projects_index("harness-session")

            self.assertEqual(0, code)
            self.assertEqual("", buffer.getvalue())
            self.assertFalse(index.exists())

    def test_project_scoped_state_cannot_be_written_to_the_global_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ[STATE_HOME_ENV] = str(_make_global_state_dir(home))
            args = argparse.Namespace(
                evidence=None,
                project=home,
                worker_reservation_token="",
                parent_evidence=None,
            )

            with self.assertRaises(ValueError) as caught:
                agent_preflight.resolve_evidence_path(args, home)

            self.assertIn("global Tao Agent OS install directory", str(caught.exception))

    def test_project_scoped_state_is_allowed_for_a_project_without_state_yet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ[STATE_HOME_ENV] = str(_make_global_state_dir(home))
            project = home / "git" / "fresh"
            project.mkdir(parents=True)
            args = argparse.Namespace(
                evidence=None,
                project=project,
                worker_reservation_token="",
                parent_evidence=None,
            )

            self.assertEqual(
                project / ".tao" / "preflight.json",
                agent_preflight.resolve_evidence_path(args, project),
            )


class HostConfigDirIsNotAProjectTests(unittest.TestCase):
    """Setup writes the managed bridge into each runtime's own config directory.

    That makes `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` carry the opt-in
    token, so marker-file opt-in read those directories as projects and the edit
    gate demanded a workflow lifecycle before touching a session memory file --
    which VibeGuard then refused, because auditing `~/.claude` walks every
    transcript. `$HOME` was already excluded; this is the same case one level
    down.
    """

    def setUp(self) -> None:
        self._old_home = os.environ.get("HOME")

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home

    def test_runtime_config_directory_carrying_the_token_is_not_a_project(self) -> None:
        for name in (".claude", ".codex", ".gemini", ".antigravity"):
            with self.subTest(directory=name):
                with tempfile.TemporaryDirectory() as tmp:
                    home = Path(tmp) / "home"
                    home.mkdir()
                    os.environ["HOME"] = str(home)

                    config = home / name
                    config.mkdir()
                    # The managed bridge block is what puts the token here.
                    (config / "CLAUDE.md").write_text("# Tao Agent OS Bridge\n")
                    (config / "AGENTS.md").write_text("# Tao Agent OS Bridge\n")

                    self.assertFalse(gate.opts_in(config))
                    self.assertFalse(pretool.opts_in(config))

    def test_a_real_project_directory_still_opts_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            project = home / "git" / "some-repo"
            project.mkdir(parents=True)
            (project / "AGENTS.md").write_text("# tao project\n")

            self.assertTrue(gate.opts_in(project))
            self.assertTrue(pretool.opts_in(project))

    def test_a_hidden_directory_below_home_is_not_excluded(self) -> None:
        # Only an immediate child of $HOME is host configuration. A dotted
        # directory deeper in the tree can still be a checkout.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            project = home / "work" / ".hidden-repo"
            project.mkdir(parents=True)
            (project / "AGENTS.md").write_text("# tao project\n")

            self.assertTrue(gate.opts_in(project))
            self.assertTrue(pretool.opts_in(project))

    def test_an_immediate_hidden_git_repository_is_still_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            project = home / ".dotfiles"
            (project / ".git").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# tao project\n", encoding="utf-8")

            self.assertTrue(gate.opts_in(project))
            self.assertTrue(pretool.opts_in(project))
            self.assertEqual(project, gate.find_project_root(project))
            self.assertEqual(project, pretool.find_project_root(project))


if __name__ == "__main__":
    unittest.main()
