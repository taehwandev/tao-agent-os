#!/usr/bin/env python3
"""Convert flat Tao Agent OS guidance docs into skill bundles.

The migration is intentionally mechanical: each flat guidance card moves into a
small SKILL.md entrypoint plus references/current-guidance.md. Flat source
files are removed by default so agents do not retrieve duplicate guidance.
Use --keep-stubs only for a named temporary downstream/runtime compatibility
need.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from workflow_skill_paths import canonical_doc_path, guidance_reference_path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(\[[^\]]+\]\()([^)]+)(\))")
STUB_MARKER = "tao_skill_bundle_stub: true"


def main() -> int:
    args = parse_args()
    migrated = 0
    for source in source_docs():
        migrate_doc(source, keep_stub=args.keep_stubs)
        migrated += 1
    mode = "kept temporary stubs" if args.keep_stubs else "removed flat sources"
    print(f"migrated {migrated} flat guidance docs into skill bundles; {mode}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep-stubs",
        action="store_true",
        help="keep temporary flat compatibility stubs instead of deleting migrated source files",
    )
    return parser.parse_args()


def source_docs() -> list[Path]:
    docs: list[Path] = []
    docs.extend(sorted((ROOT / "common").glob("*.md")))
    docs.extend(path for path in sorted((ROOT / "workflows").glob("*.md")) if path.name != "README.md")
    docs.extend(sorted((ROOT / "product-patterns").glob("*.md")))
    for platform_dir in sorted((ROOT / "platforms").iterdir()):
        if platform_dir.is_dir():
            docs.extend(sorted(platform_dir.glob("*.md")))
    docs.extend(sorted((ROOT / "docs").glob("*.md")))
    return [path for path in docs if "/skills/" not in path.as_posix()]


def migrate_doc(source: Path, *, keep_stub: bool = False) -> None:
    relative = source.relative_to(ROOT).as_posix()
    skill_relative = canonical_doc_path(relative)
    reference_relative = guidance_reference_path(relative)
    skill = ROOT / skill_relative
    reference = ROOT / reference_relative
    skill.parent.mkdir(parents=True, exist_ok=True)
    reference.parent.mkdir(parents=True, exist_ok=True)

    current_text = source.read_text(encoding="utf-8")
    if STUB_MARKER in current_text and reference.exists():
        original_text = reference.read_text(encoding="utf-8")
    else:
        original_text = current_text
        reference.write_text(rewrite_links(original_text, source, reference), encoding="utf-8")

    title = extract_title(original_text, source.stem)
    skill.write_text(skill_text(skill_relative, title), encoding="utf-8")
    if keep_stub:
        source.write_text(stub_text(relative, skill_relative, reference_relative, title), encoding="utf-8")
    else:
        source.unlink()


def rewrite_links(text: str, old_path: Path, new_path: Path) -> str:
    old_parent = old_path.parent
    new_parent = new_path.parent

    def replace(match: re.Match[str]) -> str:
        prefix, raw_link, suffix = match.groups()
        link = raw_link.strip()
        target, rest = split_target(link)
        if not target or target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            return match.group(0)
        target_path = (old_parent / target.strip("<>")).resolve()
        if not target_path.exists():
            return match.group(0)
        if target_path.is_file() and target_path.suffix == ".md":
            try:
                target_relative = target_path.relative_to(ROOT).as_posix()
            except ValueError:
                target_relative = ""
            if target_relative and is_migrated_source(target_relative):
                target_path = ROOT / guidance_reference_path(target_relative)
        rewritten = os.path.relpath(target_path, new_parent).replace(os.sep, "/")
        return f"{prefix}{rewritten}{rest}{suffix}"

    return MARKDOWN_LINK_RE.sub(replace, text)


def split_target(link: str) -> tuple[str, str]:
    if "#" in link:
        target, anchor = link.split("#", 1)
        return target, "#" + anchor
    return link, ""


def is_migrated_source(relative: str) -> bool:
    return canonical_doc_path(relative) != relative


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback.replace("-", " ").title()


def skill_text(skill_relative: str, title: str) -> str:
    key = keyflow_id(skill_relative, "skill")
    return (
        f"---\n"
        f"keyflow_id: {key}\n"
        f"status: review\n"
        f"type: ai-generated\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"Use when routed to `{skill_relative}` or when work needs this "
        f"Tao Agent OS guidance area.\n\n"
        f"## Read\n\n"
        f"- `references/current-guidance.md` for the detailed guidance for this skill.\n"
        f"- Related `SKILL.md` entrypoints named by the reference before loading their "
        f"detailed references.\n\n"
        f"## Process\n\n"
        f"1. Read this entrypoint first to confirm this guidance area applies.\n"
        f"2. Open `references/current-guidance.md` only when the task actually touches "
        f"this area.\n"
        f"3. Follow the reference's decision rules, stop conditions, and verification "
        f"requirements before editing, reviewing, or reporting completion.\n\n"
        f"## Do Not\n\n"
        f"- Do not look for legacy flat compatibility paths; load this skill bundle "
        f"as the canonical context-loading target.\n"
        f"- Do not load broad references for unrelated work just because this skill was "
        f"nearby in the route.\n\n"
        f"## Verification\n\n"
        f"- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.\n"
        f"- If detailed guidance changes, validate links and frontmatter for "
        f"`references/current-guidance.md`.\n"
    )


def stub_text(source_relative: str, skill_relative: str, reference_relative: str, title: str) -> str:
    key = keyflow_id(source_relative, "compat")
    source_parent = (ROOT / source_relative).parent
    skill_link = os.path.relpath(ROOT / skill_relative, source_parent).replace(os.sep, "/")
    reference_link = os.path.relpath(ROOT / reference_relative, source_parent).replace(os.sep, "/")
    return (
        f"---\n"
        f"keyflow_id: {key}\n"
        f"status: review\n"
        f"type: compatibility-entrypoint\n"
        f"tao_skill_bundle_stub: true\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"This compatibility path has moved to the Tao Agent OS skill-bundle layout.\n\n"
        f"## Read\n\n"
        f"- `{skill_link}` for the canonical lightweight entrypoint.\n"
        f"- `{reference_link}` for the full detailed guidance that previously lived here.\n\n"
        f"## Verification\n\n"
        f"Routes should load `{skill_relative}` instead of this compatibility stub.\n"
    )


def keyflow_id(source_relative: str, suffix: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "_", source_relative.lower()).strip("_")
    return f"sys_{safe}_{suffix}"


if __name__ == "__main__":
    raise SystemExit(main())
