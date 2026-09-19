#!/usr/bin/env python3
"""Stateless preview of the final review's structural checks.

Owner: changed-source structural preview CLI.
Allowed imports: standard library and agent_review_structure.
Forbidden imports: lifecycle writers, gates, provider runtimes.
Callers/tests: refactor workflow; test_agent_structure_check.py.
Verification: CLI tests against temporary Git projects.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

from agent_review_structure import (
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
    structure_review,
)


def _run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--review-path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        report = structure_review(
            args.project.resolve(), REVIEW_SOURCE_FILE_LINE_LIMIT,
            REVIEW_FUNCTION_LINE_LIMIT, _run, args.review_path or None,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1
    print(json.dumps({
        "status": "FAIL" if report["failures"] else "SUCCESS",
        "scope": "Structural preview only; not behavior verification or review approval",
        "checked_paths": report["checked_paths"],
        "failures": report["failures"],
        "warnings": report["warnings"],
        "boundary_note_requirements": report["boundary_note_requirements"],
        "net_deletions": report["net_deletions"],
    }, indent=2, ensure_ascii=False))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
