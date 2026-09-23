"""Run unittest discovery and write its result to a separate local receipt."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


def _without_tao_scripts(entries: list[str]) -> list[str]:
    """Drop Tao's own script directories from the project's import path.

    Python puts this runner's directory first, so a project test importing a
    module the project lacks would otherwise import Tao's same-named module
    and could pass against the wrong code. The runner needs only the standard
    library, already imported above.
    """
    scripts = Path(__file__).resolve().parent
    tao = {scripts, scripts / "support"}
    return [entry for entry in entries if Path(entry or ".").resolve() not in tao]


def main() -> int:
    project, directory, pattern, receipt = sys.argv[1:5]
    sys.path[:] = [str(Path(project).resolve()), *_without_tao_scripts(sys.path)]
    suite = unittest.defaultTestLoader.discover(start_dir=directory, pattern=pattern)
    result = unittest.TextTestRunner().run(suite)
    Path(receipt).write_text(
        json.dumps({"tests_run": result.testsRun, "successful": result.wasSuccessful()}),
        encoding="utf-8",
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
