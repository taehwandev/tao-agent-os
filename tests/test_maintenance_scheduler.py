from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.maintenance_scheduler import (
    LAUNCH_AGENT_LABEL,
    MAINTENANCE_INTERVAL_SECONDS,
    configure_maintenance_scheduler,
)


class MaintenanceSchedulerTests(unittest.TestCase):
    def test_installs_and_loads_one_bounded_daily_launch_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            root = Path(temp_dir) / "tao-agent-os"
            (root / "scripts").mkdir(parents=True)
            run_results = [
                subprocess.CompletedProcess([], 1),
                subprocess.CompletedProcess([], 0),
            ]
            with (
                patch("support.maintenance_scheduler.sys.platform", "darwin"),
                patch("support.maintenance_scheduler.sys.executable", "/usr/bin/python3"),
                patch("support.maintenance_scheduler.Path.home", return_value=home),
                patch("support.maintenance_scheduler.os.getuid", return_value=501),
                patch("support.maintenance_scheduler.subprocess.run", side_effect=run_results) as run,
            ):
                result = configure_maintenance_scheduler(root, dry_run=False)

            target = home / "Library/LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
            payload = plistlib.loads(target.read_bytes())

        self.assertEqual("installed", result[0]["status"])
        self.assertEqual(MAINTENANCE_INTERVAL_SECONDS, payload["StartInterval"])
        self.assertTrue(payload["RunAtLoad"])
        self.assertEqual(
            [
                "/usr/bin/python3",
                str(root.resolve() / "scripts/agent-os-maintenance.py"),
                "--project",
                str(root.resolve()),
                "--max-records",
                "100",
            ],
            payload["ProgramArguments"],
        )
        self.assertEqual("print", run.call_args_list[0].args[0][1])
        self.assertEqual("bootstrap", run.call_args_list[1].args[0][1])

    def test_check_reports_ok_only_when_config_matches_and_service_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            root = Path(temp_dir) / "tao-agent-os"
            (root / "scripts").mkdir(parents=True)
            target = home / "Library/LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
            with (
                patch("support.maintenance_scheduler.sys.platform", "darwin"),
                patch("support.maintenance_scheduler.sys.executable", "/usr/bin/python3"),
                patch("support.maintenance_scheduler.Path.home", return_value=home),
                patch("support.maintenance_scheduler.os.getuid", return_value=501),
                patch("support.maintenance_scheduler.subprocess.run", return_value=subprocess.CompletedProcess([], 1)),
            ):
                self.assertEqual(
                    "missing",
                    configure_maintenance_scheduler(root, dry_run=True)[0]["status"],
                )
            self.assertFalse(target.exists())

            with (
                patch("support.maintenance_scheduler.sys.platform", "darwin"),
                patch("support.maintenance_scheduler.sys.executable", "/usr/bin/python3"),
                patch("support.maintenance_scheduler.Path.home", return_value=home),
                patch("support.maintenance_scheduler.os.getuid", return_value=501),
                patch(
                    "support.maintenance_scheduler.subprocess.run",
                    side_effect=[
                        subprocess.CompletedProcess([], 1),
                        subprocess.CompletedProcess([], 0),
                    ],
                ),
            ):
                configure_maintenance_scheduler(root, dry_run=False)

            with (
                patch("support.maintenance_scheduler.sys.platform", "darwin"),
                patch("support.maintenance_scheduler.sys.executable", "/usr/bin/python3"),
                patch("support.maintenance_scheduler.Path.home", return_value=home),
                patch("support.maintenance_scheduler.os.getuid", return_value=501),
                patch("support.maintenance_scheduler.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
            ):
                self.assertEqual(
                    "ok",
                    configure_maintenance_scheduler(root, dry_run=True)[0]["status"],
                )

    def test_non_macos_setup_does_not_install_an_os_specific_scheduler(self) -> None:
        with patch("support.maintenance_scheduler.sys.platform", "linux"):
            self.assertEqual([], configure_maintenance_scheduler(Path("/tmp/tao"), False))


if __name__ == "__main__":
    unittest.main()
