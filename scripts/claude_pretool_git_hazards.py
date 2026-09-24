"""Which Git commands reach state every linked worktree shares.

Owner: the reason a Git command deserves one question -- refs, remotes,
tags, config, the object store and the reflog live in the common Git
directory, and a protected branch is named by the caller's policy.
Allowed imports: the standard library and claude_bash_git.
Forbidden imports: claude_pretool_gate and any run-evidence or policy reader;
the caller supplies the protected branch names.
Callers/tests: claude_pretool_gate (which re-exports these names);
tests/test_shared_repository_hazard.py, test_safe_ref_cleanup.py,
test_claude_pretool_gate.py.
Verification: those modules.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_git import git_subcommand, names_unsafe_git_option


def names_a_protected_branch(words: list[str], protected: frozenset[str] | None) -> bool:
    """Whether this command's targets include a branch the repository protects.

    Fails closed twice over: an unreadable policy (`None`) and a command that
    names no branch at all are both answered "yes". Deleting without saying
    what, or without knowing what is protected, is exactly when a question is
    worth asking.

    A refspec may arrive as `topic`, `:topic` or `heads/topic`; all three name
    the same branch, and matching only the first spelling would let the other
    two through.
    """

    if protected is None or not words:
        return True
    for word in words:
        candidate = word.split(":")[-1].strip()
        if not candidate:
            continue
        for prefix in ("refs/heads/", "heads/"):
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
        if candidate in protected:
            return True
    return False


def _shared_history_hazard(
    subcommand: str,
    arguments: list[str],
    flags: set[str],
    short_flags: set[str],
    words: list[str],
    first: str,
) -> str:
    """Why this command deserves a question about state every worktree shares.

    The other half of the list asks about this working tree -- a branch
    deleted, a push, a hard reset, a checkout over local edits. These reach
    further: refs, reflogs, objects, remotes and config that every worktree
    on the repository reads. Split for the block limit, along the line the
    list already divides on.
    """

    if subcommand == "tag" and (
        short_flags & {"d", "f"} or flags & {"--delete", "--force"}
    ):
        return "deletes or overwrites a tag every worktree shares"
    update_ref_help = flags in ({"-h"}, {"--help"})
    if subcommand == "update-ref" and arguments and not update_ref_help:
        return "writes a shared ref directly, past the commands that check it"
    if subcommand in {"filter-branch", "filter-repo"}:
        return "rewrites the entire shared history"
    if subcommand == "reflog" and first in {"expire", "delete"}:
        return "removes the reflog, which is how the rest of this list is undone"
    if subcommand == "gc" and "--prune" in flags:
        return "prunes objects the reflog would otherwise recover"
    if subcommand == "prune":
        return "deletes unreachable objects from the shared object store"
    if subcommand == "replace" and flags & {"-d", "--delete"}:
        return "deletes a replacement ref every worktree shares"
    if subcommand == "remote" and first in {"remove", "rm", "set-url"}:
        return "changes a remote every worktree shares"
    if subcommand == "stash" and first in {"drop", "clear"}:
        return "drops stashed work every worktree shares"
    if subcommand == "worktree" and flags & {"-f", "--force"}:
        # Only the forced forms. Git refuses to remove a worktree holding
        # modified or untracked files, and refuses to add one over a path it
        # already registers; the plain forms therefore cannot lose anything,
        # and asking about them put a prompt on the step that closes every
        # task, on top of a check git was already making. `--force` is what
        # overrides both refusals.
        return "forces past git's own refusal to overwrite or drop a worktree"
    if subcommand == "submodule" and first in {"deinit", "foreach", "set-url"}:
        return "removes files, changes shared config, or executes a nested command"
    if subcommand == "config":
        getters = {"--get", "--get-all", "--get-regexp", "--list"}
        if flags & getters:
            return ""
        if flags & {"-f", "--file", "--global", "--system"}:
            return "changes Git configuration outside this repository"
        if "core.hooksPath" in words:
            return "changes the executable hooks path every worktree shares"
    return ""


def shared_repository_hazard(
    tokens: list[str], protected: frozenset[str] | None = None
) -> str:
    """Why this Git command deserves one question, or "" for the ordinary kind.

    A linked worktree isolates the working tree and nothing else. Refs,
    remotes, tags, config, the object store and the reflog live in the common
    Git directory every worktree shares, so a handful of commands reach exactly
    what they would reach from the protected checkout.

    That is a reason to name those commands, not to distrust Git. Committing,
    branching, merging, stashing and pushing inside your own worktree is the
    work, and stopping it stops everything for the sake of the rare case. So
    this returns a reason only for the short list below, where losing
    work or escaping through an output/execution option is the command's actual
    effect -- and the answer there is `ask`, not `deny`, because each of these
    is sometimes precisely what was meant.
    """

    if not tokens or Path(tokens[0]).name != "git":
        return ""
    subcommand, arguments = git_subcommand(tokens)
    if subcommand is None:
        return "uses a Git option this gate cannot read, so what it does is unknown"
    if subcommand:
        subcommand_index = len(tokens) - len(arguments) - 1
        global_names = {
            token.split("=", 1)[0] for token in tokens[1:subcommand_index]
        }
        if global_names & {"-c", "--config-env", "--exec-path"}:
            return "changes configuration or executable lookup for this Git invocation"
    if any(names_unsafe_git_option(argument) for argument in arguments):
        return "names an option that can write output or execute another program"
    flags = {argument.split("=", 1)[0] for argument in arguments}
    words = [argument for argument in arguments if not argument.startswith("-")]
    first = words[0] if words else ""
    short_flags = {
        letter
        for argument in arguments
        if argument.startswith("-") and not argument.startswith("--")
        for letter in argument[1:]
    }

    if subcommand == "branch":
        # `-d` refuses to drop unmerged work; `-D`, `-M`, and `-f` do not.
        # Git accepts bundled short flags, so `-vD` must be read as containing
        # `-D`, not mistaken for an unrelated listing option.
        forced_long = "--force" in flags and flags & {"--delete", "--move"}
        if short_flags & {"D", "M", "f"} or forced_long:
            # Which branch decides, not which flag. A squash merge leaves the
            # topic branch looking unmerged to `-d`, so `-D` is the ordinary way
            # to clean it up -- and asking about every one of those put a prompt
            # on the last step of every task. What must not go quietly is the
            # branch this repository names as protected.
            if names_a_protected_branch(words, protected):
                return "deletes or overwrites a branch this repository protects"
    if subcommand == "push":
        if "f" in short_flags or flags & {"--force", "--force-with-lease", "--mirror"}:
            return "rewrites or deletes a published branch"
        deleting = "--delete" in flags or "d" in short_flags
        # `git push origin :main` deletes main too: a refspec with an empty
        # source pushes nothing onto the target. It carries no flag, so a check
        # that looked only at `--delete` let the older spelling through.
        colon_deletes = [word for word in words[1:] if word.startswith(":")]
        if deleting or colon_deletes:
            # `git push <remote> --delete <branch>`: the first word is the
            # remote, so the branches are what follow it.
            if names_a_protected_branch(colon_deletes or words[1:], protected):
                return "deletes a published branch this repository protects"
        if any(word.startswith("+") for word in words):
            return "force-pushes: a leading + in a refspec rewrites the remote"
    if subcommand == "reset" and "--hard" in flags:
        return "discards committed work reachable only from here"
    dry_run = short_flags & {"n"} or "--dry-run" in flags
    if subcommand == "clean" and not dry_run:
        return "deletes untracked work from this worktree"
    if subcommand == "restore":
        staged_only = "--staged" in flags and "--worktree" not in flags
        if not staged_only:
            return "discards uncommitted work from this worktree"
    if subcommand == "checkout":
        if short_flags & {"B", "f"} or flags & {"--force"} or "--" in arguments:
            return "discards work or overwrites a branch"
    if subcommand == "switch":
        force_flags = {"--discard-changes", "--force", "--force-create"}
        if short_flags & {"C", "f"} or flags & force_flags:
            return "discards work or overwrites a branch"
    return _shared_history_hazard(
        subcommand, arguments, flags, short_flags, words, first
    )
