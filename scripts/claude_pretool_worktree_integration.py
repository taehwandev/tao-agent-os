"""Admit a fast-forward of a finished linked worktree into its repository.

Owner: the one integration a finished run admits without a new lifecycle --
`git [-C <repo>] merge --ff-only <ref>` of exactly a registered worktree's
clean, attested HEAD -- the plain `git push` of that same commit from another
checkout of the repository, and the run-evidence lookups every finished
admission receives from the gate.
Allowed imports: the standard library, claude_bash_git, and
agent_publication_admission and agent_repository_checkouts (lazily).
Forbidden imports: claude_pretool_gate; run evidence arrives through
``FinishedRuns`` so that the gate's own lookups, and patches of them, decide.
Callers/tests: claude_pretool_finished_admission, claude_pretool_gate;
tests/test_finished_worktree_integration.py.
Verification: that module.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple

from claude_bash_git import git_subcommand, names_unsafe_git_option

# The only options a fast-forward integration of an attested worktree may
# carry. `--ff-only` is what makes it a reference move rather than a merge;
# the rest only quieten it. Anything else -- `--no-ff`, `-m`, `--squash`, a
# strategy option -- builds a commit nobody reviewed, so it is not this shape.
FAST_FORWARD_MERGE_FLAGS = frozenset({"--ff-only", "-q", "--quiet", "--no-edit"})
# Stashes the target's uncommitted tracked changes around the move and puts
# them back. Admitted only when every one of them is already in the commit
# (see `_leftovers_already_in`), so the move still brings in nothing unattested
# and the put-back leaves the target clean instead of touching other work.
AUTOSTASH_FLAG = "--autostash"


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
    if "--ff-only" not in flags or set(flags) - FAST_FORWARD_MERGE_FLAGS - {AUTOSTASH_FLAG}:
        return ""
    if len(words) != 1 or not words[0] or words[0].split() != [words[0]]:
        return ""
    return words[0]


def _git_bytes(root: Path, arguments: list[str]) -> "bytes | None":
    """One short binary read of a repository, or None when it fails."""

    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _contains_leftover(target: Path, base: bytes, commit: bytes, leftover: bytes) -> bool:
    """Whether merging the leftover edit of `base` into `commit` changes nothing."""

    if leftover == commit:
        return True
    with tempfile.TemporaryDirectory() as folder:
        files = []
        for name, content in (("commit", commit), ("base", base), ("leftover", leftover)):
            path = Path(folder) / name
            path.write_bytes(content)
            files.append(str(path))
        merged = _git_bytes(target, ["merge-file", "-p", *files])
    return merged == commit


def _leftovers_already_in(target: Path, sha: str) -> bool:
    """Whether every uncommitted tracked change in the target is already in `sha`.

    A run that began in the main checkout before moving to its worktree can
    leave its own edits behind there; git then refuses the fast-forward, and
    every way of clearing them is a write the main checkout's guard refuses.
    `--autostash` clears them only for the move. When each leftover file merges
    into the commit's version without changing it, the put-back is a no-op and
    the target ends clean at the commit; anything else -- a deleted file, a
    path the commit does not hold, an edit the commit lacks -- may be someone
    else's work, so the ordinary refusal stays.
    """

    listed = _git_bytes(target, ["diff", "--name-only", "-z", "HEAD"])
    if listed is None:
        return False
    for raw in filter(None, listed.split(b"\0")):
        path = raw.decode("utf-8", "surrogateescape")
        base = _git_bytes(target, ["show", f"HEAD:{path}"])
        commit = _git_bytes(target, ["show", f"{sha}:{path}"])
        try:
            leftover = (target / path).read_bytes()
        except OSError:
            return False
        if base is None or commit is None or not _contains_leftover(target, base, commit, leftover):
            return False
    return True


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
    worktree: Path, session_id: str, sha: str, runs: FinishedRuns, effect: str = "git_write"
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

    if not PublicationAdmission.allows(worktree, evidence, effect):
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
    read-route finish, `--autostash` over a change the commit lacks -- fails
    closed and keeps the ordinary refusal.
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
    if AUTOSTASH_FLAG in arguments and not _leftovers_already_in(target, sha):
        return False
    return any(
        _holds_exactly_the_finished_commit(worktree, session_id, sha, runs)
        for worktree in _registered_worktrees(target)
    )


# The only options a cross-checkout push of an attested commit may carry. Each
# leaves the push one branch update of one named commit; `--force`, `--tags`,
# `--all`, `--mirror`, `--delete` and anything else is not this shape.
CROSS_CHECKOUT_PUSH_FLAGS = frozenset(
    {"-q", "--quiet", "-v", "--verbose", "-u", "--set-upstream", "--porcelain", "--no-progress"}
)


def _pushed_source(arguments: list[str]) -> str:
    """The one local revision a plain `git push` publishes, or "" when unsure.

    No positional, or only a remote, pushes the current branch, read as HEAD.
    A remote and one refspec push its source side. A forced (`+`), pattern,
    deleting or multi-ref refspec, and any option outside the set above, can
    publish something other than one commit, so it is not this shape.
    """

    flags = [argument for argument in arguments if argument.startswith("-")]
    words = [argument for argument in arguments if not argument.startswith("-")]
    if set(flags) - CROSS_CHECKOUT_PUSH_FLAGS or len(words) > 2:
        return ""
    if len(words) < 2:
        return "HEAD"
    source = words[1].split(":", 1)[0]
    if not source or source.startswith("+") or any(mark in source for mark in "*^~@: "):
        return ""
    return source


def pushes_finished_checkout_commit(
    root: Path,
    session_id: str,
    tokens: list[str],
    runs: FinishedRuns,
    cwd: Path | None = None,
) -> "tuple[Path, str] | None":
    """The other checkout and run whose finish attested exactly the pushed commit.

    A session finishes a run in a linked worktree with publication authority,
    fast-forwards main to that commit, and pushes from the main checkout. The
    pushing checkout holds no finished run, so the push needed a second
    lifecycle there for a commit already reviewed and attested. This admits
    it only when the commit being pushed is exactly a clean other checkout's
    HEAD, and that checkout's latest finished run of this session admits
    `external_write` on unchanged bytes -- the same receipt check the
    same-checkout path uses. Any other push shape returns None.
    """

    if not session_id or tokens[:2] != ["git", "push"]:
        return None
    source = _pushed_source(tokens[2:])
    if not source:
        return None
    pushing = Path(cwd or root)
    top = _git_read(pushing, ["rev-parse", "--show-toplevel"])
    resolved = _git_read(pushing, ["rev-parse", "--verify", "--end-of-options", f"{source}^{{commit}}"])
    if top is None or top[0] != 0 or resolved is None or resolved[0] != 0:
        return None
    sha = resolved[1].strip()
    from agent_repository_checkouts import checkouts_with_run_state

    for checkout in checkouts_with_run_state(Path(top[1].strip())):
        if _holds_exactly_the_finished_commit(checkout, session_id, sha, runs, "external_write"):
            evidence = runs.evidence(checkout, session_id)
            return checkout, evidence.parent.name if evidence is not None else ""
    return None
