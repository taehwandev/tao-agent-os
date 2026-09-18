"""Check the references in changed Markdown, instead of asking about them.

The docs route carried a `link/path check` gate whose evidence was the agent
writing that the links resolved. Nothing could refuse that sentence, and the one
failure it existed to catch -- a document moves and the references to it are left
behind -- is invisible from the moved file alone. These checks read the diff.

The link rules are repository-neutral. The frontmatter rule is not: it describes
Tao's own card convention and the review adapter enables it only for a Tao source
checkout. Target repositories keep their own documentation conventions.
"""

from __future__ import annotations

import re
from pathlib import Path


# `[text](path "title")` is valid Markdown, and a pattern that stops at the
# first whitespace does not merely mis-parse it, it ignores the link entirely --
# so a broken target wearing a title passed silently.
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+[\"'(][^)]*)?\)")
BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|json|py))`")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FRONTMATTER_ENTRY = re.compile(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$")
REQUIRED_FRONTMATTER_KEYS = ("keyflow_id", "status", "type")
# Measured across the 394 tracked documents rather than invented, so the rule
# describes the convention in force instead of one a reader would have to adopt.
FRONTMATTER_VALUES = {
    "status": frozenset({"review", "stable", "draft"}),
    "type": frozenset(
        {"ai-generated", "human-reviewed-needed", "human-reviewed", "planning"}
    ),
}
KEYFLOW_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
# A bundled external skill is vendored, not owned: it carries its own header
# (`name`/`description` rather than Tao's keys) and its example paths describe
# whatever repository the skill is pointed at. Both rules skip it, because both
# would otherwise be wrong about a tree this repository does not maintain.
VENDORED_TREES = (".tao/skills/",)
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
    tracked_markdown: list[str] | None = None,
    *,
    require_tao_frontmatter: bool = True,
) -> list[str]:
    """Return one failure line per broken reference rule, or an empty list.

    ``changed_markdown`` and ``removed_paths`` are repository-relative and come
    from the diff the review hook already computed. ``removed_paths`` must
    include a rename's previous path: a rename is a removal as far as every
    document that still points at the old name is concerned.

    ``tracked_markdown`` bounds the search for references to a removed document.
    The hook passes what git tracks, because generated output is regenerated and
    a stale reference inside it is not a break anyone should fix. Falling back to
    a filesystem walk keeps the function usable without the hook, at the cost of
    reading artifacts the repository does not track.

    ``require_tao_frontmatter`` is true only when the reviewed checkout owns
    Tao's card convention. Link and removal checks remain active everywhere.
    """

    failures: list[str] = []
    failures.extend(_broken_link_failures(project, changed_markdown))
    if require_tao_frontmatter:
        failures.extend(_frontmatter_failures(project, changed_markdown))
    failures.extend(
        _orphaned_reference_failures(project, removed_paths, tracked_markdown)
    )
    return failures


def _broken_link_failures(project: Path, changed: list[str]) -> list[str]:
    broken: list[str] = []
    unreadable: list[str] = []
    for relative in changed:
        if relative.startswith(VENDORED_TREES):
            continue
        path = project / relative
        text, error = _read(path)
        if error is not None:
            unreadable.append(f"{relative} ({error})")
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
    failures = _unreadable_failure(unreadable)
    if broken:
        failures.append(
            "changed documentation references paths that do not resolve: "
            + _summarize(broken)
            + ". Fix the reference or restore the target; a reference that "
            "resolved when it was written is how a reader learns it moved."
        )
    return failures


def _frontmatter_failures(project: Path, changed: list[str]) -> list[str]:
    missing: list[str] = []
    unreadable: list[str] = []
    for relative in changed:
        if relative.startswith(VENDORED_TREES):
            continue
        text, error = _read(project / relative)
        if error is not None:
            unreadable.append(f"{relative} ({error})")
            continue
        match = FRONTMATTER.match(text)
        if match is None:
            missing.append(f"{relative} (no frontmatter block)")
            continue
        # A key with nothing after the colon satisfied "the key is present" and
        # told the reader nothing, so the value has to be there too.
        values = {}
        for line in match.group(1).splitlines():
            entry = FRONTMATTER_ENTRY.match(line)
            if entry:
                values[entry.group(1)] = entry.group(2).strip().strip("\"'")
        absent = [key for key in REQUIRED_FRONTMATTER_KEYS if not values.get(key)]
        if absent:
            missing.append(f"{relative} (missing or empty {', '.join(absent)})")
            continue
        # A present value that means nothing is the same defect as an absent
        # one: it satisfies the check and tells the reader no more.
        for key, allowed in FRONTMATTER_VALUES.items():
            if values[key] not in allowed:
                missing.append(
                    f"{relative} ({key}: {values[key]!r} is not one of "
                    f"{', '.join(sorted(allowed))})"
                )
        if not KEYFLOW_ID.match(values["keyflow_id"]):
            missing.append(
                f"{relative} (keyflow_id: {values['keyflow_id']!r} is not a "
                "lowercase identifier)"
            )
    failures = _unreadable_failure(unreadable)
    if missing:
        failures.append(
            "changed documentation is missing required frontmatter: "
            + _summarize(missing)
            + f". Every card carries {', '.join(REQUIRED_FRONTMATTER_KEYS)}."
        )
    return failures


def _orphaned_reference_failures(
    project: Path, removed: list[str], tracked: list[str] | None = None
) -> list[str]:
    """Find documents still pointing at something this change deleted or moved.

    This is the rule the other two cannot express: the evidence is not in the
    changed file, it is in every file that was not changed. It therefore scans
    the whole repository rather than a list of directories -- a reference from a
    top-level README is the same broken reference as one from a skill card.
    """

    targets = [path for path in removed if path.endswith(".md")]
    if not targets:
        return []
    orphaned: list[str] = []
    unreadable: list[str] = []
    sources = (
        [project / item for item in tracked]
        if tracked is not None
        else _markdown_files(project)
    )
    for source in sources:
        relative = source.relative_to(project).as_posix()
        if relative in targets:
            continue
        text, error = _read(source)
        if error is not None:
            unreadable.append(f"{relative} ({error})")
            continue
        for target in targets:
            if _references(text, source, project, target):
                orphaned.append(f"{relative} still references {target}")
    failures = _unreadable_failure(unreadable)
    if orphaned:
        failures.append(
            "this change removed or moved documentation that other documents "
            "still reference: " + _summarize(orphaned)
            + ". Update each reference, or the reader follows it to nothing."
        )
    return failures


def _references(text: str, source: Path, project: Path, target: str) -> bool:
    """Whether this document points at ``target``, by any spelling it can use.

    A repository-relative mention is a substring, but a relative link such as
    `../a/old.md` shares no substring with `common/a/old.md` at all, so each
    link is resolved from the referring file before it is compared.
    """

    if target in text:
        return True
    absolute = (project / target).resolve()
    for link in MARKDOWN_LINK.findall(text):
        if link.startswith(EXTERNAL_LINK):
            continue
        if (source.parent / link.split("#", 1)[0]).resolve() == absolute:
            return True
    return False


def _markdown_files(project: Path) -> list[Path]:
    """Fallback for a caller with no tracked-file list; approximates it."""

    skip = {
        ".git", ".tao", "node_modules", "__pycache__", ".venv", "venv",
        "graphify-out", "local",
    }
    files: list[Path] = []
    for path in sorted(project.rglob("*.md")):
        if any(part in skip for part in path.relative_to(project).parts):
            continue
        files.append(path)
    return files


def _read(path: Path) -> tuple[str, str | None]:
    """Return the text, or an empty string and the reason it could not be read.

    An unreadable file is reported rather than skipped. This runs as an
    automatic check, and a check that silently passes what it could not inspect
    is indistinguishable from one that found nothing wrong.
    """

    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as error:
        return "", error.strerror or error.__class__.__name__


def _unreadable_failure(unreadable: list[str]) -> list[str]:
    if not unreadable:
        return []
    return [
        "documentation could not be read, so its references are unchecked: "
        + _summarize(unreadable)
        + ". Restore access or remove the file; an unreadable document is not a "
        "passing one."
    ]


def _summarize(items: list[str]) -> str:
    shown = "; ".join(items[:MAX_REPORTED])
    if len(items) > MAX_REPORTED:
        shown += f"; ... (+{len(items) - MAX_REPORTED} more)"
    return shown
