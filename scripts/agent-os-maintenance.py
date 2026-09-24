#!/usr/bin/env python3
"""Run bounded Tao Agent OS recovery and retention maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_os_maintenance import (
    DEFAULT_RETENTION_SECONDS,
    format_project_line,
    run_all_maintenance,
    run_maintenance,
)
from agent_run_evidence import DEFAULT_ORPHAN_AFTER_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain Tao Agent OS runtime state")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="the checkout to maintain; with --all-projects, the Tao root",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        help=(
            "maintain the Tao root, every project in ~/.tao/projects.json, every "
            "checkout with Tao run state directly under a search root, and their "
            "linked worktrees under .tao/worktrees"
        ),
    )
    parser.add_argument(
        "--projects-registry",
        type=Path,
        default=None,
        help="projects registry to read instead of ~/.tao/projects.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report per-project counts and change nothing",
    )
    parser.add_argument("--stale-after-seconds", type=int, default=3600)
    parser.add_argument("--retention-seconds", type=int, default=DEFAULT_RETENTION_SECONDS)
    parser.add_argument(
        "--orphan-after-seconds", type=int, default=DEFAULT_ORPHAN_AFTER_SECONDS
    )
    parser.add_argument("--max-records", type=int, default=100)
    args = parser.parse_args(argv)
    options = {
        "retention_seconds": args.retention_seconds,
        "stale_after_seconds": args.stale_after_seconds,
        "max_records": args.max_records,
        "orphan_after_seconds": args.orphan_after_seconds,
    }
    if not args.all_projects:
        print(json.dumps(
            run_maintenance(args.project, dry_run=args.dry_run, **options),
            sort_keys=True,
        ))
        return 0

    summary = run_all_maintenance(
        args.project,
        projects_registry=args.projects_registry,
        dry_run=args.dry_run,
        **options,
    )
    for checkout, result in summary["projects"].items():
        print(format_project_line(checkout, result))
    failed = sum("error" in result for result in summary["projects"].values())
    mode = "dry run, nothing changed" if args.dry_run else "applied"
    print(f"checkouts: {len(summary['projects'])} errors: {failed} ({mode})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
