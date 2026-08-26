"""Allowlisted commands and contained targets for structural verification."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


UNITTEST_SELECTOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,200}$")
VERIFICATION_KINDS = {
    "py_compile",
    "unittest",
    "vibeguard",
    "workflow_validate",
}
Runner = Callable[[list[str], Path], dict[str, Any]]


def verification_workdir(
    *,
    verification_kind: str,
    target_root: Path,
    rules: Path,
) -> Path:
    return target_root if verification_kind == "unittest" else rules


def resolve_verification_target(
    project: Path, rules: Path, target: str
) -> tuple[Path, str, str, Path] | None:
    raw = Path(target.strip()).expanduser()
    candidates = [raw] if raw.is_absolute() else [project / raw, rules / raw]
    # Prefer rules when both names resolve to one checkout. Skill maintenance
    # is specifically allowed to change canonical Tao Agent OS files.
    roots = (("rules", rules.resolve()), ("project", project.resolve()))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        for scope, root in roots:
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            return resolved, scope, relative.as_posix(), root
    return None


def verification_target_is_changed(
    root: Path,
    target: Path,
    *,
    preflight: dict[str, Any] | None = None,
    target_relative: str = "",
) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return False
    result = run_verification_command(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", relative.as_posix()],
        root,
    )
    if result["returncode"] == 0 and bool(str(result.get("stdout") or "").strip()):
        return True
    if preflight is None or not target_relative:
        return False
    required_docs = (preflight.get("execution_snapshot") or {}).get("required_docs") or []
    baseline = next(
        (
            item
            for item in required_docs
            if isinstance(item, dict) and item.get("path") == target_relative
        ),
        None,
    )
    baseline_sha256 = str((baseline or {}).get("sha256") or "")
    if baseline_sha256:
        current_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        return current_sha256 != baseline_sha256
    return non_git_target_changed_after_preflight(
        root,
        target,
        preflight,
        git_status_returncode=int(result.get("returncode", 1)),
    )


def non_git_target_changed_after_preflight(
    root: Path,
    target: Path,
    preflight: dict[str, Any],
    *,
    git_status_returncode: int,
) -> bool:
    if git_status_returncode == 0:
        return False
    project = str(preflight.get("project") or "").strip()
    if not project:
        return False
    project_root = Path(project).expanduser().resolve()
    if root.resolve() == project_root:
        git_status = preflight.get("git_status") or {}
        if git_status.get("review_only") is not True:
            return False
    timestamp = str(preflight.get("timestamp") or "").strip()
    if not timestamp:
        return False
    try:
        started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        modified_at = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError):
        return False
    return modified_at > started_at.astimezone(timezone.utc)


def verification_command(
    *,
    project: Path,
    rules: Path,
    target: Path,
    verification_kind: str,
    test_selector: str,
) -> list[str]:
    if verification_kind == "workflow_validate":
        script = rules / "scripts" / "workflow.py"
        return [sys.executable, str(script), "validate"] if script.is_file() else []
    if verification_kind == "unittest":
        return (
            [sys.executable, "-m", "unittest", test_selector]
            if UNITTEST_SELECTOR_RE.fullmatch(test_selector)
            else []
        )
    if verification_kind == "py_compile":
        return [sys.executable, "-m", "py_compile", str(target)] if target.suffix == ".py" else []
    if verification_kind == "vibeguard":
        binary = shutil.which("vibeguard")
        if binary:
            return [binary, "audit", str(project), "--rules", str(rules)]
        return ["npx", "--yes", "@taehwandev/vibeguard", "audit", str(project), "--rules", str(rules)]
    return []


def run_verification_command(command: list[str], cwd: Path) -> dict[str, Any]:
    """Run one allowlisted check, and let it fail only for what it checks.

    The environment is inherited except for the bytecode cache location. The
    default interpreter on a macOS host is Xcode's Python, whose
    `sys.pycache_prefix` is an absolute path under the user's Library rather
    than a `__pycache__` beside the source; where a sandbox denies that path,
    `py_compile` exits non-zero with a PermissionError and a syntactically
    perfect file is recorded as a failed verification. `unittest` never showed
    this because bytecode written at import is best-effort -- only `py_compile`
    treats the write as the job, so only it turns a denied cache into a verdict.

    A private cache directory removes the dependency without hiding anything:
    `PYTHONDONTWRITEBYTECODE` cannot be used here, because suppressing the write
    is suppressing the check.
    """

    with tempfile.TemporaryDirectory(prefix="tao-verify-cache-") as cache:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONPYCACHEPREFIX": cache},
        )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
