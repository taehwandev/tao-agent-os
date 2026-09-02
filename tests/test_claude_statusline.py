from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_statusline
from support.claude_setup import _STATUSLINE_MARKER, _merge_claude_statusline
from support.setup_config_files import read_json

RENDERER = ROOT / "scripts" / "claude_statusline.py"


def _render(payload: object, *arguments: str) -> tuple[int, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    done = subprocess.run(
        [sys.executable, str(RENDERER), *arguments],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, done.stdout


def _project(root: Path) -> Path:
    (root / ".tao" / "evidence").mkdir(parents=True)
    return root


def _open_run(project: Path, *, command: str, evidence_name: str) -> None:
    (project / ".tao" / "run-registry.json").write_text(
        json.dumps({
            "schema_version": 1,
            "runs": [{
                "run_id": "a" * 32,
                "command": command,
                "evidence_name": evidence_name,
                "state": "running",
                "started_at": "2026-09-02T09:00:00+00:00",
            }],
        }),
        encoding="utf-8",
    )


def _ledger(project: Path, *, evidence_name: str, gates: list[str], recorded: list[str]) -> None:
    evidence = project / ".tao" / "evidence" / evidence_name
    evidence.write_text(json.dumps({"route": {"gates": gates}}), encoding="utf-8")
    ledger = project / ".tao" / "evidence" / f"{Path(evidence_name).stem}-gate-evidence.json"
    ledger.write_text(
        json.dumps({
            "preflight_evidence": str(evidence),
            "entries": [{"gate": gate, "status": "SUCCESS"} for gate in recorded],
        }),
        encoding="utf-8",
    )


class QuotaTests(unittest.TestCase):
    def test_the_line_reports_what_is_left_not_what_is_spent(self) -> None:
        # The payload states the fraction used, which answers "how much have I
        # burned". The question the status line exists for is the other one.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {
                "five_hour": {"used_percentage": 65},
                "seven_day": {"used_percentage": 6},
            },
        })

        self.assertEqual(0, code)
        self.assertEqual("5h 35% 7d 94%", out)

    def test_a_window_running_out_is_marked(self) -> None:
        # A number among other numbers is read as a number. The mark is what
        # makes the one window worth acting on look different from the rest.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {
                "five_hour": {"used_percentage": 93.4},
                "seven_day": {"used_percentage": 6},
            },
        })

        self.assertEqual(0, code)
        self.assertEqual("!5h 7% 7d 94%", out)

    def test_the_other_runtimes_spelling_of_the_same_windows_is_read(self) -> None:
        # Codex states the same two windows as primary and secondary with an
        # explicit length. Reading a window by the fields it must have, rather
        # than by one layout, is what lets this renderer serve both.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {
                "primary": {"used_percent": 11.0, "window_minutes": 300},
                "secondary": {"used_percent": 35.0, "window_minutes": 10080},
            },
        })

        self.assertEqual(0, code)
        self.assertEqual("5h 89% 7d 65%", out)

    def test_a_list_of_windows_is_read_too(self) -> None:
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": [
                {"kind": "five_hour", "used_percentage": 20},
                {"kind": "seven_day", "used_percentage": 40},
            ],
        })

        self.assertEqual(0, code)
        self.assertEqual("5h 80% 7d 60%", out)

    def test_a_window_this_renderer_cannot_name_is_left_out(self) -> None:
        # An unlabelled percentage is worse than no percentage: the reader
        # cannot tell which budget it is about.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {
                "five_hour": {"used_percentage": 20},
                "some_new_window": {"used_percentage": 90},
            },
        })

        self.assertEqual(0, code)
        self.assertEqual("5h 80%", out)

    def test_a_window_that_states_a_length_nobody_labels_is_left_out(self) -> None:
        # A stated length is believed over the name, so a runtime that adds an
        # hourly window arrives here as a real number with no label to draw it
        # under. Skipping on the label rather than on the length is what keeps
        # that from becoming a crash on every redraw.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {
                "five_hour": {"used_percentage": 20},
                "hourly": {"used_percent": 50, "window_minutes": 60},
            },
        })

        self.assertEqual(0, code)
        self.assertEqual("5h 80%", out)

    def test_nothing_is_drawn_when_the_payload_carries_no_limits(self) -> None:
        for payload in ({}, {"cwd": "/nowhere"}, {"rate_limits": None}, "not json", ""):
            with self.subTest(payload=payload):
                code, out = _render(payload)
                self.assertEqual(0, code)
                self.assertEqual("", out)


