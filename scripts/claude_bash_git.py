"""Read-only classification of the `git` command line.

Split from `claude_bash_readonly.py` because Git carries its own option
vocabulary: which global options only choose a repository, which of them can
put a program where the classifier expects a read, and which subcommands
inspect rather than change. Keeping that vocabulary beside the general command
policy made one file answer two questions, and it is the Git half that grows
whenever an option turns out to be an execution path.
"""

from __future__ import annotations


UNSAFE_GIT_OPTIONS = frozenset(
    {
        "--exec",
        "--ext-diff",
        "--output",
        "--receive-pack",
        "--textconv",
        "--upload-pack",
    }
)
GIT_SAFE_VALUE_OPTIONS = frozenset({"-C", "--git-dir", "--work-tree"})
# The `git branch` options that only list. Named here rather than inline
# because the installer's permission rules are built from the same set: a
# second hand-written copy is the one that drifts toward approving `-D`.
BRANCH_READ_ONLY_OPTIONS = frozenset(
    {
        "-a",
        "-r",
        "-v",
        "-vv",
        "--contains",
        "--list",
        "--merged",
        "--no-merged",
        "--show-current",
    }
)
GIT_SAFE_FLAG_OPTIONS = frozenset(
    {
        "--bare",
        "--glob-pathspecs",
        "--icase-pathspecs",
        "--literal-pathspecs",
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        "--noglob-pathspecs",
        "-P",
    }
)
# Only commands that cannot write through an argument belong here, because a
# redirection is the sole write path this gate strips out. That rules out
# `sort -o`, `uniq <in> <out>`, `tee`, `awk`, and `find -delete/-exec`.


def names_unsafe_git_option(argument: str) -> bool:
    """Whether an argument names an option that runs or writes, abbreviated too.

    Git accepts any unambiguous prefix of a long option, so an exact-string
    denylist reads `--ext-dif` as an unremarkable word and hands the command
    back as a read while Git still runs the external differ. Comparing the
    other way -- does a known-unsafe option start with what was written --
    covers every abbreviation without enumerating them.
    """

    name = argument.split("=", 1)[0]
    if not name.startswith("--") or len(name) <= 2:
        return False
    return any(unsafe.startswith(name) for unsafe in UNSAFE_GIT_OPTIONS)


def git_command_kind(tokens: list[str]) -> str:
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        name = option.split("=", 1)[0]
        if name in GIT_SAFE_VALUE_OPTIONS:
            index += 1 if "=" in option else 2
            continue
        if name in GIT_SAFE_FLAG_OPTIONS:
            index += 1
            continue
        # Every other global option, `-c` and `--config-env` above all, can put
        # a program where this classifier expects only a read.
        return "mutating"
    if index >= len(tokens):
        return "read_only"
    command = tokens[index]
    args = tokens[index + 1 :]
    if any(names_unsafe_git_option(arg) for arg in args):
        return "mutating"
    # `blame`, `describe`, `shortlog` and `whatchanged` read history the same
    # way `log` and `show` do. They were absent rather than excluded, and a
    # review of the current branch is where that shows: reading who last
    # touched a line is inspection, and denying it left the reviewer unable to
    # answer the question a review is for.
    if command in {
        "blame",
        "check-ignore",
        "describe",
        "diff",
        "log",
        "ls-files",
        "ls-tree",
        "rev-parse",
        "shortlog",
        "show",
        "status",
        "whatchanged",
    }:
        return "read_only"
    if command == "branch":
        return (
            "read_only"
            if not args or all(arg in BRANCH_READ_ONLY_OPTIONS for arg in args)
            else "mutating"
        )
    if command == "remote":
        return "read_only" if not args or args[0] in {"-v", "get-url"} else "mutating"
    if command == "config":
        getters = {"--get", "--get-all", "--get-regexp", "--list"}
        return "read_only" if args and args[0] in getters else "mutating"
    if command == "worktree":
        if args and args[0] == "list":
            return "read_only"
        if args and args[0] == "add":
            return "bootstrap"
        return "mutating"
    return "bootstrap" if command == "fetch" else "mutating"
