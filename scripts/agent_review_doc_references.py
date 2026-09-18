"""Check the references in changed Markdown, instead of asking about them.

The docs route carried a `link/path check` gate whose evidence was the agent
writing that the links resolved. Nothing could refuse that sentence, and the one
failure it existed to catch -- a document moves and the references to it are left
behind -- is invisible from the moved file alone. These checks read the diff.

The rules are deliberately narrow, because a check that starts red is a check
nobody keeps. Measured across the 353 Markdown files in this repository before
the rules were chosen: local Markdown links broken 0, repository-rooted backtick
paths missing 4, files without frontmatter 0. All four of the missing paths were
mentions rather than references -- two elided patterns containing `...`, and two
examples of files a *target* repository would hold -- so `...` is excluded and
the scope is the changed files rather than the whole tree.
"""

from __future__ import annotations

import re
from pathlib import Path


MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|json|py))`")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
REQUIRED_FRONTMATTER_KEYS = ("keyflow_id", "status", "type")
# A backtick path is a reference only when it is rooted in this repository. A
# bare `SKILL.md` names a sibling by filename, and `README.md` in a list of what
# a target repository holds is not about this tree at all.
REPOSITORY_ROOTS = ("common/", "workflows/", "platforms/", "docs/", "scripts/", "tests/")
EXTERNAL_LINK = ("http://", "https://", "mailto:", "#")
MAX_REPORTED = 8


def doc_reference_failures(
    project: Path,
    changed_markdown: list[str],
    removed_paths: list[str],
) -> list[str]:
    """Return one failure line per broken reference rule, or an empty list.

    ``changed_markdown`` and ``removed_paths`` are repository-relative and come
    from the diff the review hook already computed.
    """

    failures: list[str] = []
    failures.extend(_broken_link_failures(project, changed_markdown))
    failures.extend(_frontmatter_failures(project, changed_markdown))
    failures.extend(_orphaned_reference_failures(project, removed_paths))
    return failures


def _broken_link_failures(project: Path, changed: list[str]) -> list[str]:
    broken: list[str] = []
    for relative in changed:
        path = project / relative
        text = _read(path)
        if text is None:
            continue
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(EXTERNAL_LINK):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                broken.append(f"{relative} -> {target}")
        for target in BACKTICK_PATH.findall(text):
            if "..." in target or not target.startswith(REPOSITORY_ROOTS):
                continue
            if not (project / target).exists():
                broken.append(f"{relative} -> {target}")
    if not broken:
        return []
    return [
        "changed documentation references paths that do not resolve: "
        + _summarize(broken)
        + ". Fix the reference or restore the target; a reference that resolved "
        "when it was written is how a reader learns the document moved."
    ]


def _frontmatter_failures(project: Path, changed: list[str]) -> list[str]:
    missing: list[str] = []
    for relative in changed:
        text = _read(project / relative)
        if text is None:
            continue
        match = FRONTMATTER.match(text)
        if match is None:
            missing.append(f"{relative} (no frontmatter block)")
            continue
        keys = {
            line.split(":", 1)[0].strip()
            for line in match.group(1).splitlines()
            if ":" in line
        }
        absent = [key for key in REQUIRED_FRONTMATTER_KEYS if key not in keys]
        if absent:
            missing.append(f"{relative} (missing {', '.join(absent)})")
    if not missing:
        return []
    return [
        "changed documentation is missing required frontmatter: "
        + _summarize(missing)
        + f". Every card carries {', '.join(REQUIRED_FRONTMATTER_KEYS)}."
    ]


def _orphaned_reference_failures(project: Path, removed: list[str]) -> list[str]:
    """Find documents still pointing at something this change deleted or moved.

    This is the rule the other two cannot express: the evidence is not in the
    changed file, it is in every file that was not changed.
    """

    targets = [path for path in removed if path.endswith(".md")]
    if not targets:
        return []
    orphaned: list[str] = []
    for source in _markdown_files(project):
        relative = source.relative_to(project).as_posix()
        if relative in targets:
            continue
        text = _read(source)
        if text is None:
            continue
        for target in targets:
            if target in text:
                orphaned.append(f"{relative} still references {target}")
    if not orphaned:
        return []
    return [
        "this change removed or moved documentation that other documents still "
        "reference: " + _summarize(orphaned)
        + ". Update each reference, or the reader follows it to nothing."
    ]


def _markdown_files(project: Path) -> list[Path]:
    files: list[Path] = []
    for root in REPOSITORY_ROOTS:
        directory = project / root.rstrip("/")
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.md")))
    return files


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _summarize(items: list[str]) -> str:
    shown = "; ".join(items[:MAX_REPORTED])
    if len(items) > MAX_REPORTED:
        shown += f"; ... (+{len(items) - MAX_REPORTED} more)"
    return shown