class CurrentWorkTests(unittest.TestCase):
    def test_the_open_run_is_named_with_how_far_it_has_to_go(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(
                project,
                evidence_name="statusline.json",
                gates=["a", "b", "c", "d"],
                recorded=["a", "b"],
            )

            code, out = _render({"cwd": str(project)})

            self.assertEqual(0, code)
            self.assertEqual("task 2/4", out)

    def test_a_project_with_no_open_run_says_nothing(self) -> None:
        # A line that names something on every draw stops being read for the
        # draws where it names something real.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text(
                json.dumps({"runs": [{"command": "task", "state": "completed"}]}),
                encoding="utf-8",
            )

            code, out = _render({"cwd": str(project)})

            self.assertEqual(0, code)
            self.assertEqual("", out)

    def test_a_ledger_belonging_to_another_run_is_not_counted(self) -> None:
        # `.tao/gate-evidence.json` is tracked, so a fresh worktree starts life
        # holding a finished run's ledger. Without the binding check a new run
        # would report that run's progress as its own.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="mine.json")
            stale = project / ".tao" / "evidence" / "mine-gate-evidence.json"
            stale.write_text(
                json.dumps({
                    "preflight_evidence": str(project / ".tao" / "evidence" / "someone-else.json"),
                    "entries": [{"gate": g, "status": "SUCCESS"} for g in "abcdefg"],
                }),
                encoding="utf-8",
            )

            code, out = _render({"cwd": str(project)})

            self.assertEqual(0, code)
            self.assertEqual("task", out)

    def test_only_recorded_gates_count_toward_the_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            evidence = project / ".tao" / "evidence" / "statusline.json"
            evidence.write_text(json.dumps({"route": {"gates": ["a", "b"]}}), encoding="utf-8")
            (project / ".tao" / "evidence" / "statusline-gate-evidence.json").write_text(
                json.dumps({
                    "preflight_evidence": str(evidence),
                    "entries": [
                        {"gate": "a", "status": "SUCCESS"},
                        {"gate": "b", "status": "FAIL"},
                        {"gate": "not on this route", "status": "SUCCESS"},
                    ],
                }),
                encoding="utf-8",
            )

            code, out = _render({"cwd": str(project)})

            self.assertEqual(0, code)
            self.assertEqual("task 1/2", out)

    def test_the_workspace_directory_wins_over_the_process_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="review", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=[])

            code, out = _render({
                "cwd": "/nowhere",
                "workspace": {"current_dir": str(project)},
            })

            self.assertEqual(0, code)
            self.assertEqual("review 0/1", out)

    def test_a_directory_inside_the_project_still_finds_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])
            inside = project / "src" / "deep"
            inside.mkdir(parents=True)

            code, out = _render({"cwd": str(inside)})

            self.assertEqual(0, code)
            self.assertEqual("task 1/1", out)


class ChainTests(unittest.TestCase):
    def test_what_already_held_the_slot_keeps_its_output(self) -> None:
        code, out = _render(
            {"cwd": "/nowhere", "rate_limits": {"five_hour": {"used_percentage": 20}}},
            "--chain",
            "echo held-this-before",
        )

        self.assertEqual(0, code)
        self.assertEqual("5h 80%  held-this-before", out)

    def test_the_chain_is_handed_the_untouched_payload(self) -> None:
        # The other tool reads the same JSON this renderer does; passing it
        # anything else would break the meter that was already working.
        code, out = _render({"cwd": "/nowhere", "marker": "verbatim"}, "--chain", "cat")

        self.assertEqual(0, code)
        self.assertIn('"marker": "verbatim"', out)

    def test_a_chain_that_hangs_cannot_hold_the_frame(self) -> None:
        # The status line is redrawn constantly. One slow draw is invisible; a
        # hung one takes the terminal with it.
        code, out = _render(
            {"cwd": "/nowhere", "rate_limits": {"five_hour": {"used_percentage": 20}}},
            "--chain",
            "sleep 30",
        )

        self.assertEqual(0, code)
        self.assertEqual("5h 80%", out)

    def test_a_chain_that_fails_is_not_an_error_here(self) -> None:
        code, out = _render(
            {"cwd": "/nowhere", "rate_limits": {"five_hour": {"used_percentage": 20}}},
            "--chain",
            "exit 3",
        )

        self.assertEqual(0, code)
        self.assertEqual("5h 80%", out)


