"""Read-only classification of Claude Bash commands for the worktree gate."""

from __future__ import annotations

import re
from pathlib import Path

from claude_bash_git import git_command_kind
from claude_bash_syntax import (
    ENV_ASSIGNMENT_RE,
    SHELL_PUNCTUATION,
    bash_command,
    bash_invocation as _tokenise,
    command_segments,
    has_unresolvable_expansion,
    mask_substitutions,
    substitution_bodies,
    unmodelled_operator,
)
from claude_bash_paths import (  # noqa: F401
    path_arguments,
    raw_path_arguments,
)
from support.stable_launcher import stable_launcher_path


# An assignment prefix used to be stripped by name shape alone, which reads a
# variable's name without asking what the variable does. Many of them hand the
# following command a program to run: `LD_PRELOAD` and `DYLD_INSERT_LIBRARIES`
# inject a library into any binary, `BASH_ENV` and `ENV` source a script before
# the command's first line, `PYTHONSTARTUP`, `NODE_OPTIONS` and `PERL5OPT` do
# the same for their interpreters, and the whole `GIT_*` space can supply an
# external diff, a pager, or a synthesised config. Stripping those turned
# `LD_PRELOAD=evil.so cat file` into a read-only `cat`.
#
# The allowlist is therefore inert names only: locale, timezone, and terminal
# presentation, which change how output is rendered and never what runs.
# Anything outside it is not classified further -- an unrecognised assignment
# makes the command mutating, so the next executor variable someone invents
# fails closed instead of arriving as an allowance.
INERT_ENV_ASSIGNMENTS = frozenset(
    {
        "CLICOLOR",
        "CLICOLOR_FORCE",
        "COLUMNS",
        "GREP_COLOR",
        "GREP_COLORS",
        "LANG",
        "LANGUAGE",
        "LINES",
        "NO_COLOR",
        "TERM",
        "TZ",
    }
)
INERT_ENV_PREFIXES = ("LC_",)
# These two are read only by this runtime's own tooling and never select what
# executes: the session id labels which runtime session a hook binds to, and
# the soft-fail flag only masks a hook's exit status. Refusing them made the
# gate deny the exact `tao-hook start` remedy its own denial message names,
# because the documented invocation carries the session id as a prefix.
RUNTIME_HOOK_ENV_ASSIGNMENTS = frozenset(
    {
        "CLAUDE_CODE_SESSION_ID",
        "TAO_HOOK_SOFT_FAIL",
    }
)
# Only commands that cannot write through an argument belong here, because a
# redirection is the sole write path this module strips out. That rules out
# `sort -o`, `uniq <in> <out>`, `tee`, `awk`, and `find -delete/-exec`.
READ_ONLY_COMMANDS = frozenset(
    {
        "basename",
        "cat",
        "column",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "egrep",
        "fgrep",
        "file",
        "grep",
        "head",
        "jq",
        "ls",
        "mdls",
        "nl",
        "printf",
        "pwd",
        "realpath",
        "rg",
        "stat",
        "tail",
        "test",
        "tr",
        "true",
        "type",
        "uname",
        "wc",
        "which",
    }
)
RUNTIME_CONTROL_HOOKS = frozenset(
    {
        "cancel",
        "checkpoint",
        "fingerprint",
        "finish",
        "gate",
        "gate-batch",
        "handoff",
        "repair-verify",
        "resume",
        "review",
        "skill-curate",
        "skill-draft",
        "skill-feedback",
        "skill-maintenance",
        "skill-review",
    }
)
WORKFLOW_START_HOOK = "start"


def inert_env_assignment(token: str) -> bool:
    """Whether an assignment only changes presentation, never what runs."""

    match = ENV_ASSIGNMENT_RE.fullmatch(token)
    if match is None:
        return False
    name = match.group(1)
    return (
        name in INERT_ENV_ASSIGNMENTS
        or name in RUNTIME_HOOK_ENV_ASSIGNMENTS
        or name.startswith(INERT_ENV_PREFIXES)
    )


def strip_env_assignments(tokens: list[str]) -> list[str] | None:
    """Drop an inert assignment prefix, or refuse the command outright.

    Returning None rather than the remaining tokens is what keeps an executor
    variable from being classified by the command it wraps: the caller has no
    command left to look at, which is the correct reading of
    `LD_PRELOAD=... cat file`.
    """

    index = 0
    while index < len(tokens) and ENV_ASSIGNMENT_RE.fullmatch(tokens[index]):
        if not inert_env_assignment(tokens[index]):
            return None
        index += 1
    return tokens[index:]


