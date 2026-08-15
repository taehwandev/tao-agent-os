"""Read-only classification of Claude Bash commands for the worktree gate."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from support.stable_launcher import stable_launcher_path


SHELL_PUNCTUATION = frozenset({";", "&", "&&", "|", "||", ">", ">>", "<", "<<"})
REDIRECTIONS = frozenset({">", ">>", "<", "<<"})
# An input redirection feeds a command; it never writes. `>` and `>>` do write,
# except to the discard sink, which is how a probe silences stderr.
INPUT_REDIRECTIONS = frozenset({"<", "<<"})
DISCARD_TARGETS = frozenset({"/dev/null"})
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
# Only commands that cannot write through an argument belong here, because a
# redirection is the sole write path this gate strips out. That rules out
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


def bash_command(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def bash_invocation(payload: dict, cwd: Path) -> tuple[Path, list[str], bool]:
    """Return effective cwd, simple-command tokens, and syntax confidence."""

    command = bash_command(payload).strip()
    if not command or "\n" in command or "\r" in command or "$(" in command or "`" in command:
        return cwd, [], False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return cwd, [], False
    punctuation = [index for index, token in enumerate(tokens) if token in SHELL_PUNCTUATION]
    if not punctuation:
        return cwd, tokens, True
    # A `cd <dir> && ...` prefix states where the rest of the command runs, and
    # that stays true when the rest is a pipeline. Requiring the whole command
    # to be punctuation-free here meant a session working inside a linked
    # worktree still had every compound command judged against the session cwd,
    # which is the checkout the session was launched from.
    if punctuation[0] == 2 and len(tokens) > 3 and tokens[0] == "cd" and tokens[2] == "&&":
        target = Path(tokens[1]).expanduser()
        if not target.is_absolute():
            target = cwd / target
        try:
            effective_cwd = target.resolve()
        except OSError:
            effective_cwd = target
        rest = tokens[3:]
        return effective_cwd, rest, not any(token in SHELL_PUNCTUATION for token in rest)
    return cwd, tokens, False


def strip_env_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and ENV_ASSIGNMENT_RE.fullmatch(tokens[index]):
        index += 1
    return tokens[index:]


def git_command_kind(tokens: list[str]) -> str:
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
    if index >= len(tokens):
        return "read_only"
    command = tokens[index]
    args = tokens[index + 1 :]
    unsafe_read_args = {"--ext-diff", "--textconv"}
    if any(
        arg in unsafe_read_args or arg == "--output" or arg.startswith("--output=")
        for arg in args
    ):
        return "mutating"
    if command in {"check-ignore", "diff", "log", "ls-files", "rev-parse", "show", "status"}:
        return "read_only"
    if command == "branch":
        allowed = {"-a", "-r", "-v", "-vv", "--contains", "--list", "--merged", "--no-merged", "--show-current"}
        return "read_only" if not args or all(arg in allowed for arg in args) else "mutating"
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


def command_segments(tokens: list[str]) -> list[list[str]] | None:
    """Split a compound command into its parts, or None when it can write.

    An output redirection writes a file whatever the commands around it do, so a
    command that contains one never qualifies as read-only. Two forms carry no
    write and are dropped instead: an input redirection only reads, and a
    redirect to the discard sink throws its output away. Refusing those made
    `2>/dev/null` -- the ordinary way to silence a probe's stderr -- enough to
    reclassify a plain `grep` as mutating, so diagnosing this gate inside a
    protected checkout was blocked by the gate itself.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in REDIRECTIONS:
            operand = tokens[index + 1] if index + 1 < len(tokens) else None
            if token not in INPUT_REDIRECTIONS and operand not in DISCARD_TARGETS:
                return None
            index += 2
            continue
        if token in SHELL_PUNCTUATION:
            segments.append(current)
            current = []
            index += 1
            continue
        current.append(token)
        index += 1
    segments.append(current)
    return segments if all(segments) else None


def bash_command_kind(tokens: list[str], syntax_is_simple: bool) -> str:
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


def path_arguments(tokens: list[str]) -> list[Path]:
    """Absolute paths a command names outright, in order.

    Bash is judged by the session working directory, so a command run from one
    project could still write into a protected checkout it named by absolute
    path. Only argv-shaped paths are visible here: a path buried inside a quoted
    script body is one token of program text, not an argument, so this narrows
    the hole rather than closing it.
    """
    paths: list[Path] = []
    for token in tokens:
        if token.startswith("-") or ENV_ASSIGNMENT_RE.fullmatch(token):
            continue
        if not (token.startswith("/") or token.startswith("~/")):
            continue
        paths.append(Path(token).expanduser())
    return paths
