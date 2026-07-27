"""Shared Graphify bundle staging and user-level link helpers."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from support.graphify_contract import GLOBAL_CANONICAL_SKILL_DIR


def install_bundled_skill(source_dir: Path, home_path: Path) -> bool:
    """Atomically copy the runtime-owned Graphify bundle into the user home."""

    source = source_dir.resolve()
    if not (source / "SKILL.md").is_file():
        return False

    destination = home_path / GLOBAL_CANONICAL_SKILL_DIR
    try:
        if destination.resolve() == source:
            return True
    except OSError:
        pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(prefix=".graphify-global-", dir=destination.parent)
    )
    backup = destination.parent / ".graphify-global.previous"
    remove_path(backup)
    try:
        shutil.copytree(source, staged, dirs_exist_ok=True)
        if destination.exists() or destination.is_symlink():
            os.replace(destination, backup)
        os.replace(staged, destination)
    except OSError:
        remove_path(staged)
        if backup.exists() or backup.is_symlink():
            if destination.exists() or destination.is_symlink():
                remove_path(destination)
            os.replace(backup, destination)
        return False
    remove_path(backup)
    return (destination / "SKILL.md").is_file()


def runtime_link_ready(link: Path, canonical: Path) -> bool:
    if not link.is_symlink() or not (link / "SKILL.md").is_file():
        return False
    try:
        return link.resolve(strict=True) == canonical.resolve(strict=True)
    except OSError:
        return False


def replace_path_with_relative_link(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool,
) -> None:
    remove_path(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    relative_target = os.path.relpath(target, start=link.parent)
    link.symlink_to(relative_target, target_is_directory=target_is_directory)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
