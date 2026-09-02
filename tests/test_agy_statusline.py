from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agy_statusline
from support.agy_setup import _STATUSLINE_MARKER, _merge_agy_statusline
from support.runtime_quota import gauge, remaining_summary
from support.setup_config_files import _status_marker, read_json

RENDERER = ROOT / "scripts" / "agy_statusline.py"


def _render(payload: object, *arguments: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    done = subprocess.run(
        [sys.executable, str(RENDERER), *arguments],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
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
        self.assertEqual("5h ██▊░░░░░  35%  │  7d ███████▌  94%", out)

    def test_a_weekly_only_limit_is_drawn_as_a_gauge(self) -> None:
        # A runtime may expose only its weekly budget. That must stay a visual
        # gauge rather than disappear merely because no five-hour window exists.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {"weekly": {"used_percentage": 25}},
        })

        self.assertEqual(0, code)
        self.assertEqual("7d ██████░░  75%", out)

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
        self.assertEqual("!5h ▌░░░░░░░   7%  │  7d ███████▌  94%", out)

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
        self.assertEqual("5h ███████▏  89%  │  7d █████▎░░  65%", out)

    def test_a_list_of_windows_is_read_too(self) -> None:
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": [
                {"kind": "five_hour", "used_percentage": 20},
                {"kind": "seven_day", "used_percentage": 40},
            ],
        })

        self.assertEqual(0, code)
        self.assertEqual("5h ██████▍░  80%  │  7d ████▊░░░  60%", out)

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
        self.assertEqual("5h ██████▍░  80%", out)

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
        self.assertEqual("5h ██████▍░  80%", out)

    def test_nothing_is_drawn_when_the_payload_carries_no_limits(self) -> None:
        for payload in ({}, {"cwd": "/nowhere"}, {"rate_limits": None}, "not json", ""):
            with self.subTest(payload=payload):
                code, out = _render(payload)
                self.assertEqual(0, code)
                self.assertEqual("", out)


class GaugeTests(unittest.TestCase):
    def test_the_bar_fills_to_what_is_left(self) -> None:
        self.assertEqual("████████", gauge(100))
        self.assertEqual("████░░░░", gauge(50))
        self.assertEqual("░░░░░░░░", gauge(0))

    def test_a_window_with_anything_left_never_draws_as_empty(self) -> None:
        # An exhausted window and one with a little left are the two states it
        # matters most to tell apart, and rounding would draw them the same.
        for percent in (1, 2, 3):
            with self.subTest(percent=percent):
                self.assertNotEqual("░" * 8, gauge(percent))
        self.assertEqual("░" * 8, gauge(0))

    def test_partial_cells_keep_nearby_levels_distinguishable(self) -> None:
        # Whole blocks round 3% and 12% to the same picture. The eighth-block
        # cell is what carries the difference at the end that matters.
        self.assertNotEqual(gauge(3), gauge(12))
        self.assertNotEqual(gauge(21), gauge(35))

    def test_every_bar_is_the_same_width(self) -> None:
        # A gauge that changed width would move the number beside it on every
        # redraw.
        for percent in range(0, 101):
            with self.subTest(percent=percent):
                self.assertEqual(8, len(gauge(percent)), gauge(percent))

    def test_the_bar_never_shrinks_as_more_is_left(self) -> None:
        filled = [
            sum(1 for cell in gauge(percent) if cell != "░") for percent in range(101)
        ]
        self.assertEqual(sorted(filled), filled)

    def test_the_number_is_padded_so_the_tail_stops_jittering(self) -> None:
        for percent, expected in ((7, "  7%"), (35, " 35%"), (100, "100%")):
            with self.subTest(percent=percent):
                summary = remaining_summary({"five_hour": {"used_percentage": 100 - percent}})
                self.assertTrue(summary.endswith(expected), summary)


def _loc(path: Path) -> str:
    home = Path.home().resolve()
    try:
        rel = path.resolve().relative_to(home)
        return f"~/{rel}" if str(rel) != "." else "~"
    except ValueError:
        return str(path.resolve())


