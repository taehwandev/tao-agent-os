"""Run unittest discovery and write its result to a separate local receipt."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


def main() -> int:
    project, directory, pattern, receipt = sys.argv[1:5]
    sys.path.insert(0, str(Path(project).resolve()))
    suite = unittest.defaultTestLoader.discover(start_dir=directory, pattern=pattern)
    result = unittest.TextTestRunner().run(suite)
    Path(receipt).write_text(
        json.dumps({"tests_run": result.testsRun, "successful": result.wasSuccessful()}),
        encoding="utf-8",
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
