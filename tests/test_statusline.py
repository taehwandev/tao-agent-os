"""The line itself, tested once for both runtimes that render it."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.runtime_quota import (
    BOLD,
    CYAN,
    DIM,
    RED,
    RESET,
    SEPARATOR,
    YELLOW,
    gauge,
    level_color,
    remaining_summary,
)
from support.statusline import color_enabled, render, shorten_path
from support.tao_run_state import open_run, work_segment

# The palette deliberately has no green entry, so the tests name the code
# they must never find rather than importing one that does not exist.
GREEN = "\033[32m"


def _strip(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)

HOME = Path("/home/someone")


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
                "started_at": "2026-09-03T09:00:00+00:00",
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


def _line(payload: object, chain: str = "") -> str:
    return render(payload if isinstance(payload, str) else json.dumps(payload), chain)


class QuotaTests(unittest.TestCase):
    def test_the_line_reports_what_is_left_not_what_is_spent(self) -> None:
        # The payload states the fraction used, which answers "how much have I
        # burned". The question the status line exists for is the other one.
        line = _line({
            "rate_limits": {
                "five_hour": {"used_percentage": 65},
                "seven_day": {"used_percentage": 6},
            },
        })

        self.assertEqual("5h ██▊░░░░░  35%  │  7d ███████▌  94%", line)

    def test_a_weekly_only_limit_is_drawn_as_a_gauge(self) -> None:
        # A runtime may expose only its weekly budget. That must stay a visual
        # gauge rather than disappear merely because no five-hour window exists.
        line = _line({"rate_limits": {"weekly": {"used_percentage": 25}}})

        self.assertEqual("7d ██████░░  75%", line)

    def test_a_window_running_out_is_marked(self) -> None:
        line = _line({"rate_limits": {"five_hour": {"used_percentage": 93.4}}})

        self.assertEqual("!5h ▌░░░░░░░   7%", line)

    def test_the_other_runtimes_spelling_of_the_same_windows_is_read(self) -> None:
        # Codex states the same two windows as primary and secondary with an
        # explicit length. Reading a window by the fields it must have, rather
        # than by one layout, is what lets one renderer serve every runtime.
        line = _line({
            "rate_limits": {
                "primary": {"used_percent": 11.0, "window_minutes": 300},
                "secondary": {"used_percent": 35.0, "window_minutes": 10080},
            },
        })

        self.assertEqual("5h ███████▏  89%  │  7d █████▎░░  65%", line)

    def test_a_list_of_windows_is_read_too(self) -> None:
        line = _line({
            "rate_limits": [
                {"kind": "five_hour", "used_percentage": 20},
                {"kind": "seven_day", "used_percentage": 40},
            ],
        })

        self.assertEqual("5h ██████▍░  80%  │  7d ████▊░░░  60%", line)

    def test_a_window_this_renderer_cannot_name_is_left_out(self) -> None:
        # An unlabelled percentage is worse than no percentage: the reader
        # cannot tell which budget it is about.
        for extra in ({"some_new_window": {"used_percentage": 90}},
                      {"hourly": {"used_percent": 50, "window_minutes": 60}}):
            with self.subTest(extra=extra):
                line = _line({
                    "rate_limits": {"five_hour": {"used_percentage": 20}, **extra},
                })
                self.assertEqual("5h ██████▍░  80%", line)

    def test_nothing_is_drawn_when_the_payload_carries_nothing(self) -> None:
        for payload in ({}, {"rate_limits": None}, "not json", ""):
            with self.subTest(payload=payload):
                self.assertEqual("", _line(payload))


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
        self.assertNotEqual(gauge(3), gauge(12))
        self.assertNotEqual(gauge(21), gauge(35))

    def test_every_bar_is_the_same_width(self) -> None:
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


class WorkingPathTests(unittest.TestCase):
    def test_home_is_folded_the_way_a_shell_prompt_folds_it(self) -> None:
        self.assertEqual("~/git/tao", shorten_path("/home/someone/git/tao", HOME))
        self.assertEqual("~", shorten_path("/home/someone", HOME))

    def test_a_path_outside_home_is_left_alone(self) -> None:
        self.assertEqual("/private/tmp/x", shorten_path("/private/tmp/x", HOME))

    def test_a_path_that_fits_keeps_every_segment(self) -> None:
        # These are the paths an operator reads rather than scans, so they are
        # worth the width.
        for directory in ("/home/someone/git/tao-agent-os",
                          "/home/someone/git/tao-agent-os/scripts"):
            with self.subTest(directory=directory):
                self.assertNotIn("…", shorten_path(directory, HOME))

    def test_the_middle_gives_way_and_both_names_survive(self) -> None:
        # The project and the leaf are what answer "where am I". What sits
        # between them is boilerplate: every task worktree lives under the same
        # `.tao/worktrees`.
        self.assertEqual(
            "~/git/tao-agent-os/…/gauge",
            shorten_path("/home/someone/git/tao-agent-os/.tao/worktrees/gauge", HOME),
        )

    def test_a_long_leaf_is_never_truncated(self) -> None:
        # A half-written worktree name is worse than a long one: it is the part
        # that tells two worktrees apart.
        shortened = shorten_path(
            "/home/someone/git/tao-agent-os/.tao/worktrees/codex-quota-gauge", HOME
        )

        self.assertTrue(shortened.endswith("/codex-quota-gauge"), shortened)

    def test_no_directory_draws_nothing(self) -> None:
        self.assertEqual("", shorten_path("", HOME))
        self.assertEqual("", _line({"rate_limits": None}))

    def test_the_path_shown_is_where_the_session_started(self) -> None:
        # A label that moved under you would be answering a question nobody
        # asked. The point of naming the path is to recognise which checkout
        # this window belongs to, and that is fixed when the window opens.
        line = _line({
            "cwd": "/moved/here",
            "workspace": {"project_dir": "/started/here", "current_dir": "/moved/here"},
        })

        self.assertEqual("/started/here", line)

    def test_the_directory_it_has_is_used_when_there_is_only_one(self) -> None:
        for payload, expected in (
            ({"workspace": {"current_dir": "/only"}}, "/only"),
            ({"cwd": "/only"}, "/only"),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(expected, _line(payload))

    def test_the_run_reported_is_the_one_where_work_is_happening(self) -> None:
        # The other half of the pair: the session may have started elsewhere,
        # but the open run lives where commands are actually running.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])

            segment = work_segment({
                "workspace": {"project_dir": "/started/here", "current_dir": str(project)},
            })

            self.assertEqual("task 1/1", segment)


class CurrentWorkTests(unittest.TestCase):
    def test_the_open_run_is_named_with_how_far_it_has_to_go(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json",
                    gates=["a", "b", "c", "d"], recorded=["a", "b"])

            self.assertEqual("task 2/4", work_segment({"cwd": str(project)}))

    def test_a_project_with_no_open_run_says_nothing(self) -> None:
        # A line that names something on every draw stops being read for the
        # draws where it names something real.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text(
                json.dumps({"runs": [{"command": "task", "state": "completed"}]}),
                encoding="utf-8",
            )

            self.assertEqual("", work_segment({"cwd": str(project)}))

    def test_a_ledger_belonging_to_another_run_is_not_counted(self) -> None:
        # `.tao/gate-evidence.json` is tracked, so a fresh worktree starts life
        # holding a finished run's ledger. Without the binding check a new run
        # would report that run's progress as its own.
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="mine.json")
            (project / ".tao" / "evidence" / "mine-gate-evidence.json").write_text(
                json.dumps({
                    "preflight_evidence": str(project / ".tao" / "evidence" / "other.json"),
                    "entries": [{"gate": g, "status": "SUCCESS"} for g in "abcdefg"],
                }),
                encoding="utf-8",
            )

            self.assertEqual("task", work_segment({"cwd": str(project)}))

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

            self.assertEqual("task 1/2", work_segment({"cwd": str(project)}))

    def test_a_directory_inside_the_project_still_finds_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])
            inside = project / "src" / "deep"
            inside.mkdir(parents=True)

            self.assertEqual("task 1/1", work_segment({"cwd": str(inside)}))

    def test_an_unreadable_registry_leaves_the_line_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            (project / ".tao" / "run-registry.json").write_text("{ not json", encoding="utf-8")

            self.assertIsNone(open_run(project))


class ColorTests(unittest.TestCase):
    def _windows(self, five: int, seven: int) -> dict:
        return {
            "rate_limits": {
                "five_hour": {"used_percentage": 100 - five},
                "seven_day": {"used_percentage": 100 - seven},
            },
        }

    def test_the_line_says_the_same_things_without_colour(self) -> None:
        # Colour is emphasis, never the message. Stripping every escape has to
        # leave exactly the line that would have been drawn with colour off.
        payload = self._windows(7, 61)
        painted = _line(payload)
        plain = render(json.dumps(payload), color=True)

        self.assertEqual(painted, _strip(plain))
        self.assertNotIn("\033", painted)

    def test_a_window_is_coloured_by_how_much_is_left(self) -> None:
        for remaining, expected in ((94, CYAN), (65, CYAN), (32, YELLOW),
                                    (16, YELLOW), (15, RED), (4, RED)):
            with self.subTest(remaining=remaining):
                self.assertIn(expected, level_color(remaining))

    def test_the_ramp_avoids_the_pair_most_often_confused(self) -> None:
        # Green and red are the pair colour-vision deficiency most often
        # collapses, so the ramp does not rely on it, and no entry is green.
        ramp = {level_color(remaining) for remaining in range(101)}

        self.assertEqual(3, len(ramp))
        self.assertTrue(all(GREEN not in entry for entry in ramp), ramp)

    def test_running_out_is_also_said_without_colour(self) -> None:
        # The mark and the gauge length carry the same warning, so a reader who
        # cannot separate the hues loses nothing.
        low = render(json.dumps(self._windows(7, 61)), color=True)

        self.assertIn("!5h", _strip(low))
        self.assertIn(BOLD, low)

    def test_context_recedes_so_the_quota_is_what_is_seen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json", gates=["a"], recorded=["a"])

            line = render(
                json.dumps({"cwd": str(project), **self._windows(65, 94)}), color=True
            )

            # The quota's own windows are joined by the same divider, so the
            # line is a segment per window, then the location, then the run.
            *windows, location, work = line.split(SEPARATOR)
            self.assertTrue(location.startswith(DIM), location)
            self.assertTrue(work.startswith(DIM), work)
            for window in windows:
                with self.subTest(window=window):
                    self.assertFalse(window.startswith(DIM), window)

    def test_no_color_in_the_environment_turns_it_off(self) -> None:
        # A status line is exactly the sort of output someone captures or reads
        # through a tool that does not interpret escapes.
        self.assertFalse(color_enabled({"NO_COLOR": "1"}))
        self.assertFalse(color_enabled({"NO_COLOR": "anything"}))
        self.assertTrue(color_enabled({}))
        self.assertTrue(color_enabled({"NO_COLOR": ""}))
        self.assertTrue(color_enabled({"NO_COLOR": "   "}))

    def test_every_painted_run_is_closed(self) -> None:
        # An unterminated escape bleeds into whatever the terminal draws next,
        # and a status line is redrawn beside other output constantly.
        line = render(json.dumps(self._windows(7, 94)), color=True)

        self.assertTrue(line.endswith(RESET), repr(line[-12:]))
        # One reset per painted segment: here, one window that is running out
        # and one that is not.
        self.assertEqual(2, line.count(RESET))
        self.assertEqual("", _strip(line).split(SEPARATOR)[0].split("!")[0])


class WholeLineTests(unittest.TestCase):
    def test_what_is_left_then_where_then_what_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            _open_run(project, command="task", evidence_name="statusline.json")
            _ledger(project, evidence_name="statusline.json",
                    gates=list("abcdefgh"), recorded=list("abcde"))

            line = _line({
                "cwd": str(project),
                "rate_limits": {
                    "five_hour": {"used_percentage": 65},
                    "seven_day": {"used_percentage": 6},
                },
            })

            self.assertEqual(
                "5h ██▊░░░░░  35%  │  7d ███████▌  94%"
                f"  │  {shorten_path(str(project))}  │  task 5/8",
                line,
            )

    def test_a_project_with_no_open_run_still_says_where_it_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))

            line = _line({"cwd": str(project)})

            self.assertEqual(shorten_path(str(project)), line)

    def test_a_directory_that_no_longer_exists_is_still_named(self) -> None:
        # An earlier version dropped the segment when the directory was gone.
        # That blanks it exactly when it is most worth reading -- a worktree
        # removed out from under a session -- and costs a stat on every redraw.
        line = _line({"cwd": "/gone/with/the/worktree"})

        self.assertEqual("/gone/with/the/worktree", line)

    def test_someone_elses_text_is_not_claimed_by_this_layout(self) -> None:
        # A divider in front of the chain's output would present it as another
        # field of this line. It is a separate tool's text.
        line = _line({"rate_limits": {"five_hour": {"used_percentage": 20}}},
                     "echo theirs")

        self.assertEqual("5h ██████▍░  80%  theirs", line)

    def test_the_chain_is_handed_the_untouched_payload(self) -> None:
        line = _line({"marker": "verbatim"}, "cat")

        self.assertIn('"marker": "verbatim"', line)

    def test_a_chain_that_hangs_cannot_hold_the_frame(self) -> None:
        # The status line is redrawn constantly. One slow draw is invisible; a
        # hung one takes the terminal with it.
        line = _line({"rate_limits": {"five_hour": {"used_percentage": 20}}}, "sleep 30")

        self.assertEqual("5h ██████▍░  80%", line)

    def test_a_chain_that_fails_is_not_an_error_here(self) -> None:
        line = _line({"rate_limits": {"five_hour": {"used_percentage": 20}}}, "exit 3")

        self.assertEqual("5h ██████▍░  80%", line)


if __name__ == "__main__":
    unittest.main()
