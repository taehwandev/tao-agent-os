"""What a Git command may do in the protected checkout itself.

Owner: the protected-checkout verdict -- refuse authoring there, ask about
committing or discarding, approve routine reference maintenance, defer what
belongs to the runtime's own permission flow -- and the deletion forms that
flow keeps.
Allowed imports: the standard library, claude_bash_git and
claude_pretool_git_hazards.
Forbidden imports: claude_pretool_gate and any run-evidence or policy reader;
the caller supplies the protected branch names.
Callers/tests: claude_pretool_gate (which re-exports these names);
tests/test_safe_ref_cleanup.py, test_claude_pretool_gate.py.
Verification: those modules.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_git import git_subcommand, names_unsafe_git_option
from claude_pretool_git_hazards import shared_repository_hazard


# Writing new content into the working tree is the one thing the protected
# checkout is protected from. These author it; everything else Git does there
# moves or removes what already exists.
AUTHORING_GIT_SUBCOMMANDS = frozenset(
    {"add", "am", "apply", "cherry-pick", "commit", "mv", "rebase", "revert", "rm"}
)


# In the protected checkout these either write a new commit or throw away
# uncommitted work there. Neither is authoring in the sense the refusal covers,
# but both are a decision worth one question. `switch` is absent on purpose:
# git refuses to change branches over uncommitted changes, so it cannot lose
# them, and it is how you move around a checkout at all. Two members of this
# set have a spelling that only unstages; `unstages_only` names it, because
# the question is about losing work and unstaging loses none.
COMMITTING_OR_DISCARDING_SUBCOMMANDS = frozenset(
    {"checkout", "clean", "merge", "pull", "reset", "restore", "stash"}
)
# Reference maintenance: moving or removing things that already exist, without
# touching the working tree. These are what a task's last step is made of, so
# they are approved outright -- and the list is positive, so a subcommand
# nobody has read still asks.
ROUTINE_PROTECTED_SUBCOMMANDS = frozenset(
    {"branch", "config", "fetch", "gc", "push", "remote", "switch", "tag", "worktree"}
)


def unstages_only(subcommand: str, arguments: list[str]) -> bool:
    """True for the two spellings of "take these paths back out of the index".

    Unstaging is the one member of `COMMITTING_OR_DISCARDING_SUBCOMMANDS` that
    cannot lose anything: the files keep their contents on disk, no ref moves,
    and in the protected checkout it cannot even lead anywhere, because `git
    commit` is refused there. Reading it as a discard put a prompt in front of
    tidying a single stray index entry.

    Only the long option spellings are read. `-S` is `--staged`, but a short
    flag that this function does not recognise falls through to the question,
    which is the direction a misreading should fail in.
    """

    flags = {argument.split("=", 1)[0] for argument in arguments}
    if subcommand == "reset":
        # The pathspec is what makes a reset index-only. Given one, Git refuses
        # `--hard` and leaves HEAD where it is whatever commit is named, so the
        # separator -- not the absence of a commit -- is the thing to look for.
        # Requiring it explicitly also keeps a branch name from being read as a
        # path.
        if "--" not in arguments or arguments[-1] == "--":
            return False
        return not flags & {"--hard", "--merge", "--keep"}
    if subcommand == "restore":
        return "--staged" in flags and "--worktree" not in flags
    return False


def is_git_deletion(tokens: list[str]) -> bool:
    """Recognize deletion forms only; native permissions still decide access."""
    if not tokens or Path(tokens[0]).name != "git":
        return False
    if any(arg.split("=", 1)[0] in {"--git-dir", "--work-tree", "--config-env", "-c"} for arg in tokens[1:]):
        return False  # Repository/configuration overrides need their own review.
    subcommand, arguments = git_subcommand(tokens)
    if any(names_unsafe_git_option(arg) for arg in arguments):
        return False
    flags = {arg.split("=", 1)[0] for arg in arguments if arg.startswith("--")}
    short = {c for arg in arguments if arg.startswith("-") and not arg.startswith("--") for c in arg[1:]}
    words = [arg for arg in arguments if not arg.startswith("-")]
    first = words[0] if words else ""
    if subcommand in {"branch", "tag"}:
        return bool(short & ({"d", "D"} if subcommand == "branch" else {"d"}) or "--delete" in flags)
    if subcommand == "push":
        return "d" in short or "--delete" in flags or any(word.startswith(":") for word in words[1:])
    if subcommand in {"remote", "worktree"}:
        return first in ({"remove", "rm"} if subcommand == "remote" else {"remove", "prune"})
    if subcommand == "stash":
        return first in {"drop", "clear"}
    if subcommand in {"update-ref", "replace"}:
        return "d" in short or "--delete" in flags
    return subcommand in {"clean", "prune"} or (subcommand == "reflog" and first in {"delete", "expire"}) or (subcommand == "gc" and "--prune" in flags)


def protected_checkout_verdict(
    tokens: list[str], protected: frozenset[str] | None = None
) -> str:
    """`allow`, `ask`, or `""` for a Git command aimed at the protected checkout.

    The policy is that new work is authored in a linked worktree and the
    original is left alone, so authoring is what the refusal is for. It was
    written the other way round -- a short list of permitted commands, refusing
    everything else -- and the list was never going to be complete. First it
    missed `merge` and `pull`, so work done in a worktree had no way home. Then
    it missed `branch -D`, so deleting two merged branches meant creating a
    throwaway worktree to delete them from, which is ceremony standing in for a
    decision the operator had already made.

    Naming what is refused instead makes the boundary answer for cases nobody
    listed. Authoring is refused outright, because the remedy is deterministic:
    do it in a worktree.

    Everything else was then put to the operator as a decision, on the belief
    that Claude's prompt carries "don't ask again" so a routine one would cost
    a single answer. It does not: a hook's `ask` offers yes or no, every time.
    So tidying up a merged branch here asked on the last step of every task,
    forever -- which is the machine that only takes Enter, rebuilt one tier
    down.

    The asking tier is therefore the same one a worktree uses: a shared-state
    hazard, plus the commands that create a commit or throw away uncommitted
    work in this checkout. Ordinary reference maintenance -- deleting a merged
    branch, removing a tag, tidying a remote, pruning a worktree -- is approved
    outright, exactly as it is inside a worktree.

    Returns `defer` for what belongs to Claude's own permission flow rather
    than to this gate, `""` for a refusal, and covers anything that is not Git
    at all.
    """

    if not tokens:
        return ""
    if Path(tokens[0]).name == "gh":
        # `gh` talks to GitHub and writes nothing into this working tree, so it
        # is not this gate's business either way -- the same answer it gets
        # inside a worktree.
        return "defer"
    if Path(tokens[0]).name != "git":
        # A test runner, a build, a package manager, the project's own
        # maintenance tooling: a question rather than a refusal.
        #
        # Refusing them read as "authoring", and for a build or a test that is
        # fair -- the remedy is deterministic, do it in a worktree. But the same
        # wall stood in front of commands with no such remedy. `vibeguard
        # update` writes per-checkout state a worktree run cannot refresh here,
        # so there was no route at all, only a hand-run command, and seven
        # ordinary runners sat behind it too.
        #
        # And a question this gate does not answer, because Claude already
        # answers it. A hook's `ask` overrides the permission rules, so asking
        # here re-asked about commands the operator had already allowed once and
        # for all: `vibeguard`, `npm test` and `pytest` all had standing allow
        # rules and started prompting every time. Turning a dead end into a
        # prompt is only an improvement when there was no prompt before.
        #
        # Deferring keeps both halves. A command with a standing rule runs
        # silently again; one without still reaches the operator, through the
        # layer whose answers persist. This gate keeps only what it alone
        # knows -- authoring here, and the shared refs below.
        #
        # The caller keeps two refusals in front of this: a command whose text
        # cannot be read stays denied, because nothing downstream can describe
        # it either, and an Edit or Write naming a path here never reaches this
        # function at all.
        return "defer"
    subcommand, arguments = git_subcommand(tokens)
    if subcommand is None:
        # An option this gate cannot read hides which subcommand runs. That is
        # the dangerous case, and a question is the safe answer to it -- the
        # same fail-closed reading the hazard check uses.
        return "ask"
    if not subcommand or subcommand in AUTHORING_GIT_SUBCOMMANDS:
        return ""
    if any(names_unsafe_git_option(argument) for argument in arguments):
        # A subcommand that only reads still writes when handed `--output`, and
        # runs a program when handed `--ext-diff` or `--textconv`. Naming the
        # refusal by subcommand alone missed that: `git diff --output=<a path
        # in the protected checkout>` authors a file there under a verb that
        # looks like inspection.
        return ""
    flags = {argument.split("=", 1)[0] for argument in arguments}
    if subcommand in {"merge", "pull"} and "--ff-only" in flags:
        return "allow"
    if subcommand == "merge" and not flags & {"--abort", "--quit"}:
        # Integration belongs in this checkout. This hook cannot see the
        # user's merge authorization, so do not override Claude's native
        # permission decision with a new ask on every invocation.
        return "defer"
    if subcommand in COMMITTING_OR_DISCARDING_SUBCOMMANDS:
        return "allow" if unstages_only(subcommand, arguments) else "ask"
    if shared_repository_hazard(tokens, protected):
        return "ask"
    # Approve only what has been read and found routine. Defaulting the other
    # way was the mistake: it handed an outright approval -- which bypasses
    # Claude's permission flow entirely -- to every subcommand nobody had
    # thought about, and several of those rewrite this working tree.
    # `sparse-checkout` removes files from it, `checkout-index` and `read-tree`
    # overwrite them, `bisect` checks out other commits, `symbolic-ref` moves
    # HEAD without moving the index, `replace` changes what a commit resolves
    # to for the whole repository. None of them is authoring, so none was
    # refused, and none was named, so all were approved.
    #
    # Everywhere else in this gate the unknown case asks. This is the same
    # rule, applied where it was skipped.
    return "allow" if subcommand in ROUTINE_PROTECTED_SUBCOMMANDS else "ask"
