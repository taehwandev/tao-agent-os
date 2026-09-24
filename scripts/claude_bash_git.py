"""Read-only classification of the `git` command line.

Split from `claude_bash_readonly.py` because Git carries its own option
vocabulary: which global options only choose a repository, which of them can
put a program where the classifier expects a read, and which subcommands
inspect rather than change. Keeping that vocabulary beside the general command
policy made one file answer two questions, and it is the Git half that grows
whenever an option turns out to be an execution path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


UNSAFE_GIT_OPTIONS = frozenset(
    {
        "--exec",
        "--ext-diff",
        # `git grep --open-files-in-pager=<cmd>` runs <cmd>. It arrives with
        # the subcommands just added, so it is named before it can be used.
        "--open-files-in-pager",
        "--output",
        "--receive-pack",
        "--textconv",
        "--unsafe-paths",
        "--upload-pack",
    }
)
# Subcommands that inspect and cannot write through any argument.
#
# The short list this grew from covered the commands people type by hand and
# stopped there, so `git merge-base`, `git show-ref`, `git cat-file`,
# `git rev-list`, `git for-each-ref` and `git grep` -- none of which can change
# anything -- were classified as mutations. Inside a protected checkout that
# meant an agent could not read the repository it was asked about: a guard
# tight in the one place tightness buys nothing, which is how a guard becomes
# the thing people switch off.
READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "annotate",
        "blame",
        "cat-file",
        "check-ignore",
        "cherry",
        "count-objects",
        "describe",
        "diff",
        "diff-files",
        "diff-index",
        "diff-tree",
        "for-each-ref",
        "grep",
        "help",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "var",
        "verify-commit",
        "verify-tag",
        "whatchanged",
    }
)
# `git tag` flags that create, delete, or open an editor.
TAG_WRITE_OPTIONS = frozenset(
    {
        "-a",
        "-d",
        "-e",
        "-f",
        "-m",
        "-s",
        "-u",
        "--annotate",
        "--delete",
        "--edit",
        "--file",
        "--force",
        "--local-user",
        "--message",
        "--sign",
        "-F",
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
    explicit_listing = any(
        word.split("=", 1)[0] in value_options | {"--list"}
        or (word.startswith("-") and set(word[1:]) <= set("arv")
            and bool(set(word[1:]) & set("ar")))
        for word in arguments
    )
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
        if argument in BRANCH_READ_ONLY_OPTIONS or (
            len(argument) > 1 and argument.startswith("-")
            and set(argument[1:]) <= set("arv")
        ):
            listing_mode = True
            index += 1
            continue
        if explicit_listing and not argument.startswith("-"):
            index += 1
            continue
        return False
    return listing_mode


def _self_protecting_ref_cleanup(command: str, args: list[str]) -> bool:
    """Local ref cleanup that git itself refuses whenever it could lose work.

    `branch -d` refuses an unmerged branch. Classifying it as
    mutations sent a lone merged-branch deletion through a whole workflow
    lifecycle. Only these exact spellings qualify; `-D`, `--force`, `-f`,
    clustered short flags and anything unrecognised stay mutations.
    """

    options = [argument for argument in args if argument.startswith("-")]
    names = [argument for argument in args if not argument.startswith("-")]
    if command == "branch":
        return bool(options) and set(options) <= {"-d", "--delete"} and bool(names)
    return False


def _prune_config(prefix: list[str], cwd: Path | None) -> dict[str, list[str]] | None:
    """Read effective ref cleanup configuration, including Git's include rules."""
    if cwd is None:
        return None
    try:
        result = subprocess.run(
            [*prefix, "config", "--null", "--get-regexp",
             r"^(remote\..*\.(fetch|prune|prunetags|tagopt)|fetch\.(all|prune|prunetags|recursesubmodules)|"
             r"submodule\.(recurse|.*\.fetchrecursesubmodules)|branch\..*\.remote)$"],
            cwd=cwd, capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if result.returncode != 0:
        return None
    config: dict[str, list[str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        key, separator, value = record.partition("\n")
        if not separator:
            return None
        config.setdefault(key, []).append(value)
    return config


def _tracking_prune_only(config: dict[str, list[str]], remotes: list[str],
                         refspecs: list[str] | None = None) -> bool:
    for remote in remotes:
        prune_tags = config.get(f"remote.{remote}.prunetags", config.get("fetch.prunetags", ["false"]))[-1]
        if prune_tags.lower() not in {"false", "no", "off", "0"}:
            return False
        specs = list(refspecs or config.get(f"remote.{remote}.fetch", []))
        if refspecs and any(":" not in spec and not spec.startswith("^") for spec in refspecs):
            specs = [spec for spec in refspecs if ":" in spec or spec.startswith("^")]
            specs += config.get(f"remote.{remote}.fetch", [])
        if not specs:
            return False
        for spec in specs:
            if spec.startswith("^"):
                continue
            source, separator, destination = spec.lstrip("+").partition(":")
            if not separator or not source or not destination.startswith("refs/remotes/"):
                return False
    return True


def _remote_prune_kind(prefix: list[str], args: list[str], cwd: Path | None) -> str:
    """Allow pruning only destinations proven to be remote-tracking refs."""
    options = {arg for arg in args[1:] if arg.startswith("-")}
    remotes = [arg for arg in args[1:] if not arg.startswith("-")]
    if not remotes or options - {"-n", "--dry-run"}:
        return "mutating"
    if options:
        return "read_only"
    config = _prune_config(prefix, cwd)
    return "bootstrap" if config is not None and _tracking_prune_only(config, remotes) else "mutating"


def _fetch_kind(prefix: list[str], args: list[str], cwd: Path | None) -> str:
    """A fetch may prune through flags or configuration, just like remote prune."""
    switches = {"--prune", "-p", "--no-prune", "--prune-tags", "--no-prune-tags",
                "--tags", "-t", "--no-tags", "-n", "--all", "--multiple", "--dry-run",
                "--verbose", "-v", "--quiet", "-q", "--force", "-f", "--append", "-a",
                "--atomic", "--no-write-fetch-head", "--write-fetch-head", "--unshallow",
                "--update-shallow", "--no-recurse-submodules", "--recurse-submodules",
                "--recurse-submodules=on-demand", "--recurse-submodules=yes", "--recurse-submodules=no",
                "--recurse-submodules=true", "--recurse-submodules=false", "--no-auto-maintenance", "--no-auto-gc"}
    value_options = {"--depth", "--deepen", "--shallow-since", "--shallow-exclude",
                     "--negotiation-tip", "--jobs", "-j", "--refmap"}
    flags, words, index = set(), [], 0
    tags_override = None
    recursion_options = []
    while index < len(args):
        name, equal, value = args[index].partition("=")
        if name in value_options:
            index += 1 if equal else 2
            if index > len(args) or name == "--refmap":
                return "mutating"
            continue
        if args[index] in switches:
            flags.add(args[index])
            if args[index] in {"--tags", "-t", "--no-tags", "-n"}:
                tags_override = "--tags" if args[index] in {"--tags", "-t"} else "--no-tags"
            if args[index].startswith(("--recurse-submodules", "--no-recurse-submodules")):
                recursion_options.append(args[index])
        elif args[index].startswith("-"):
            return "mutating"
        else:
            words.append(args[index])
        index += 1
    if "--dry-run" in flags:
        return "read_only"
    if "--prune-tags" in flags:
        return "mutating"
    config = _prune_config(prefix, cwd)
    if config is None:
        return "mutating"
    if not _fetch_recursion_safe(prefix, recursion_options, config, cwd):
        return "mutating"
    configured_all = config.get("fetch.all", ["false"])[-1].lower() not in {"false", "no", "off", "0"}
    if "--all" in flags or (not words and configured_all):
        remotes = [key[7:-6] for key in config if key.startswith("remote.") and key.endswith(".fetch")]
        refspecs = []
    elif "--multiple" in flags:
        remotes, refspecs = words, []
    else:
        remotes, refspecs = words[:1], words[1:]
    if "tag" in refspecs:
        return "mutating"
    if not remotes:
        try:
            branch = subprocess.run([*prefix, "symbolic-ref", "--quiet", "--short", "HEAD"],
                                    cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return "mutating"
        remotes = config.get(f"branch.{branch.stdout.strip()}.remote", ["origin"])[-1:]
    for remote in remotes:
        configured_specs = config.get(f"remote.{remote}.fetch", [])
        # Unknown operands may name a remote group with its own prune settings.
        if not configured_specs:
            return "mutating"
        # Explicit fetch operands do not replace configured refmaps: Git also
        # updates matching configured destinations opportunistically.
        for spec in [*configured_specs, *refspecs]:
            if spec.startswith("^"):
                continue
            source, separator, destination = spec.lstrip("+").partition(":")
            if (refspecs or spec.startswith("+") or flags & {"--force", "-f"}) and (
                separator and not destination.startswith("refs/remotes/")
            ):
                return "mutating"
        tags = config.get(f"remote.{remote}.tagopt", [""])[-1]
        if tags not in {"", "--tags", "--no-tags"}:
            return "mutating"
        if tags_override is not None:
            tags = tags_override
        if flags & {"--force", "-f"} and tags == "--tags":
            return "mutating"
        prune = config.get(f"remote.{remote}.prune", config.get("fetch.prune", ["false"]))[-1]
        if flags & {"--prune", "-p"} or prune.lower() not in {"false", "no", "off", "0"}:
            if not _tracking_prune_only(config, [remote], refspecs):
                return "mutating"
    return "bootstrap"


def _fetch_recursion_safe(prefix: list[str], args: list[str], config: dict[str, list[str]],
                          cwd: Path | None) -> bool:
    """Child repositories need their own effective ref checks if Git may fetch them."""
    false_values = {"false", "no", "off", "0"}
    mode = config.get("fetch.recursesubmodules", config.get("submodule.recurse", ["on-demand"]))[-1]
    per_module = any(key.endswith(".fetchrecursesubmodules") and values[-1].lower() not in false_values
                     for key, values in config.items() if key.startswith("submodule."))
    for argument in args:
        if argument == "--no-recurse-submodules":
            mode, per_module = "false", False
        elif argument == "--recurse-submodules":
            mode = "true"
        elif argument.startswith("--recurse-submodules="):
            mode, per_module = argument.split("=", 1)[1], False
    if mode.lower() in false_values and not per_module:
        return True
    try:
        result = subprocess.run([*prefix, "ls-files", "--stage", "-z"], cwd=cwd,
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
    return result.returncode == 0 and not any(
        record.startswith("160000 ") for record in result.stdout.split("\0")
    )


def git_command_kind(tokens: list[str], cwd: Path | None = None) -> str:
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
    names = {argument.split("=", 1)[0] for argument in args}
    words = [argument for argument in args if not argument.startswith("-")]
    if any(names_unsafe_git_option(arg) for arg in args):
        return "mutating"
    # The short spelling of `--open-files-in-pager`, which takes its command
    # attached (`-Oless`) rather than as a separate token.
    if any(arg.startswith("-O") for arg in args):
        return "mutating"
    # `blame`, `describe`, `shortlog` and `whatchanged` read history the same
    # way `log` and `show` do. They were absent rather than excluded, and a
    # review of the current branch is where that shows: reading who last
    # touched a line is inspection, and denying it left the reviewer unable to
    # answer the question a review is for.
    if command in READ_ONLY_GIT_SUBCOMMANDS:
        return "read_only"
    if command == "tag":
        # `git tag` with no name lists; a name creates one. `-l` takes a
        # pattern, so a positional is only a write when nothing asked to list.
        listing = bool(
            names & {"-l", "--list", "--contains", "--points-at", "--merged", "--no-merged"}
        )
        if names & TAG_WRITE_OPTIONS:
            return "mutating"
        return "read_only" if listing or not words else "mutating"
    if command == "stash":
        return "read_only" if args and args[0] in {"list", "show"} else "mutating"
    if command == "reflog":
        # Bare, `show`, `exists`, or show options (`-5`, `--oneline`) only read;
        # `expire`, `delete` and any other word stay mutations.
        return "read_only" if not args or args[0] in {"show", "exists"} or args[0].startswith("-") else "mutating"
    if command == "submodule":
        return "read_only" if args and args[0] in {"status", "summary"} else "mutating"
    if command == "symbolic-ref":
        # One name reads it; two set it.
        if names & {"-d", "--delete"}:
            return "mutating"
        return "read_only" if len(words) <= 1 else "mutating"
    if _self_protecting_ref_cleanup(command, args):
        return "bootstrap"
    if command == "branch":
        return "read_only" if _branch_arguments_are_read_only(args) else "mutating"
    if command == "remote":
        if args and args[0] == "prune":
            return _remote_prune_kind(tokens[:index], args, cwd)
        return "read_only" if not args or args[0] in {"-v", "get-url"} else "mutating"
    if command == "config":
        getters = {"--get", "--get-all", "--get-regexp", "--list"}
        names = {argument.split("=", 1)[0] for argument in args}
        return "read_only" if names & getters else "mutating"
    if command == "worktree":
        if args and args[0] == "list":
            return "read_only"
        # Creating and removing a worktree are the same lifecycle, and the
        # workflow runs it constantly: branch a worktree, work, remove it.
        # Only `add` was recognised, so the removal that closes every task
        # asked for confirmation -- one more Enter on the most routine step
        # there is.
        #
        # Git already refuses to remove a worktree holding modified or
        # untracked files and says to use `--force`, so the plain form cannot
        # lose work; `prune` only clears records for directories that are
        # already gone. `--force` is what overrides that, and it stays a
        # mutation.
        if args and args[0] in {"add", "remove", "prune"}:
            forcing = any(
                argument in {"-f", "--force"} for argument in args[1:]
            )
            return "mutating" if forcing else "bootstrap"
        return "mutating"
    return _fetch_kind(tokens[:index], args, cwd) if command == "fetch" else "mutating"