class LocationTests(unittest.TestCase):
    def test_location_under_home_uses_tilde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            work = home / "git" / "project"
            work.mkdir(parents=True)
            code, out = _render({"cwd": str(work)}, env={**os.environ, "HOME": str(home)})
            self.assertEqual(0, code)
            self.assertEqual("~/git/project", out)

    def test_location_at_home_uses_tilde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            code, out = _render({"cwd": str(home)}, env={**os.environ, "HOME": str(home)})
            self.assertEqual(0, code)
            self.assertEqual("~", out)

    def test_nonexistent_location_is_ignored(self) -> None:
        code, out = _render({"cwd": "/nowhere/does/not/exist"})
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
            self.assertEqual(f"{_loc(project)}  │  task 2/4", out)

    def test_a_project_with_no_open_run_shows_location_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text(
                json.dumps({"runs": [{"command": "task", "state": "completed"}]}),
                encoding="utf-8",
            )

            code, out = _render({"cwd": str(project)})

            self.assertEqual(0, code)
            self.assertEqual(_loc(project), out)

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
            self.assertEqual(f"{_loc(project)}  │  task", out)

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
            self.assertEqual(f"{_loc(project)}  │  task 1/2", out)

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
            self.assertEqual(f"{_loc(project)}  │  review 0/1", out)

    def test_a_directory_inside_the_project_still_finds_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])
            inside = project / "src" / "deep"
            inside.mkdir(parents=True)

            code, out = _render({"cwd": str(inside)})

            self.assertEqual(0, code)
            self.assertEqual(f"{_loc(inside)}  │  task 1/1", out)


class WholeLineTests(unittest.TestCase):
    def test_taos_own_segments_are_divided_the_same_way_throughout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(
                project,
                evidence_name="statusline.json",
                gates=list("abcdefgh"),
                recorded=list("abcde"),
            )

            code, out = _render({
                "cwd": str(project),
                "rate_limits": {
                    "five_hour": {"used_percentage": 65},
                    "seven_day": {"used_percentage": 6},
                },
            })

            self.assertEqual(0, code)
            self.assertEqual(
                f"5h ██▊░░░░░  35%  │  7d ███████▌  94%  │  {_loc(project)}  │  task 5/8",
                out,
            )

    def test_someone_elses_text_is_not_claimed_by_this_layout(self) -> None:
        # A divider in front of the chain's output would present it as another
        # field of this line. It is a separate tool's text.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])

            code, out = _render({"cwd": str(project)}, "--chain", "echo theirs")

            self.assertEqual(0, code)
            self.assertEqual(f"{_loc(project)}  │  task 1/1  theirs", out)


class ChainTests(unittest.TestCase):
    def test_what_already_held_the_slot_keeps_its_output(self) -> None:
        code, out = _render(
            {"cwd": "/nowhere", "rate_limits": {"five_hour": {"used_percentage": 20}}},
            "--chain",
            "echo held-this-before",
        )

        self.assertEqual(0, code)
        self.assertEqual("5h ██████▍░  80%  held-this-before", out)

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
        self.assertEqual("5h ██████▍░  80%", out)

    def test_a_chain_that_fails_is_not_an_error_here(self) -> None:
        code, out = _render(
            {"cwd": "/nowhere", "rate_limits": {"five_hour": {"used_percentage": 20}}},
            "--chain",
            "exit 3",
        )

        self.assertEqual(0, code)
        self.assertEqual("5h ██████▍░  80%", out)