def runtime_control_kind(tokens: list[str]) -> str | None:
    executable_path = Path(tokens[0]).expanduser()
    try:
        executable_path = executable_path.resolve()
    except OSError:
        return None
    if executable_path == stable_launcher_path().expanduser().resolve() and len(tokens) > 1:
        if tokens[1] == WORKFLOW_START_HOOK:
            return "workflow_start"
        return "bootstrap" if tokens[1] in RUNTIME_CONTROL_HOOKS else None
    if executable_path.name not in {"python", "python3"} or len(tokens) <= 2:
        return None
    script = Path(tokens[1]).expanduser()
    try:
        script = script.resolve()
    except OSError:
        return None
    expected = Path(__file__).resolve().with_name("agent-hook.py")
    if script != expected:
        return None
    if tokens[2] == WORKFLOW_START_HOOK:
        return "workflow_start"
    return "bootstrap" if tokens[2] in RUNTIME_CONTROL_HOOKS else None


def bash_command_kind(tokens: list[str], syntax_is_simple: bool) -> str:
    # Checked before either path: a clustered operator such as `>|` or `&>`
    # carries no metacharacter the simple path would notice and no punctuation
    # the segment splitter would act on, so both paths read it as a word.
    if unmodelled_operator(tokens):
        return "mutating"
    if syntax_is_simple:
        return simple_command_kind(tokens)
    # A compound command used to be mutating on sight, so plain inspection like
    # `grep ... | head` was blocked in a protected checkout and every diagnosis
    # had to be rewritten as single commands. Judge it by its parts instead and
    # keep the strictest kind any part earns.
    #
    # Chaining is how a control hook would be smuggled next to a write, but a
    # write is exactly what a `mutating` part already reports, and that verdict
    # still wins here. Voiding the bootstrap allowance on sight of a pipe
    # instead denied `git fetch && git worktree add`, the one command the
    # worktree denial message tells the reader to run.
    segments = command_segments(tokens) if tokens else None
    if not segments:
        return "mutating"
    kinds = {simple_command_kind(segment) for segment in segments}
    # Ordered strictest first, so the weakest allowance any part needs is the
    # one the whole command gets.
    for kind in ("mutating", "workflow_start", "bootstrap"):
        if kind in kinds:
            return kind
    return "read_only"


def simple_command_kind(tokens: list[str]) -> str:
    command = strip_env_assignments(tokens)
    if not command:
        return "mutating"
    runtime_kind = runtime_control_kind(command)
    if runtime_kind is not None:
        return runtime_kind
    executable = Path(command[0]).name
    if executable in READ_ONLY_COMMANDS:
        if executable == "rg" and any(arg == "--pre" or arg.startswith("--pre=") for arg in command[1:]):
            return "mutating"
        return "read_only"
    if executable == "sed":
        args = command[1:]
        print_only = (
            len(args) >= 3
            and args[0] == "-n"
            and re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", args[1]) is not None
        )
        return "read_only" if print_only else "mutating"
    if executable == "git":
        return git_command_kind(command)
    if executable == "vibeguard":
        args = command[1:]
        writes = any(arg == "--fix" or arg.startswith("--fix=") for arg in args)
        return "read_only" if args and args[0] == "audit" and not writes else "mutating"
    if executable == "npx":
        args = command[1:]
        while args and args[0] in {"--yes", "-y", "--no-install"}:
            args = args[1:]
        package = r"@taehwandev/vibeguard(?:@[^/\s]+)?"
        writes = any(arg == "--fix" or arg.startswith("--fix=") for arg in args)
        if len(args) > 1 and re.fullmatch(package, args[0]) and args[1] == "audit" and not writes:
            return "read_only"
    return "mutating"


def bash_invocation(payload: dict, cwd: Path) -> tuple[Path, list[str], bool]:
    """Tokenise a command, masking a substitution only when it cannot write.

    A substitution runs a program, so masking it unconditionally said nothing
    about `echo $(rm -rf build)` and called it a read. Refusing to parse on
    sight said nothing about `echo $(date)` either, and that one names no path
    and writes nothing, so it was judged an unlocatable mutation. Classifying
    the substituted command decides which it is: a read-only body is replaced
    by a placeholder and the outer command stays readable, and anything else
    leaves the command unparseable, which is already the strictest verdict.
    """

    command = bash_command(payload)
    bodies = substitution_bodies(command)
    if not bodies:
        return _tokenise(payload, cwd)
    for body in bodies:
        inner_cwd, tokens, simple = _tokenise({"tool_input": {"command": body}}, cwd)
        if not tokens or bash_command_kind(tokens, simple) != "read_only":
            return cwd, [], False
    masked = {"tool_input": {"command": mask_substitutions(command)}}
    return _tokenise(masked, cwd)
