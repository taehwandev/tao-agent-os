"""Install a stable Tao Agent OS launcher for user-level runtime hooks."""

from __future__ import annotations

import os
from pathlib import Path


LAUNCHER_NAME = "tao-hook"
STATE_DIR_NAME = ".tao"
ROOT_POINTER_NAME = "tao-root"


def stable_launcher_path() -> Path:
    return Path.home() / STATE_DIR_NAME / "bin" / LAUNCHER_NAME


def stable_root_pointer_path() -> Path:
    return Path.home() / STATE_DIR_NAME / ROOT_POINTER_NAME


def ensure_stable_launcher(root: Path, dry_run: bool) -> list[dict]:
    """Install or verify the home-stable launcher and root pointer."""
    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    root_text = f"{root.resolve()}\n"
    launcher_text = _launcher_script_text()

    launcher_ok = (
        launcher_path.exists()
        and _read_text(launcher_path) == launcher_text
        and _is_executable(launcher_path)
    )
    pointer_ok = pointer_path.exists() and _read_text(pointer_path) == root_text

    if dry_run:
        return [
            {
                "tool": "tao",
                "hook": "stable_launcher",
                "status": "ok" if launcher_ok else "missing",
                "path": str(launcher_path),
            },
            {
                "tool": "tao",
                "hook": "root_pointer",
                "status": "ok" if pointer_ok else "missing",
                "path": str(pointer_path),
            },
        ]

    launcher_status = "ok"
    pointer_status = "ok"
    if not launcher_ok:
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        launcher_path.write_text(launcher_text)
        launcher_path.chmod(0o755)
        launcher_status = "installed"
    if not pointer_ok:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(root_text)
        pointer_status = "installed"

    return [
        {"tool": "tao", "hook": "stable_launcher", "status": launcher_status, "path": str(launcher_path)},
        {"tool": "tao", "hook": "root_pointer", "status": pointer_status, "path": str(pointer_path)},
    ]


def stable_launcher_issue(root: Path) -> str:
    """Return a preflight warning when the stable launcher is absent or stale."""
    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    if not launcher_path.exists() or _read_text(launcher_path) != _launcher_script_text() or not _is_executable(launcher_path):
        return (
            "Tao Agent OS stable launcher is missing or stale. "
            f"Run: python3 {root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    if _read_text(pointer_path) != f"{root.resolve()}\n":
        return (
            "Tao Agent OS root pointer is missing or stale. "
            f"Run: python3 {root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    return ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _launcher_script_text() -> str:
    return """#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

STATE_DIR_NAME = ".tao"
ROOT_POINTER_NAME = "tao-root"
REQUIRED_MARKERS = ("AGENTS.md", "index.md", "scripts/workflow.py")
SCRIPT_ALIASES = {
    "workflow": "workflow.py",
    "agent-hook": "agent-hook.py",
    "agent-preflight": "agent-preflight.py",
    "agent-finish-check": "agent-finish-check.py",
    "execution-capsule": "agent_execution_capsule.py",
    "agent-entry": "agent-entry.py",
    "project-discover": "project-discover.py",
    "setup-agent-hooks": "setup-agent-hooks.py",
    "agent-os-status": "agent-os-status.py",
    "agent-os-watchdog": "agent-os-watchdog.py",
    "agent-os-maintenance": "agent-os-maintenance.py",
    "agent-room": "agent-room.py",
    "workflow-dispatch": "workflow_dispatch.py",
    "workflow-dispatch-launch": "workflow_dispatch_launch.py",
    "claude-pretool-gate": "claude_pretool_gate.py",
    "claude-continuation-hook": "claude_continuation_hook.py",
    "claude-stop-gate": "claude_stop_gate.py",
    "codex-stop-gate": "codex_stop_gate.py",
}
HOOK_ALIASES = {
    "start",
    "cancel",
    "fingerprint",
    "handoff",
    "resume",
    "checkpoint",
    "gate",
    "gate-batch",
    "review",
    "finish",
    "skill-feedback",
    "skill-draft",
    "skill-curate",
    "skill-review",
    "skill-maintenance",
    "repair-verify",
}
# Calling agent-finish-check.py directly skips agent-hook.py's repair-cycle
# ceremony (the structural repair receipt checks in
# main()) entirely -- it is a lower-level fallback for human debugging only,
# never the normal agent path. Require an explicit opt-in so an agent cannot
# casually use it to dodge the wrapped `finish` hook's guardrails.
DIRECT_FINISH_CHECK_ENV = "TAO_ALLOW_DIRECT_FINISH_CHECK"

def main():
    if len(sys.argv) < 2:
        return _soft_fail("missing Tao Agent OS script alias")

    script_alias = sys.argv[1]
    passthrough_args = list(sys.argv[2:])
    if script_alias in HOOK_ALIASES:
        script_name = "agent-hook.py"
        passthrough_args.insert(0, script_alias)
    elif script_alias == "agent-finish-check" and os.environ.get(DIRECT_FINISH_CHECK_ENV) != "1":
        return _soft_fail(
            "direct agent-finish-check is a human-debugging fallback and skips the "
            "finish hook's repair-cycle checks; run 'tao-hook finish' instead, "
            f"or set {DIRECT_FINISH_CHECK_ENV}=1 to use it directly on purpose"
        )
    else:
        script_name = SCRIPT_ALIASES.get(script_alias)
    if not script_name:
        return _soft_fail(f"unsupported Tao Agent OS script alias: {script_alias}")

    root = _find_root()
    if root is None:
        return _soft_fail(
            "Tao Agent OS root is not configured. Run setup-agent-hooks.py from the current Tao Agent OS checkout."
        )

    script = root / "scripts" / script_name
    if not script.is_file():
        return _soft_fail(
            "Tao Agent OS root pointer is stale. Run setup-agent-hooks.py from the current Tao Agent OS checkout."
        )

    env = os.environ.copy()
    env.setdefault("TAO_HOME", str(root))
    result = subprocess.run([sys.executable, str(script), *passthrough_args], env=env, check=False)
    if result.returncode and env.get("TAO_HOOK_SOFT_FAIL") == "1":
        return 0
    return result.returncode

def _find_root():
    candidates: list[Path] = []
    env_root = os.environ.get("TAO_HOME", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())

    pointer_path = Path.home() / STATE_DIR_NAME / ROOT_POINTER_NAME
    try:
        pointer = pointer_path.read_text().strip()
    except OSError:
        pointer = ""
    if pointer:
        candidates.append(Path(pointer).expanduser())

    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.extend(cwd.parents)
    candidates.extend(
        [
            Path.home() / ".tao-agent-os",
            Path.home() / "tao-agent-os",
            Path.home() / "git" / "tao-agent-os",
            Path.home() / "Documents" / "KeyFlowVault" / "tao-agent-os",
            Path.home() / "GitHub" / "tao-agent-os",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_tao_root(resolved):
            return resolved
    return None

def _is_tao_root(path):
    return all((path / marker).exists() for marker in REQUIRED_MARKERS)

def _soft_fail(message):
    print(f"Tao Agent OS hook skipped: {message}", file=sys.stderr)
    if os.environ.get("TAO_HOOK_SOFT_FAIL") == "1":
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
"""