class InstallTests(unittest.TestCase):
    MANAGED = f"{_STATUSLINE_MARKER} '/tao/bin/tao-hook' agy-statusline"

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

            self.assertEqual("installed", _merge_agy_statusline(target, "tao statusline", False))

            config = read_json(target)
            self.assertEqual(
                {"type": "command", "command": "tao statusline", "enabled": True}, config["statusLine"]
            )
            self.assertEqual("opus", config["model"])

    def test_another_tools_status_line_is_kept_and_chained(self) -> None:
        # Taking this slot would silently switch off whatever meter or terminal
        # integration was using it.
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp), {"type": "command", "command": "node spill.mjs --chain 'orca.sh'"}
            )

            self.assertEqual("installed", _merge_agy_statusline(target, "tao statusline", False))

            self.assertEqual(
                "tao statusline --chain 'node spill.mjs --chain '\\''orca.sh'\\'''",
                read_json(target)["statusLine"]["command"],
            )

    def test_a_command_that_merely_mentions_the_alias_is_not_ours(self) -> None:
        # The terminal integration already in this slot chains a script called
        # `agy-statusline.sh`. Recognising a managed entry by the alias
        # matched it and dropped the meter in front of it -- the exact eviction
        # the chain exists to prevent.
        with tempfile.TemporaryDirectory() as tmp:
            theirs = "node spill.mjs --chain '/home/me/.orca/agy-statusline.sh'"
            target = self._settings(Path(tmp), {"type": "command", "command": theirs})

            _merge_agy_statusline(target, self.MANAGED, False)

            self.assertIn("spill.mjs", read_json(target)["statusLine"]["command"])

    def test_reinstalling_does_not_nest_a_second_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp), {"type": "command", "command": "node spill.mjs"}
            )
            _merge_agy_statusline(target, self.MANAGED, False)
            first = read_json(target)["statusLine"]["command"]

            self.assertEqual("ok", _merge_agy_statusline(target, self.MANAGED, False))
            self.assertEqual(first, read_json(target)["statusLine"]["command"])
            self.assertEqual(1, first.count("--chain"))

    def test_a_moved_installation_is_repaired_without_losing_the_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(
                Path(tmp),
                {
                    "type": "command",
                    "command": f"{_STATUSLINE_MARKER} '/old/tao' agy-statusline"
                    " --chain 'node spill.mjs'",
                },
            )

            self.assertEqual("installed", _merge_agy_statusline(target, self.MANAGED, False))

            self.assertEqual(
                f"{self.MANAGED} --chain 'node spill.mjs'",
                read_json(target)["statusLine"]["command"],
            )

    def test_configure_agy_installs_marker_and_alias(self) -> None:
        from support.agy_setup import configure_agy
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            cli_settings = home / ".gemini" / "antigravity-cli" / "settings.json"
            cli_settings.parent.mkdir(parents=True)
            cli_settings.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
            (home / ".gemini" / "config").mkdir(parents=True)
            (home / ".antigravity").mkdir(parents=True)

            with unittest.mock.patch("pathlib.Path.home", return_value=home), unittest.mock.patch("support.agy_setup.Path.home", return_value=home):
                configure_agy(
                    False,
                    root=ROOT,
                    scripts_dir=ROOT / "scripts",
                    launcher_path=Path("/custom/tao-hook"),
                    spill_available=False,
                )

            data = read_json(cli_settings)
            statusline_cmd = data["statusLine"]["command"]
            self.assertTrue(statusline_cmd.startswith(f"{_STATUSLINE_MARKER} "))
            self.assertIn("'/custom/tao-hook' agy-statusline", statusline_cmd)

    def test_a_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(Path(tmp), None)

            self.assertEqual(
                "would_update", _merge_agy_statusline(target, "tao statusline", True)
            )
            self.assertNotIn("statusLine", read_json(target))

    def test_every_status_this_merger_returns_is_one_the_report_knows(self) -> None:
        # The report prints anything it does not recognise as MISSING. This
        # merger was written from the Claude one and inherited a word outside
        # that vocabulary, so a correctly installed status line reported as
        # missing on every check.
        with tempfile.TemporaryDirectory() as tmp:
            target = self._settings(Path(tmp), None)
            statuses = {
                _merge_agy_statusline(target, self.MANAGED, True),
                _merge_agy_statusline(target, self.MANAGED, False),
                _merge_agy_statusline(target, self.MANAGED, False),
            }

            for status in statuses:
                with self.subTest(status=status):
                    self.assertNotEqual("MISSING", _status_marker(status))


class LauncherTests(unittest.TestCase):
    def test_the_renderer_is_reachable_through_the_stable_launcher(self) -> None:
        # The installed status-line entry names the alias, not a path, so the
        # launcher it is written into has to know that alias or every draw is a
        # soft failure.
        from support.stable_launcher import _launcher_script_text

        self.assertIn('"agy-statusline": "agy_statusline.py"', _launcher_script_text())
        self.assertTrue(RENDERER.exists())


class ModuleTests(unittest.TestCase):
    def test_an_unreadable_registry_leaves_the_line_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text("{ not json", encoding="utf-8")

            self.assertIsNone(agy_statusline.open_run(project))


if __name__ == "__main__":
    unittest.main()
