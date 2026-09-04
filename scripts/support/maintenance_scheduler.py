"""Install bounded Tao Agent OS maintenance as a macOS LaunchAgent."""

from __future__ import annotations

import os
import plistlib
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
    loaded = _launchctl(["print", service]).returncode == 0
    matches = current == expected

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