class InstallTests(unittest.TestCase):
    MANAGED = f"{_STATUSLINE_MARKER} '/tao/bin/tao-hook' claude-statusline"

    def _settings(self, root: Path, statusline: object | None) -> Path:
        target = root / "settings.json"
        config: dict = {"model": "opus"}
        if statusline is not None:
            config["statusLine"] = statusline
        target.write_text(json.dumps(config), encoding="utf-8")
        return target

    def test_an_empty_slot_is_filled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(Path(tmp), None)

            self.assertEqual("updated", _merge_claude_statusline(target, "tao statusline", False))

            config = read_json(target)
            self.assertEqual(
                {"type": "command", "command": "tao statusline"}, config["statusLine"]
            )
            self.assertEqual("opus", config["model"])

    def test_another_tools_status_line_is_kept_and_chained(self) -> None:
        # Taking this slot would silently switch off whatever meter or terminal
        # integration was using it.
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp), {"type": "command", "command": "node spill.mjs --chain 'orca.sh'"}
            )

            self.assertEqual("updated", _merge_claude_statusline(target, "tao statusline", False))

            self.assertEqual(
                "tao statusline --chain 'node spill.mjs --chain '\\''orca.sh'\\'''",
                read_json(target)["statusLine"]["command"],
            )

    def test_a_command_that_merely_mentions_the_alias_is_not_ours(self) -> None:
        # The terminal integration already in this slot chains a script called
        # `claude-statusline.sh`. Recognising a managed entry by the alias
        # matched it and dropped the meter in front of it -- the exact eviction
        # the chain exists to prevent.
        with tempfile.TemporaryDirectory() as tmp:
            theirs = "node spill.mjs --chain '/home/me/.orca/claude-statusline.sh'"
            target = self._settings(Path(tmp), {"type": "command", "command": theirs})

            _merge_claude_statusline(target, self.MANAGED, False)

            self.assertIn("spill.mjs", read_json(target)["statusLine"]["command"])

    def test_reinstalling_does_not_nest_a_second_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp), {"type": "command", "command": "node spill.mjs"}
            )
            _merge_claude_statusline(target, self.MANAGED, False)
            first = read_json(target)["statusLine"]["command"]

            self.assertEqual("unchanged", _merge_claude_statusline(target, self.MANAGED, False))
            self.assertEqual(first, read_json(target)["statusLine"]["command"])
            self.assertEqual(1, first.count("--chain"))

    def test_a_moved_installation_is_repaired_without_losing_the_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp),
                {
                    "type": "command",
                    "command": f"{_STATUSLINE_MARKER} '/old/tao' claude-statusline"
                    " --chain 'node spill.mjs'",
                },
            )

            self.assertEqual("updated", _merge_claude_statusline(target, self.MANAGED, False))

            self.assertEqual(
                f"{self.MANAGED} --chain 'node spill.mjs'",
                read_json(target)["statusLine"]["command"],
            )

    def test_a_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(Path(tmp), None)

            self.assertEqual(
                "would-update", _merge_claude_statusline(target, "tao statusline", True)
            )
            self.assertNotIn("statusLine", read_json(target))


class LauncherTests(unittest.TestCase):
    def test_the_renderer_is_reachable_through_the_stable_launcher(self) -> None:
        # The installed status-line entry names the alias, not a path, so the
        # launcher it is written into has to know that alias or every draw is a
        # soft failure.
        from support.stable_launcher import _launcher_script_text

        self.assertIn('"claude-statusline": "claude_statusline.py"', _launcher_script_text())
        self.assertTrue(RENDERER.exists())


class ModuleTests(unittest.TestCase):
    def test_an_unreadable_registry_leaves_the_line_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text("{ not json", encoding="utf-8")

            self.assertIsNone(claude_statusline.open_run(project))


if __name__ == "__main__":
    unittest.main()
