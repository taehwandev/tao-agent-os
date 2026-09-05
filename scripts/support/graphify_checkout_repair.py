"""Opt-in repair of the installed Graphify checkout block, not its package."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path


_START = "# graphify-checkout-hook-start"
_END = "# graphify-checkout-hook-end"
_VERSION = "# tao-graphify-checkout:v1"
_GUARD = '''BRANCH_SWITCH=$3
# tao-graphify-checkout:v1
[ "${GRAPHIFY_SKIP_HOOK:-0}" = "1" ] && exit 0
[ "$PREV_HEAD" = "$NEW_HEAD" ] && exit 0
export GRAPHIFY_PREV_HEAD="$PREV_HEAD" GRAPHIFY_NEW_HEAD="$NEW_HEAD"
'''
_REBUILD = '''    # Hooks belong to the active checkout, not a copied graph's saved root.
    _root = Path.cwd()
    import subprocess
    _diff = subprocess.run(
        ['git', 'diff', '--name-only', '-z', os.environ['GRAPHIFY_PREV_HEAD'],
         os.environ['GRAPHIFY_NEW_HEAD'], '--'],
        cwd=_root, capture_output=True,
    )
    _changed = None
    if _diff.returncode == 0:
        _changed = [Path(os.fsdecode(p)) for p in _diff.stdout.split(bytes([0])) if p]
        if not _changed:
            sys.exit(0)
    # An unavailable old commit (including a new worktree's zero OID) retains
    # the upstream full-rebuild fallback instead of guessing an empty change.
    _rebuild_code(_root, changed_paths=_changed, force=_force)'''


def repair_checkout_hook(project: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Repair only a recognized Graphify block; preserve all other hook bytes."""

    result: dict[str, object] = {"ready": False, "changed": False, "dry_run": dry_run}
    try:
        project = project.resolve()
        top = Path(_git(project, "rev-parse", "--show-toplevel")).resolve()
        if project != top:
            raise ValueError("project must be the Git checkout root")
        common = (project / _git(project, "rev-parse", "--git-common-dir")).resolve()
        hook = project / _git(project, "rev-parse", "--git-path", "hooks/post-checkout")
        result["path"] = str(hook)
        resolved = hook.resolve()
        if not (resolved.is_relative_to(common) or resolved.is_relative_to(project)):
            raise ValueError("external hooksPath is outside this project's repair scope")
        if hook.is_symlink() or not hook.is_file():
            raise ValueError("post-checkout must be an existing regular non-symlink file")
        original = hook.read_bytes()
        updated = _patched(original.decode("utf-8")).encode("utf-8")
        if updated != original and not dry_run:
            _write_repair(hook, original, updated)
        result.update(ready=True, changed=updated != original)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as error:
        result["reason"] = str(error)
    return result


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=project, check=True, capture_output=True, text=True
    ).stdout.strip()


def _patched(content: str) -> str:
    if content.count(_START) != 1 or content.count(_END) != 1:
        raise ValueError("one recognized Graphify checkout block is required")
    start, end = content.index(_START), content.index(_END)
    if end <= start:
        raise ValueError("Graphify checkout markers are out of order")
    block = content[start:end]
    if _VERSION in block:
        if _GUARD not in block or _REBUILD not in block:
            raise ValueError("modified Tao checkout repair block; manual review required")
        return content
    replacements = (
        ("BRANCH_SWITCH=$3\n", _GUARD),
        ("    _rebuild_code(_root, force=_force)", _REBUILD),
    )
    if "# Installed by: graphify hook install" not in block:
        raise ValueError("checkout block is not recognized as Graphify-installed")
    for old, new in replacements:
        if block.count(old) != 1:
            raise ValueError("unsupported Graphify checkout template; left unchanged")
        block = block.replace(old, new, 1)
    return content[:start] + block + content[end:]


def _write_repair(hook: Path, original: bytes, updated: bytes) -> None:
    mode = stat.S_IMODE(hook.stat().st_mode)
    backup = hook.with_name(hook.name + ".tao-before-repair")
    if not backup.exists():
        with backup.open("xb") as stream:
            stream.write(original)
        backup.chmod(mode)
    descriptor, name = tempfile.mkstemp(prefix=".tao-checkout-", dir=hook.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
        temporary.chmod(mode)
        if hook.read_bytes() != original:
            raise ValueError("checkout hook changed during repair; retry after review")
        os.replace(temporary, hook)
    finally:
        temporary.unlink(missing_ok=True)
