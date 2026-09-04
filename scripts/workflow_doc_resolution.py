"""Resolve thin skill entrypoints to the documents that hold the actual rules.

Most `<skill>/SKILL.md` files in this repo are generated pointers: once
frontmatter, the H1 title, and the skill's own path are normalised away they are
byte-identical to one another and say only "the detailed guidance is in
`references/current-guidance.md`".  Routing those as `required_docs` spends the
agent's startup budget on text that carries no decision content, while the rules
the finish gates actually enforce sit one hop away in the reference.

This module answers one question per document: *is this entrypoint a pointer, or
does it carry guidance of its own?*  Pointers are replaced by their reference.
Entrypoints with real content are kept and the reference is added alongside.

The pointer test is deliberately corpus-derived rather than hard-coded.  The
shared template is generated, so any wording change would invalidate a literal
copy embedded here; instead we take the *modal* normalised body across the skill
corpus and treat exact matches as pointers.  If the template is ever
regenerated, all pointers move together and the modal body follows them.  If the
corpus genuinely diversifies, the modal group shrinks and fewer documents are
classified as pointers -- which keeps entrypoints in the route.  That is the
safe direction to fail: a misclassified pointer costs about a kilobyte, while a
misclassified substantive entrypoint would silently drop guidance.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from support.project_tree import iter_project_files
from workflow_skill_paths import guidance_reference_path


_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)
_H1 = re.compile(r"^#\s+.*$", re.M)
_WHITESPACE = re.compile(r"\s+")

# A modal group smaller than this means the corpus no longer has one dominant
# generated template.  Rather than guess, we stop classifying anything as a
# pointer and let every entrypoint stay in the route.
_MIN_TEMPLATE_GROUP = 20


def _normalised_body(root: Path, path: str) -> str:
    """Strip the parts of an entrypoint that vary purely by which skill it is."""

    try:
        text = (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    text = _FRONTMATTER.sub("", text)
    text = _H1.sub("", text, count=1)
    # The template names its own path in the "Use when routed to ..." line.
    text = text.replace(path, "@SKILL_PATH@")
    return _WHITESPACE.sub(" ", text).strip().lower()


def _digest(root: Path, path: str) -> str:
    return hashlib.sha256(_normalised_body(root, path).encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def _pointer_digest(root_key: str) -> str:
    """Return the digest of the modal entrypoint body, or "" when there is none."""

    root = Path(root_key)
    groups: dict[str, int] = defaultdict(int)
    for skill in iter_project_files(root, "SKILL.md"):
        relative = skill.relative_to(root)
        if len(relative.parts) < 3 or relative.parts[-3] != "skills":
            continue
        rel = relative.as_posix()
        body = _normalised_body(root, rel)
        if body:
            groups[hashlib.sha256(body.encode("utf-8")).hexdigest()] += 1
    if not groups:
        return ""
    digest, count = max(groups.items(), key=lambda item: item[1])
    return digest if count >= _MIN_TEMPLATE_GROUP else ""


def is_pointer_entrypoint(root: Path, path: str) -> bool:
    """True when `path` is a generated entrypoint with no guidance of its own."""

    if not path.endswith("/SKILL.md"):
        return False
    pointer = _pointer_digest(str(root))
    if not pointer:
        return False
    return _digest(root, path) == pointer


def resolve_guidance_docs(root: Path, docs: list[str]) -> list[str]:
    """Replace pointer entrypoints with the reference that holds the real rules.

    * pointer entrypoint with a reference -> the reference replaces it
    * substantive entrypoint with a reference -> both are kept, entrypoint first
    * entrypoint with no reference on disk -> the entrypoint is kept unchanged
    * anything that is not a `SKILL.md` -> passed through untouched
    """

    resolved: list[str] = []
    for doc in docs:
        if not doc.endswith("/SKILL.md"):
            resolved.append(doc)
            continue
        reference = guidance_reference_path(doc)
        if reference == doc or not (root / reference).exists():
            # No detailed reference exists; the entrypoint is all there is.
            resolved.append(doc)
            continue
        if is_pointer_entrypoint(root, doc):
            resolved.append(reference)
            continue
        # The entrypoint carries content the reference does not repeat.
        resolved.append(doc)
        resolved.append(reference)
    return resolved


def doc_size(root: Path, path: str) -> int:
    try:
        return (root / path).stat().st_size
    except OSError:
        return 0
