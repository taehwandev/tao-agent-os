"""Antigravity's own end of the status line: how it is installed and invoked.

What the line is made of is shared with Claude Code and tested once, in
`test_statusline.py`. What is tested here is the part that is AGY's alone.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.agy_setup import _STATUSLINE_MARKER, _merge_agy_statusline
from support.setup_config_files import _status_marker, read_json

RENDERER = ROOT / "scripts" / "agy_statusline.py"
ALIAS = "agy-statusline"
SCRIPT = "agy_statusline.py"
MERGE = staticmethod(_merge_agy_statusline)


def _render(payload: object, *arguments: str) -> tuple[int, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    done = subprocess.run(
        [sys.executable, str(RENDERER), *arguments],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "NO_COLOR": "1"},
    )
    return done.returncode, done.stdout


class EntryPointTests(unittest.TestCase):
    def test_the_script_draws_the_line_for_a_payload_on_stdin(self) -> None:
        # The renderer is reached as a program, not as an import, so the wiring
        # from stdin through to stdout is its own thing to check.
        code, out = _render({
            "cwd": "/nowhere",
            "rate_limits": {"five_hour": {"used_percentage": 65}},
        })

        self.assertEqual(0, code)
        self.assertEqual("5h \u2588\u2588\u258a\u2591\u2591\u2591\u2591\u2591  35%  \u2502  /nowhere", out)

    def test_it_never_fails_on_input_it_cannot_read(self) -> None:
        for payload in ("not json", "", "[]"):
            with self.subTest(payload=payload):
                code, out = _render(payload)
                self.assertEqual(0, code)
                self.assertEqual("", out)

    def test_the_chain_argument_reaches_the_renderer(self) -> None:
        code, out = _render({"cwd": "/nowhere"}, "--chain", "echo theirs")

        self.assertEqual(0, code)
        self.assertEqual("/nowhere  theirs", out)


class LauncherTests(unittest.TestCase):
    def test_the_renderer_is_reachable_through_the_stable_launcher(self) -> None:
        # The installed status-line entry names the alias, not a path, so the
        # launcher it is written into has to know that alias or every draw is a
        # soft failure.
        from support.stable_launcher import _launcher_script_text

        self.assertIn(f'"{ALIAS}": "{SCRIPT}"', _launcher_script_text())
        self.assertTrue(RENDERER.exists())


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


if __name__ == "__main__":
    unittest.main()
