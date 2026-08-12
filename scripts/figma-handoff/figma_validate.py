#!/usr/bin/env python3
"""CLI entrypoint for network-free Figma handoff validation."""

from __future__ import annotations

import json
import sys

from figma_coverage import coverage_report
from figma_summary_validate import validate_summary
from figma_validation_report import format_report


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 figma_validate.py <design-summary.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as handle:
            summary = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"ERROR: cannot read summary: {error}", file=sys.stderr)
        return 2
    problems = validate_summary(summary)
    print(format_report(problems, coverage_report(summary)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
