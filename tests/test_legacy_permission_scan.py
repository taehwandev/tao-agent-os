from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.permission_entries import _legacy_tao_python_scripts


class LegacyScanSkipsRuntimeStateTests(unittest.TestCase):
    """The cleanup scan walks the repository, which also holds live run state."""

    def _project(self) -> Path:
        project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        (project / "scripts").mkdir()
        (project / "scripts" / "agent-hook.py").write_text("", encoding="utf-8")
        return project

    def test_runtime_state_is_not_scanned(self) -> None:
        # .tao holds run evidence and task worktrees, not Tao source. A worktree
        # there repeats every script under a path that is deleted with the task,
        # so entries built from it name files that will not exist.
        project = self._project()
        run_dir = project / ".tao" / "runs" / "414f42c1ebf14948bd794cfd5a5b1efb"
        run_dir.mkdir(parents=True)
        (run_dir / "evidence.py").write_text("", encoding="utf-8")

        scripts = _legacy_tao_python_scripts(project / "scripts")

        self.assertFalse([path for path in scripts if ".tao" in path.parts])

    def test_a_directory_removed_mid_walk_costs_only_that_directory(self) -> None:
        # The maintenance job prunes finished runs while the installer walks the
        # tree, so a directory listed in its parent can be gone by the time the
        # walk descends into it. That raised FileNotFoundError out of the whole
        # install. Deleting it from under the walk is what os.scandir is patched
        # for here; the walk must skip it and finish the rest of the tree.
        project = self._project()
        (project / "kept" / "pkg").mkdir(parents=True)
        (project / "kept" / "pkg" / "module.py").write_text("", encoding="utf-8")
        doomed = project / "doomed"
        doomed.mkdir()
        (doomed / "pruned.py").write_text("", encoding="utf-8")

        real_scandir = os.scandir

        def vanishing_scandir(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            # rmtree itself scans by file descriptor, so only compare real paths.
            if isinstance(path, (str, os.PathLike)) and Path(path) == project:
                listing = real_scandir(path, *args, **kwargs)
                shutil.rmtree(doomed, ignore_errors=True)
                return listing
            return real_scandir(path, *args, **kwargs)

        with mock.patch.object(os, "scandir", vanishing_scandir):
            scripts = _legacy_tao_python_scripts(project / "scripts")

        self.assertIn(project / "kept" / "pkg" / "module.py", scripts)
        self.assertFalse([path for path in scripts if path.name == "pruned.py"])


if __name__ == "__main__":
    unittest.main()
