#!/usr/bin/env python3
"""Check Android external skill source manifest coverage."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from support.bounded_git import run_git


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "platforms/android/skills/android-external-skill-source-coverage/references/current-guidance.md"
SOURCES = {
    "android": Path("/private/tmp/notmid-tao-source-android-skills"),
    "compose": Path("/private/tmp/notmid-tao-source-compose-performance-skills"),
    "chrisbanes": Path("/private/tmp/notmid-tao-source-chrisbanes-skills"),
}


def main() -> int:
    if not MANIFEST.exists():
        print(f"missing manifest: {MANIFEST}", file=sys.stderr)
        return 1
    text = MANIFEST.read_text(encoding="utf-8")
    failed = False
    for name, source_root in SOURCES.items():
        if not source_root.exists():
            print(f"[{name}] missing source snapshot: {source_root}", file=sys.stderr)
            failed = True
            continue
        actual = actual_files(source_root)
        listed = listed_files(text, source_root)
        missing = sorted(actual - listed)
        stale = sorted(listed - actual)
        head = git_head(source_root)
        print(
            f"[{name}] commit={head} actual={len(actual)} listed={len(listed)} "
            f"missing={len(missing)} stale={len(stale)}"
        )
        if missing:
            failed = True
            print("missing:")
            for item in missing:
                print(f"- {item}")
        if stale:
            failed = True
            print("stale:")
            for item in stale:
                print(f"- {item}")
    return 1 if failed else 0


def actual_files(source_root: Path) -> set[str]:
    return {
        str(path.relative_to(source_root))
        for path in source_root.rglob("*")
        if is_manifest_relevant(source_root, path)
    }


def is_manifest_relevant(source_root: Path, path: Path) -> bool:
    if not path.is_file():
        return False
    relative = str(path.relative_to(source_root))
    return (
        path.name in {"SKILL.md", "README.md", "INDEX.md", "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md", "skills.schema.json"}
        or "/references/" in relative
        or relative.startswith("docs/")
    )


def listed_files(text: str, source_root: Path) -> set[str]:
    listed: set[str] = set()
    for match in re.finditer(r"`([^`]+)`", text):
        candidate = match.group(1)
        if candidate.startswith("/") or not (candidate.endswith(".md") or candidate.endswith(".json")):
            continue
        if (source_root / candidate).is_file():
            listed.add(candidate)
    return listed


def git_head(source_root: Path) -> str:
    result = run_git(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
