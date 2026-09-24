"""Shared fixtures that make the hook test modules cheap to run.

Importing this module puts ``scripts/`` on ``sys.path``, so a test module that
imports production code works when it is run alone, not only when another
module happened to add the path first.

``fake_vibeguard_environment`` puts a stand-in ``vibeguard`` first on ``PATH``.
The lifecycle hooks run the audit on every start, review and finish; the real
binary costs a Node start per call and, when it is missing, falls back to
``npx @latest`` over the network. Modules that test the lifecycle rather than
the audit use the stand-in. It prints the same report shape the hooks parse
(``Overall: ✅ Ready``) and advertises ``--path`` in its help, so every hook
branch that depends on the audit sees a Ready verdict exactly as it would from
a clean project. Modules that assert on real audit findings must not use it.

``TemplateRepository`` builds a Git checkout once and copies it per test:
``git init`` plus a commit costs several subprocesses, and a copied checkout is
byte-for-byte the same starting state.
"""

from __future__ import annotations

import atexit
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


FAKE_VIBEGUARD_SCRIPT = """#!/bin/sh
# Stand-in for the VibeGuard CLI used by lifecycle tests.
case "$1" in
  --help|-h|help)
    printf '%s\\n' 'VibeGuard' '' 'Usage:' \\
      '  vibeguard audit [project] [--fix] [--strict] [--changed-only] [--path <path>] [--json] [--rules <path>] [--lang <en|ko>]'
    exit 0 ;;
  version)
    printf '%s\\n' 'vibeguard 0.0.0-test'
    exit 0 ;;
  audit)
    printf '%s\\n' '[VibeGuard Audit Report]' '' 'Project: test fixture' \\
      'Overall: ✅ Ready' 'Scanned: 1 file(s), skipped 0' '' \\
      '| Gate | Status | Message |' '| --- | --- | --- |' \\
      '| Security | ✅ Ready | No findings |'
    exit 0 ;;
esac
printf '%s\\n' 'Overall: ✅ Ready'
exit 0
"""

_FAKE_DIRECTORY: list[Path] = []


def fake_vibeguard_directory() -> Path:
    """Return a directory holding the stand-in ``vibeguard``, made once per process."""

    if not _FAKE_DIRECTORY:
        directory = Path(tempfile.mkdtemp(prefix="tao-fake-vibeguard-"))
        executable = directory / "vibeguard"
        executable.write_text(FAKE_VIBEGUARD_SCRIPT, encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        atexit.register(shutil.rmtree, directory, True)
        _FAKE_DIRECTORY.append(directory)
    return _FAKE_DIRECTORY[0]


def fake_vibeguard_environment() -> mock._patch_dict:
    """A patch that puts the stand-in first on ``PATH`` for this process and its children."""

    path = os.pathsep.join([str(fake_vibeguard_directory()), os.environ.get("PATH", "")])
    return mock.patch.dict(os.environ, {"PATH": path})


class TemplateRepository:
    """Build a checkout once with ``build(path)``; hand out copies of it.

    Only self-contained checkouts belong here: a linked worktree records
    absolute paths and would still point at the template after a copy.
    """

    def __init__(self, build: Callable[[Path], None], repositories: tuple[str, ...] = (".",)) -> None:
        # `repositories` names the checkouts inside the template, relative to
        # it. Their index is refreshed after each copy: a copy keeps file
        # times but not inodes or ctimes, and a plumbing command that does not
        # refresh the index itself would otherwise see every file as touched.
        self._build = build
        self._repositories = repositories
        self._directory: tempfile.TemporaryDirectory | None = None
        self._template: Path | None = None

    def template(self) -> Path:
        if self._template is None:
            self._directory = tempfile.TemporaryDirectory(prefix="tao-template-")
            self._template = Path(self._directory.name).resolve() / "template"
            self._template.mkdir()
            self._build(self._template)
        return self._template

    def copy_to(self, destination: Path) -> Path:
        """Copy the template into ``destination``, which may already exist."""

        shutil.copytree(self.template(), destination, symlinks=True, dirs_exist_ok=True)
        for relative in self._repositories:
            subprocess.run(
                ["git", "-C", str(destination / relative), "update-index", "-q", "--refresh"],
                check=False,
                capture_output=True,
            )
        return destination

    def cleanup(self) -> None:
        if self._directory is not None:
            self._directory.cleanup()
        self._directory = None
        self._template = None
