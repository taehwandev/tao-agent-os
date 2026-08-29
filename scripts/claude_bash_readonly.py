"""Read-only classification of Claude Bash commands for the worktree gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
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
    shell_keyword_command,
    substitution_bodies,
    unmodelled_operator,
)
from claude_bash_paths import (  # noqa: F401
    copy_source_token_indices,
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
# `uniq <in> <out>`, `tee`, and `awk`, whose write paths are the ordinary way
# to invoke them.
#
# `find` and `sort` are not in that company and used to be excluded anyway.
# Their write paths are spelled as options -- `find -delete/-exec`; `sort -o`,
# `-T`, and `--compress-program` -- so excluding the command denied every use
# of it, and listing a directory or ordering a listing became impossible inside
# a protected checkout. They are classified by their options below, the way
# `rg --pre` and `vibeguard --fix` already were.
READ_ONLY_COMMANDS = frozenset(
    {
        "basename",
        "cat",
        # A bare `cd` only moves the shell; the write it could precede arrives
        # as its own command and is judged then. Denying it stranded a session
        # whose persistent shell was parked inside a protected checkout.
        "cd",
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
# The declaration is injected by the parent hook environment, rather than read
# from agent-writable state. Each entry binds one canonical script path to its
# exact content. An operator revokes it by removing the environment declaration
# and refreshes it by recomputing the digest after an intentional script edit.
READ_ONLY_PYTHON_SCRIPTS_ENV = "TAO_CLAUDE_READ_ONLY_PYTHON_SCRIPTS"
READ_ONLY_PYTHON_SCRIPTS_SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
    except (OSError, ValueError):
        return None
    if executable_path == stable_launcher_path().expanduser().resolve() and len(tokens) > 1:
        if tokens[1] == WORKFLOW_START_HOOK:
            return "workflow_start"
        return "bootstrap" if tokens[1] in RUNTIME_CONTROL_HOOKS else None
    if not _current_python_interpreter(tokens[0]) or len(tokens) <= 2:
        return None
    script = Path(tokens[1]).expanduser()
    try:
        script = script.resolve()
    except (OSError, ValueError):
        return None
    expected = Path(__file__).resolve().with_name("agent-hook.py")
    if script != expected:
        return None
    if tokens[2] == WORKFLOW_START_HOOK:
        return "workflow_start"
    return "bootstrap" if tokens[2] in RUNTIME_CONTROL_HOOKS else None


def read_only_python_scripts() -> dict[Path, str]:
    """Strict digest-bound declarations supplied by the parent hook.

    One malformed entry invalidates the entire declaration. Partial acceptance
    would make an operator typo indistinguishable from an intentionally omitted
    check, so the only safe fallback is no script allowance.
    """

    raw_declaration = os.environ.get(READ_ONLY_PYTHON_SCRIPTS_ENV, "")
    if not raw_declaration:
        return {}
    try:
        raw = json.loads(raw_declaration)
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "scripts"}:
        return {}
    if raw.get("schema_version") != READ_ONLY_PYTHON_SCRIPTS_SCHEMA_VERSION:
        return {}
    entries = raw.get("scripts")
    if not isinstance(entries, list):
        return {}
    declarations: dict[Path, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            return {}
        raw_path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            return {}
        if SHA256_RE.fullmatch(digest) is None:
            return {}
        script = _canonical_regular_file(raw_path)
        if script is None or script in declarations:
            return {}
        if _file_sha256(script) != digest:
            return {}
        declarations[script] = digest
    return declarations


def _canonical_regular_file(raw_path: str) -> Path | None:
    """Return an absolute canonical regular non-symlink path, or nothing."""

    if not raw_path or "\x00" in raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return None
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if candidate != resolved or not stat.S_ISREG(candidate.lstat().st_mode):
            return None
    except (OSError, ValueError):
        return None
    return candidate


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return None
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return digest.hexdigest()


def _current_python_interpreter(token: str) -> bool:
    """Whether a token resolves to the Python running this hook."""

    if not token or "\x00" in token:
        return False
    selected = Path(token)
    if selected.is_absolute():
        candidate = selected
    elif selected.name == token:
        located = shutil.which(token)
        if not located:
            return False
        candidate = Path(located)
    else:
        return False
    try:
        resolved = candidate.resolve(strict=True)
        runtime = Path(sys.executable).resolve(strict=True)
        return resolved == runtime and stat.S_ISREG(resolved.stat().st_mode)
    except (OSError, ValueError):
        return False


def read_only_script_kind(tokens: list[str]) -> str | None:
    """Read-only when a digest-bound script is what the interpreter runs.

    The script has to be the interpreter's first argument, which is what keeps
    `-c`, `-m` and `-i` out: none of them can occupy that position and still
    resolve to a declared path. An unresolvable or undeclared path returns None
    and falls through to the mutating default, so the allowance fails closed.
    """

    if len(tokens) < 2:
        return None
    if not _current_python_interpreter(tokens[0]):
        return None
    script = _canonical_regular_file(tokens[1])
    if script is None:
        return None
    declarations = read_only_python_scripts()
    expected_digest = declarations.get(script)
    if expected_digest is None or _file_sha256(script) != expected_digest:
        return None
    return "read_only"


# A `sed` script writes through `w`, `W` and the `s///w` flag, and `-i`
# rewrites the operand in place. What remains -- printing a line range and
# substituting text on the way through a pipe -- writes nothing, and refusing
# it meant no pipeline could reshape the output it was reading.
SED_INERT_FLAGS = frozenset(
    {
        "--null-data",
        "--posix",
        "--quiet",
        "--regexp-extended",
        "--separate",
        "--silent",
        "--unbuffered",
        "-E",
        "-n",
        "-r",
        "-s",
        "-u",
        "-z",
    }
)
SED_ADDRESS = r"(?:\d+|\$|/(?:\\.|[^/\\])*/)(?:,(?:\d+|\$|/(?:\\.|[^/\\])*/))?"
# The delimiter is barred from being a word character, which is what stops a
# `w` command from being spelled as one. The flags omit `w`, which opens the
# file it names, and `e`, which hands the result to a shell.
SED_SUBSTITUTION = (
    r"s(?P<delimiter>[^\\\w\s])"
    r"(?:\\.|(?!(?P=delimiter))[^\\])*(?P=delimiter)"
    r"(?:\\.|(?!(?P=delimiter))[^\\])*(?P=delimiter)"
    r"[gpiImM0-9]*"
)
SED_READ_ONLY_COMMAND_RE = re.compile(
    rf"\s*(?:{SED_ADDRESS})?\s*(?:{SED_SUBSTITUTION}|p|=)\s*"
)


def sed_script_is_read_only(script: str) -> bool:
    """Whether every command in a script only prints or substitutes.

    Split on `;` without regard for a delimiter that holds one, so `s/a;b/c/`
    fails to parse and is refused. That is the strict direction: a script this
    module cannot read is one it cannot claim writes nothing.
    """

    return bool(script.strip()) and all(
        SED_READ_ONLY_COMMAND_RE.fullmatch(part) for part in script.split(";")
    )


def sed_kind(args: list[str]) -> str:
    """Read-only when sed neither edits in place nor writes from its script.

    Options are read wherever they appear rather than only in front of the
    script, because GNU sed accepts them after the operands too: judging only a
    leading run would have read `sed 's/a/b/' -i notes.txt` as a pipe filter
    while it rewrote the file.
    """

    scripts: list[str] = []
    script_taken = False
    index = 0
    while index < len(args):
        argument = args[index]
        if argument in {"-e", "--expression"}:
            if index + 1 >= len(args):
                return "mutating"
            scripts.append(args[index + 1])
            script_taken = True
            index += 2
            continue
        if argument.startswith("--expression="):
            scripts.append(argument.split("=", 1)[1])
            script_taken = True
            index += 1
            continue
        if argument in SED_INERT_FLAGS:
            index += 1
            continue
        if argument.startswith("-") and argument != "-":
            return "mutating"
        if not script_taken:
            scripts.append(argument)
            script_taken = True
        index += 1
    if not scripts:
        return "mutating"
    return "read_only" if all(map(sed_script_is_read_only, scripts)) else "mutating"


def find_writes(args: list[str]) -> bool:
    """Whether a `find` invocation carries an action that runs or writes.

    Matched by prefix rather than by exact spelling, so the `dir` and `f`
    variants an enumeration keeps missing -- `-execdir`, `-okdir`, `-fprintf`,
    `-fprint0` -- are covered by the option they extend. Every other primary is
    a test or a traversal option and opens nothing.
    """

    return any(
        argument in {"-delete", "-fls"}
        or argument.startswith(("-exec", "-ok", "-fprint"))
        for argument in args
    )


def sort_writes(args: list[str]) -> bool:
    """Whether a `sort` invocation names a write or executable path.

    Long options are compared the way the Git module compares unsafe options:
    an abbreviation is what the option starts with, so `--outp` is caught
    without enumerating every prefix. Besides writing its output, `sort` can
    create temporary files in a caller-selected directory and invoke a named
    compression program. The short write options can be bundled into a cluster
    (`-uo out`, `-uT .`), so the cluster's letters decide.
    """

    unsafe_long_options = (
        "--compress-program",
        "--output",
        "--temporary-directory",
    )
    for argument in args:
        name = argument.split("=", 1)[0]
        if name.startswith("--"):
            if len(name) > 2 and any(
                option.startswith(name) for option in unsafe_long_options
            ):
                return True
            continue
        if name.startswith("-") and any(option in name[1:] for option in "oT"):
            return True
    return False


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
    # A segment that is only a shell keyword runs nothing, so it earns no kind.
    # Every command a loop or branch actually runs still arrives as its own
    # segment and is classified below.
    commands = [shell_keyword_command(segment) for segment in segments]
    kinds = {simple_command_kind(command) for command in commands if command}
    if not kinds:
        return "read_only"
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
    script_kind = read_only_script_kind(command)
    if script_kind is not None:
        return script_kind
    executable = Path(command[0]).name
    if executable in READ_ONLY_COMMANDS:
        if executable == "rg" and any(arg == "--pre" or arg.startswith("--pre=") for arg in command[1:]):
            return "mutating"
        return "read_only"
    if executable == "sed":
        # The file operand is optional: a sed reading stdin at the end of a
        # pipe writes nothing either.
        return sed_kind(command[1:])
    if executable == "find":
        return "mutating" if find_writes(command[1:]) else "read_only"
    if executable == "sort":
        return "mutating" if sort_writes(command[1:]) else "read_only"
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
