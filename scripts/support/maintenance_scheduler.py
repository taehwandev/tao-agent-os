"""Install bounded Tao Agent OS maintenance as a macOS LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import pwd
import subprocess
import sys
from pathlib import Path


LAUNCH_AGENT_LABEL = "com.taehwandev.tao-agent-os.maintenance"
MAINTENANCE_INTERVAL_SECONDS = 24 * 60 * 60


def configure_maintenance_scheduler(root: Path, dry_run: bool) -> list[dict]:
    """Ensure one daily, bounded maintenance pass for the active Tao root."""
    if sys.platform != "darwin":
        return []

    resolved_root = root.resolve()
    target = (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{LAUNCH_AGENT_LABEL}.plist"
    )
    expected = _launch_agent_plist(resolved_root)
    current = target.read_bytes() if target.is_file() else b""
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LAUNCH_AGENT_LABEL}"
    matches = current == expected
    if Path.home().resolve() != _account_home().resolve():
        # launchd has one domain per account, not per HOME. A setup run under a
        # redirected HOME (a sandbox, a test) replaced the account's real agent
        # with one pointing at the sandbox checkout under the same label.
        if not dry_run and not matches:
            _write_atomic(target, expected)
        return [{"tool": "tao", "hook": "maintenance.launchd",
                 "status": "skipped_isolated_home", "path": str(target)}]
    loaded = _launchctl(["print", service]).returncode == 0

    if dry_run:
        status = "ok" if matches and loaded else "missing"
    elif matches and loaded:
        status = "ok"
    else:
        if not matches:
            _write_atomic(target, expected)
        if loaded:
            stopped = _launchctl(["bootout", service])
            if stopped.returncode != 0:
                raise RuntimeError("could not unload the stale Tao maintenance LaunchAgent")
        started = _launchctl(["bootstrap", domain, str(target)])
        if started.returncode != 0:
            raise RuntimeError("could not load the Tao maintenance LaunchAgent")
        status = "installed"

    return [
        {
            "tool": "tao",
            "hook": "maintenance.launchd",
            "status": status,
            "path": str(target),
        }
    ]


def _launch_agent_plist(root: Path) -> bytes:
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(root / "scripts" / "agent-os-maintenance.py"),
            "--all-projects",
            "--project",
            str(root),
            "--max-records",
            "100",
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "StartInterval": MAINTENANCE_INTERVAL_SECONDS,
        "ProcessType": "Background",
        "Nice": 10,
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)


def _account_home() -> Path:
    """The account's own home directory, whatever HOME says."""

    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _launchctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *arguments],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _write_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".plist.tmp")
    temporary.write_bytes(content)
    temporary.chmod(0o644)
    temporary.replace(target)
