"""Admit a fast-forward of a finished linked worktree into its repository.

Owner: the one integration a finished run admits without a new lifecycle --
`git [-C <repo>] merge --ff-only <ref>` of exactly a registered worktree's
clean, attested HEAD -- and the run-evidence lookups every finished admission
receives from the gate.
Allowed imports: the standard library, claude_bash_git, and
agent_publication_admission (lazily).
Forbidden imports: claude_pretool_gate; run evidence arrives through
``FinishedRuns`` so that the gate's own lookups, and patches of them, decide.
Callers/tests: claude_pretool_finished_admission, claude_pretool_gate;
tests/test_finished_worktree_integration.py.
Verification: that module.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, NamedTuple

from claude_bash_git import git_subcommand, names_unsafe_git_option

# The only options a fast-forward integration of an attested worktree may
# carry. `--ff-only` is what makes it a reference move rather than a merge;
# the rest only quieten it. Anything else -- `--no-ff`, `-m`, `--squash`, a
# strategy option -- builds a commit nobody reviewed, so it is not this shape.
FAST_FORWARD_MERGE_FLAGS = frozenset({"--ff-only", "-q", "--quiet", "--no-edit"})


class FinishedRuns(NamedTuple):
    """The gate's run-evidence lookups, passed in rather than imported.

    ``evidence`` finds this session's latest completed run in a checkout,
    ``is_fresh`` says whether that finish is recent enough to act on, and
    ``protected_branches`` names the checkout's protected branches (None when
    it declares none).
    """

    evidence: "Callable[[Path, str], Path | None]"
    is_fresh: "Callable[[Path | None], bool]"
    protected_branches: "Callable[[Path], frozenset[str] | None]"


def _git_read(root: Path, arguments: list[str]) -> "tuple[int, str] | None":
    """One short read of a repository, or None when it cannot be answered.

    Every caller below treats None and a non-zero status the same way -- the
    integration is not admitted -- so a missing git, a timeout and an
    unreadable administrative directory all fail closed without a branch each.
    """

    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.returncode, result.stdout


def _fast_forward_merge_target(tokens: list[str], base: Path) -> "Path | None":
    """The checkout `git [-C <path>] merge ...` acts on, or None if unreadable.

    Only `-C` is stepped over. `--git-dir`, `--work-tree`, `-c` and
    `--config-env` also choose or reconfigure the repository, and one of them
    can put a program where this admission expects a reference move, so a
    command carrying any of them is not the shape being admitted.
    """

    target = base
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return target if token == "merge" else None
        if token == "-C" and index + 1 < len(tokens):
            raw = Path(tokens[index + 1]).expanduser()
            target = raw if raw.is_absolute() else base / raw
            index += 2
            continue
        return None
    return None


def _names_exact_fast_forward(arguments: list[str]) -> str:
    """The single ref of an exact `--ff-only` merge, or "" for any other shape.

    `--no-ff`, a plain merge, a second positional and an option that runs a
    program all mean the command can bring in bytes no finish attested, so
    each of them leaves the ordinary refusal in place.
    """

    if any(names_unsafe_git_option(argument) for argument in arguments):
        return ""
    flags = [argument for argument in arguments if argument.startswith("-")]
    words = [argument for argument in arguments if not argument.startswith("-")]
    if "--ff-only" not in flags or set(flags) - FAST_FORWARD_MERGE_FLAGS:
        return ""
    if len(words) != 1 or not words[0] or words[0].split() != [words[0]]:
        return ""
    return words[0]


def _registered_worktrees(target: Path) -> list[Path]:
    """The repository's other checkouts, as git itself registers them.

    Asking the target rather than searching the filesystem is what keeps this
    to one repository: a directory that merely looks like a worktree, or one
    belonging to some other project, is never in this list.
    """

    read = _git_read(target, ["worktree", "list", "--porcelain"])
    if read is None or read[0] != 0:
        return []
    paths: list[Path] = []
    for line in read[1].splitlines():
        if not line.startswith("worktree "):
            continue
        try:
            candidate = Path(line[len("worktree ") :]).resolve()
        except OSError:
            continue
        if candidate != target and candidate not in paths:
            paths.append(candidate)
    return paths


def _holds_exactly_the_finished_commit(
    worktree: Path, session_id: str, sha: str, runs: FinishedRuns
) -> bool:
    """Whether this worktree's finish attested exactly the commit being merged.

    The receipt binds the finished bytes; HEAD and a clean status bind the
    commit to those same bytes. Without both, a worktree edited or advanced
    after its finish would hand that receipt to a commit nobody reviewed.
    """

    evidence = runs.evidence(worktree, session_id)
    if not runs.is_fresh(evidence):
        return False
    from agent_publication_admission import PublicationAdmission

    if not PublicationAdmission.allows(worktree, evidence, "git_write"):
        return False
    head = _git_read(worktree, ["rev-parse", "HEAD"])
    if head is None or head[0] != 0 or head[1].strip() != sha:
        return False
    status = _git_read(
        worktree, ["status", "--porcelain", "--untracked-files=normal"]
    )
    return status is not None and status[0] == 0 and not status[1].strip()


def integrates_finished_worktree(
    root: Path,
    session_id: str,
    tokens: list[str],
    runs: FinishedRuns,
    cwd: Path | None = None,
) -> bool:
    """Admit a fast-forward of a finished linked worktree into its repository.

    A goal loop works in `<repo>/.tao/worktrees/<slice>`, runs the whole
    lifecycle there, and then brings the commit home with
    `git -C <repo> merge --ff-only <sha>`. That merge had no admission of its
    own: publication covers `add`, `commit`, `push` and `tag`, and it is
    looked up against the checkout the command names, which never held the
    run. So every iteration opened a second lifecycle in the main checkout to
    fast-forward bytes the first had already tested, reviewed and attested --
    eight tool calls of ceremony for a reference move.

    The admission is the finish that already happened, never a new authority.
    A fast-forward writes no commit and no bytes: the target's HEAD must
    already be an ancestor of the commit, the commit must be exactly some
    registered worktree's HEAD, and that worktree must be clean and unchanged
    since its receipt. Anything else -- a plain `merge`, `--no-ff`, a rebase,
    a second ref, a dirty or advanced worktree, a diverged target, a
    read-route finish -- fails closed and keeps the ordinary refusal.
    """

    if not session_id:
        return False
    subcommand, arguments = git_subcommand(tokens)
    if subcommand != "merge":
        return False
    ref = _names_exact_fast_forward(arguments)
    if not ref:
        return False
    target = _fast_forward_merge_target(tokens, cwd or root)
    if target is None:
        return False
    try:
        target = target.resolve()
    except OSError:
        return False
    resolved = _git_read(target, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if resolved is None or resolved[0] != 0:
        return False
    sha = resolved[1].strip()
    if not sha:
        return False
    # The ancestry is the whole reason this is admissible: a diverged target
    # makes the same command an ordinary merge wearing the flag, which would
    # integrate bytes no finish attested -- and which git refuses anyway.
    ancestry = _git_read(target, ["merge-base", "--is-ancestor", "HEAD", sha])
    if ancestry is None or ancestry[0] != 0:
        return False
    return any(
        _holds_exactly_the_finished_commit(worktree, session_id, sha, runs)
        for worktree in _registered_worktrees(target)
    )
