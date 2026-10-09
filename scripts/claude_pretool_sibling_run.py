"""Find this session's open run in another checkout of the same repository.

Owner: the sentence an entry denial adds when the write was aimed at the wrong
checkout -- the main checkout while the run is open in a linked worktree, or
the reverse.
Allowed imports: the standard library.
Forbidden imports: claude_pretool_gate and run evidence; the gate hands in how
it finds a session's evidence and a checkout's main checkout.
Callers/tests: claude_pretool_gate.deny_reason;
tests/test_claude_pretool_sibling_run.py.
Verification: that module and the full gate suite.

In a week of Claude transcripts, most entry denials that arrived while a run
was open came from this mix-up: the run lived in `.tao/worktrees/<task>` and
the edit named the same file under the main checkout. The denial only said to
run `start`, so the agent opened a second run in the wrong checkout instead of
moving the edit. The verdict stays; the reason now names where the run is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable


def linked_worktrees(main: Path) -> list[Path]:
    """The checkouts git registered for `main`, read from `.git/worktrees`."""

    found: list[Path] = []
    admin = main / ".git" / "worktrees"
    try:
        entries = sorted(admin.iterdir())
    except OSError:
        return found
    for entry in entries:
        try:
            gitdir = (entry / "gitdir").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if gitdir.endswith("/.git"):
            found.append(Path(gitdir[: -len("/.git")]))
    return found


def sibling_open_run(
    root: Path,
    session_id: str,
    recorded: Iterable[Path],
    *,
    main_checkout_for: Callable[[Path], "Path | None"],
    session_evidence: Callable[[Path, str], "Path | None"],
) -> Path | None:
    """The other checkout of `root`'s repository where this session has a run."""

    if not session_id:
        return None
    main = _resolved(main_checkout_for(root) or root)
    if main is None:
        return None
    candidates: list[Path] = []
    for candidate in [main, *linked_worktrees(main), *recorded]:
        if candidate not in candidates:
            candidates.append(candidate)
    root_resolved = _resolved(root)
    for candidate in candidates:
        resolved = _resolved(candidate)
        if resolved is None or resolved == root_resolved or not resolved.is_dir():
            continue
        if _resolved(main_checkout_for(resolved) or resolved) != main:
            continue
        if session_evidence(resolved, session_id) is not None:
            return resolved
    return None


def sibling_run_sentence(root: Path, sibling: Path) -> str:
    return (
        f" This session's open run is in {sibling}, another checkout of the same "
        f"repository as {root}. Make this change there, at the same path relative "
        "to that checkout, rather than starting a second run here."
    )


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None
