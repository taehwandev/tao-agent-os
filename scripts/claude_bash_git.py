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
        "--unsafe-paths",
        "--upload-pack",
    }
)
GIT_SAFE_VALUE_OPTIONS = frozenset({"-C", "--git-dir", "--work-tree"})
# The `git branch` options that only list. Kept as one classifier vocabulary so
# read-only inspection of the protected checkout is not mistaken for a write.
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


# Global options that consume the next token as their value, and those that
# stand alone. Which is which decides where the subcommand begins, and being
# wrong by one token moves it: `--namespace` missing from the first set read
# `git --namespace n branch -D main` as the subcommand `n`, and the deletion
# disappeared from view.
GIT_VALUE_OPTIONS = frozenset(
    {
        "-C",
        "-c",
        "--attr-source",
        "--config-env",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
)
GIT_FLAG_OPTIONS = GIT_SAFE_FLAG_OPTIONS | frozenset(
    {
        "--exec-path",
        "--help",
        "--html-path",
        "--info-path",
        "--man-path",
        "--no-advice",
        "--no-lazy-fetch",
        "--paginate",
        "--version",
        "-h",
        "-p",
    }
)


def git_subcommand(tokens: list[str]) -> tuple[str | None, list[str]]:
    """The subcommand and its arguments; `None` when it cannot be located.

    A global option outside both vocabularies above ends the scan without an
    answer rather than guessing, because guessing has a direction: read one
    token too far and `branch -D main` becomes an unremarkable word. Callers
    treat "cannot tell" as the dangerous case, so an option this does not know
    costs a question, never a silent pass.

    `("", [])` is the different, harmless answer for `git` with no subcommand.
    """

    rest = tokens[1:]
    index = 0
    while index < len(rest):
        token = rest[index]
        name = token.split("=", 1)[0]
        if name in GIT_VALUE_OPTIONS:
            index += 1 if "=" in token else 2
            continue
        if not token.startswith("-"):
            return token, rest[index + 1 :]
        if name in GIT_FLAG_OPTIONS:
            index += 1
            continue
        return None, []
    return "", []


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


def _branch_arguments_are_read_only(arguments: list[str]) -> bool:
    """Recognise branch inspection without treating a branch name as creation."""

    if not arguments:
        return True
    value_options = {"--contains", "--merged", "--no-merged"}
    listing_mode = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        name = argument.split("=", 1)[0]
        if name == "--list":
            listing_mode = True
            index += 1
            continue
        if name in value_options:
            listing_mode = True
            index += 1
            if "=" not in argument and index < len(arguments):
                if not arguments[index].startswith("-"):
                    index += 1
            continue
        if argument in BRANCH_READ_ONLY_OPTIONS:
            listing_mode = True
            index += 1
            continue
        if listing_mode and not argument.startswith("-"):
            index += 1
            continue
        return False
    return listing_mode


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
        return "read_only" if _branch_arguments_are_read_only(args) else "mutating"
    if command == "remote":
        return "read_only" if not args or args[0] in {"-v", "get-url"} else "mutating"
    if command == "config":
        getters = {"--get", "--get-all", "--get-regexp", "--list"}
        names = {argument.split("=", 1)[0] for argument in args}
        return "read_only" if names & getters else "mutating"
    if command == "worktree":
        if args and args[0] == "list":
            return "read_only"
        if args and args[0] == "add":
            return "bootstrap"
        return "mutating"
    return "bootstrap" if command == "fetch" else "mutating"
