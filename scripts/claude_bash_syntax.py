"""Shell syntax for the Claude Bash gate: tokens, operators, and segments.

Split from `claude_bash_readonly.py` so that reading a command line stays
separate from deciding what a command may do. The two failed differently: the
policy half was wrong about which programs write, while this half was wrong
about what the text even said, and an operator it did not model arrived as an
ordinary word. Keeping the lexer, the operator vocabulary, and the segment
splitter together is what lets that vocabulary be audited on its own.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import Path


SHELL_PUNCTUATION = frozenset({";", "&", "&&", "|", "||", ">", ">>", "<", "<<"})
REDIRECTIONS = frozenset({">", ">>", "<", "<<"})
# The lexer clusters adjacent metacharacters into one token, so an operator this
# module does not model arrives as an ordinary word rather than as punctuation:
# `>|`, `&>`, `&>>`, `<>` and `>&` all write, and every one of them classified
# as a read while the enumerated set was treated as exhaustive. Recognising the
# shape instead of the spelling is what makes the omission fail closed -- a
# token built only from metacharacters is an operator whether or not it is
# listed above, and an unlisted one is not understood well enough to allow.
OPERATOR_CHARS = frozenset(";&|<>")
# Process and file substitution run a command inside a redirection, so the
# program in the parentheses executes with no token of its own that this module
# would classify. `=(...)` is the zsh spelling and writes a temporary file too.
SUBSTITUTION_MARKERS = ("<(", ">(", "=(")
# Duplication points one stream at another and opens nothing; `-` closes the
# stream. Anything else after `>&` is a filename the shell truncates.
FD_DUPLICATIONS = frozenset({">&", "<&"})
FD_OPERAND_RE = re.compile(r"\d+|-")
# An input redirection feeds a command; it never writes. `>` and `>>` do write,
# except to the discard sink, which is how a probe silences stderr.
INPUT_REDIRECTIONS = frozenset({"<", "<<"})
DISCARD_TARGETS = frozenset({"/dev/null"})
ENV_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=.*$")
# `env` options that consume the next word, so the word after them names a
# value and not the program. `-P` is macOS's search path and was the one whose
# absence let `env -P /usr/bin git push` read `/usr/bin` as the program.
ENV_VALUE_OPTIONS = frozenset(
    {"-u", "--unset", "-C", "--chdir", "-P", "--path", "-S", "--split-string"}
)
# Options that change the environment a program receives, never its identity.
ENV_FLAGS = frozenset({"-", "-i", "-0", "-v", "--ignore-environment", "--null", "--debug"})
# What a reader may step over when it must also say what the command does, not
# only which program it is. Nothing here changes the environment the program
# runs in, which is the same thing the assignment-inertness rule refuses to
# guess at: `env -i` and `env -u` decide what the program will see, so a reader
# answering "does this write" stops at them instead of reading past them.
ENV_IDENTITY_ONLY_FLAGS = frozenset({"-v", "--debug"})


def past_env_options(
    tokens: list[str],
    index: int,
    *,
    value_options: "frozenset[str]" = ENV_VALUE_OPTIONS,
    flags: "frozenset[str]" = ENV_FLAGS,
) -> "int | None":
    """Step over `env` options, or None for a form that hides the program.

    `-S` and `--split-string` hold the command inside their own value, and an
    option this does not know may do the same, so neither is guessed at.

    Two callers ask two different questions of this one grammar, and they are
    not equally permissive. "Which program runs" is answered for every option
    above. "What does this command do" is not, so that caller narrows `flags`
    and `value_options` and lets everything else leave the command unread. The
    sets are parameters rather than a second copy of the loop: an option
    spelling learned here is learned by both readings at once.
    """

    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] == "--":
            # The standard end-of-options marker. Reading it as an option this
            # does not know refused `env -- git status`, which names its
            # program as plainly as any command here.
            return index + 1
        option = tokens[index].split("=", 1)[0]
        if option in {"-S", "--split-string"}:
            return None
        if option in value_options:
            index += 1 if "=" in tokens[index] else 2
            continue
        if option in flags:
            index += 1
            continue
        return None
    return index


# The shell's own words, which name no program. These all stand in front of a
# command that still follows, so each is stripped and what remains is what runs.
# Putting a word that opens a block into the terminator set below instead would
# drop the command behind it unclassified, which is how `else rm -rf build`
# would have been read as running nothing at all.
#
# `time` is deliberately absent: it takes a command as its operand, and this
# module would rather see that command in a segment of its own than model a
# keyword that swallows one. `case` is absent because its arms end in `)`, which
# the lexer hands back inside a word, so no reading of those segments is
# trustworthy and the mutating default is the honest verdict.
BLOCK_OPENING_KEYWORDS = frozenset(
    {"!", "do", "elif", "else", "if", "then", "until", "while", "{"}
)
# A terminator closes a block and takes no operand. It is recognised only when
# it is the whole segment, because anything following one is text this module
# did not expect and has no reading for.
BLOCK_TERMINATORS = frozenset({"done", "esac", "fi", "}"})
# `for` and `select` are followed by a name and a word list, never a command.
WORD_LIST_KEYWORDS = frozenset({"for", "select"})
# The one brace form this module resolves, matched positively. Listing the
# operators instead -- strip, default, replace, slice -- was an enumeration
# with the same failure mode as every other one here: `${!REF}` was not on the
# list and passed. Asking whether the braces hold a bare name has a last move,
# because everything that is not a name is something the shell computes.
PLAIN_PARAMETER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
PARAMETER_BRACE_RE = re.compile(r"\$\{[^}]*\}")
# A substitution stands in for text this module cannot produce. Masking it
# keeps the surrounding command readable; the unresolvable-text rule still
# refuses to claim where such a command writes.
SUBSTITUTION_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
SUBSTITUTION_PLACEHOLDER = "__tao_substitution__"


def single_quote_masked(command: str) -> str:
    """Blank what single quotes enclose, preserving every character position.

    Inside single quotes the shell substitutes nothing: `$(`, a backquote and
    `<(` are ordinary characters there. Reading them off the raw text is what
    made a `start` unreadable because its `--request` quoted a command, and an
    unreadable command is the strictest verdict this gate has -- so the gate
    denied the very `start` its own refusals ask for.

    Double quotes are tracked but not masked, because they substitute: `"$(x)"`
    runs `x`. They are tracked so that a literal apostrophe inside them --
    "it's" -- cannot be read as opening a single-quoted region and mask the
    substitution that follows it.

    Positions are preserved, so a caller may match on the masked text and slice
    the original at the same offsets.
    """

    masked = list(command)
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote != "'" and char == "\\" and index + 1 < len(command):
            # The escaped character is literal, so it can neither open nor
            # close a quoted region, and an escaped backquote or `$` starts no
            # substitution: `grep "\`x\`"` searches for backquotes. Reading it
            # as one made a chained start unreadable, and the raw-text fallback
            # then named the `--rules` checkout as its write target. The
            # escaped character is masked; a newline keeps its line break.
            if command[index + 1] != "\n":
                masked[index + 1] = "x"
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                masked[index] = "x"
        elif quote == '"':
            if char == '"':
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        index += 1
    return "".join(masked)


def computes_text(command: str) -> bool:
    """Whether the shell will run a command or open a process substitution here.

    One question asked of the masked text, so the tokeniser's two checks -- on
    the raw line and again on the newline-normalised one -- cannot drift apart.
    """

    masked = single_quote_masked(command)
    return (
        "$(" in masked
        or "`" in masked
        or any(marker in masked for marker in SUBSTITUTION_MARKERS)
    )


def substitution_bodies(command: str) -> list[str]:
    """The commands a substitution will run, in order.

    Matched against the single-quote-masked text and sliced out of the
    original, so a backquote inside `'...'` contributes no body -- the shell
    runs nothing there -- while `"$(x)"` still yields `x`.
    """

    bodies: list[str] = []
    for match in SUBSTITUTION_RE.finditer(single_quote_masked(command)):
        group = 1 if match.group(1) is not None else 2
        body = command[match.start(group):match.end(group)].strip()
        if body:
            bodies.append(body)
    return bodies


def mask_substitutions(command: str) -> str:
    """Replace each substitution with a placeholder that names no path."""

    return SUBSTITUTION_RE.sub(SUBSTITUTION_PLACEHOLDER, command)


# Where a session parks its own output: the OS temp directory, which holds the
# Claude session scratchpad. A write there lands in no governed project, so
# reading `grep ... > <scratch>/x` as a project write asked for a workflow start
# that governs nothing the command touches.
SCRATCH_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
# A directory holding any of these is a project, wherever it lives. Test
# fixtures and throwaway clones sit under the temp directory too, and a write
# into one of them is a project write like any other.
PROJECT_MARKERS = (".git", "AGENTS.md", "CLAUDE.md", ".agents")
# Text the shell would still expand; its target cannot be claimed.
UNRESOLVED_PATH_CHARS = frozenset("$`*?[{~")
# `cd` changes what a relative target means partway through a line.
DIRECTORY_CHANGERS = frozenset({"cd", "pushd", "popd"})
# Output-file options of curl, whose value is where it writes the body.
CURL_OUTPUT_OPTIONS = frozenset({"-o", "--output"})
CURL_OUTPUT_CLUSTER_RE = re.compile(r"-[sSfLIgG46]*o")
DISCARD_TARGET = "/dev/null"


def _scratch_roots() -> list[Path]:
    roots = [*SCRATCH_ROOTS, os.environ.get("TMPDIR", ""), tempfile.gettempdir()]
    resolved: list[Path] = []
    for raw in roots:
        if not raw:
            continue
        try:
            root = Path(raw).resolve()
        except (OSError, RuntimeError):
            continue
        if root != Path(root.anchor) and root not in resolved:
            resolved.append(root)
    return resolved


def scratch_write_target(raw: str, cwd: "Path | None") -> bool:
    """Whether a write to `raw` provably lands outside every project.

    The target is resolved the way the kernel will open it -- `..` collapsed and
    every existing symlink followed -- so an escape or a link back into a
    project resolves to that project and stays a write. Only a location strictly
    inside the temp directory, with no project marker between it and that
    directory, qualifies. A relative target needs the directory it is relative
    to; without one it is not claimed.
    """

    if not raw or set(raw) & UNRESOLVED_PATH_CHARS:
        return False
    path = Path(raw)
    if not path.is_absolute():
        if cwd is None:
            return False
        path = cwd / path
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    for root in _scratch_roots():
        if resolved == root or not resolved.is_relative_to(root):
            continue
        ancestors = [resolved, *resolved.parents]
        inside = ancestors[: ancestors.index(root)]
        return not any(
            (directory / marker).exists()
            for directory in inside
            for marker in PROJECT_MARKERS
        )
    return False


def discard_scratch_writes(tokens: list[str], cwd: "Path | None") -> list[str]:
    """Read each output that provably lands in scratch as the discard sink.

    The discard sink is already modelled everywhere a write is: a redirect to
    it drops out of the segment, and it names no project. A command whose
    output goes to scratch is therefore judged by what it does itself -- `npm
    test > <scratch>/log` stays `npm test`, and `grep > <scratch>/x` becomes the
    read it is. Nothing else is rewritten, and a target that is not proven to
    be scratch is left exactly as written.
    """

    if cwd is not None and DIRECTORY_CHANGERS & set(tokens):
        cwd = None
    output: list[str] = []
    program = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in {">", ">>"} and scratch_write_target(following, cwd):
            output.extend((token, DISCARD_TARGET))
            index += 2
            continue
        if token in {"&>", "&>>"} and scratch_write_target(following, cwd):
            output.extend((">", DISCARD_TARGET, "2", ">&", "1"))
            index += 2
            continue
        if token in SHELL_PUNCTUATION:
            program = ""
            output.append(token)
            index += 1
            continue
        if not program:
            program = Path(token).name
        elif program == "curl":
            name, equals, value = token.partition("=")
            if name == "--output" and equals and scratch_write_target(value, cwd):
                output.append(f"--output={DISCARD_TARGET}")
                index += 1
                continue
            if (
                token in CURL_OUTPUT_OPTIONS
                # A cluster of value-less flags ending in `-o`, as in `-so`;
                # `-Xo` is `-X o` and is left alone.
                or CURL_OUTPUT_CLUSTER_RE.fullmatch(token)
            ) and scratch_write_target(following, cwd):
                output.extend((token, DISCARD_TARGET))
                index += 2
                continue
        output.append(token)
        index += 1
    return output


def bash_command(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def _shell_lines(command: str) -> str | None:
    """Preserve quoted newlines; model unquoted ones as command separators.

    This is lexical normalization, not script interpretation. Comments and
    heredocs on multiline input remain unsupported; substitutions are rejected
    by the caller. Escaped newlines join shell words, except in single quotes.
    """
    if "\r" in command or ("\n" in command and "<<" in command):
        return None
    quote = ""
    output: list[str] = []
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following != "\n":
                output.extend((char, following))
            index += 2
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        if not quote and char == "#" and "\n" in command:
            return None
        if char == "\n" and not quote:
            output.append(" ; ")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def bash_invocation(payload: dict, cwd: Path) -> tuple[Path, list[str], bool]:
    """Return effective cwd, simple-command tokens, and syntax confidence."""

    command = bash_command(payload).strip()
    if not command:
        return cwd, [], False
    # Substitution has to be caught before tokenising: the lexer splits `<(rm
    # -rf build)` into a redirection plus the words inside it, so by token time
    # the command that runs there is indistinguishable from an operand. It is
    # read off the single-quote-masked text rather than the raw text, because
    # what `'...'` encloses is data the shell hands on unchanged.
    if computes_text(command):
        return cwd, [], False
    command = _shell_lines(command)
    if command is None or computes_text(command):
        return cwd, [], False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return cwd, [], False
    # A relative target is claimed only against a directory the line itself
    # names with a leading `cd <dir> &&`. The hook's reported cwd is not used
    # for it: an unmarked directory there is weaker evidence than a named one.
    prefixed = len(tokens) > 3 and tokens[0] == "cd" and tokens[2] == "&&"
    if prefixed:
        tokens = tokens[:3] + discard_scratch_writes(tokens[3:], _cd_target(tokens[1], cwd))
    else:
        tokens = discard_scratch_writes(tokens, None)
    punctuation = [index for index, token in enumerate(tokens) if token in SHELL_PUNCTUATION]
    if not punctuation:
        return cwd, tokens, True
    # A `cd <dir> && ...` prefix states where the rest of the command runs, and
    # that stays true when the rest is a pipeline. Requiring the whole command
    # to be punctuation-free here meant a session working inside a linked
    # worktree still had every compound command judged against the session cwd,
    # which is the checkout the session was launched from.
    if punctuation[0] == 2 and prefixed:
        rest = tokens[3:]
        return _cd_target(tokens[1], cwd), rest, not any(
            token in SHELL_PUNCTUATION for token in rest
        )
    return cwd, tokens, False


def _cd_target(raw: str, cwd: Path) -> Path:
    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = cwd / target
    try:
        return target.resolve()
    except OSError:
        return target


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


def shell_keyword_command(tokens: list[str]) -> list[str] | None:
    """The command a segment runs, or None when the segment only shapes a block.

    Splitting on `;` leaves the shell's own keywords sitting where a program
    name is expected, so `for f in *.kt; do head "$f"; done` was read as calls
    to `for`, `do` and `done` -- none of them on the allowlist, all of them
    mutating. A loop was therefore the one shape that could not be used to look
    at a protected checkout, which is the self-blocking this gate has been
    repaired for before.

    Dropping a keyword allows nothing on its own: the body of every loop and
    branch still arrives as its own segment and is classified there, so `for f
    in *; do rm "$f"; done` stays mutating because `rm` does. A `for` or
    `select` header is the one segment that runs nothing at all -- what follows
    `in` is a word list the shell expands, never a command -- and a
    substitution written inside one was already refused before tokenisation.
    """

    keywords = 0
    while keywords < len(tokens) and tokens[keywords] in BLOCK_OPENING_KEYWORDS:
        keywords += 1
    command = tokens[keywords:]
    if not command:
        return None
    if command[0] in WORD_LIST_KEYWORDS:
        return None
    if len(command) == 1 and command[0] in BLOCK_TERMINATORS:
        return None
    return command


def unmodelled_operator(tokens: list[str]) -> bool:
    """Whether any token is an operator this module does not model.

    `>&` and `<&` are the exception, and only when the operand is a file
    descriptor: `2>&1` points one stream at another and opens nothing, which is
    how anyone reads a command's stderr. Refusing it on shape alone blocked
    `cmd 2>&1 | grep`, ordinary inspection, which is the same self-blocking this
    gate has already been repaired for once. Given a filename instead, `>&`
    truncates that file, so the operand is what decides.
    """

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in FD_DUPLICATIONS:
            operand = tokens[index + 1] if index + 1 < len(tokens) else None
            if operand is None or not FD_OPERAND_RE.fullmatch(operand):
                return True
            index += 2
            continue
        if token and set(token) <= OPERATOR_CHARS and token not in SHELL_PUNCTUATION:
            return True
        index += 1
    return False


def has_unresolvable_expansion(command: str) -> bool:
    """Whether the shell will build text this module cannot reproduce.

    Enumerating how a path may be spelled is a game with no last move: a
    quoted space, an escaped space, `${VAR%/}`, `$(echo ...)`, and whatever
    comes next each need their own rule, and every one of them was found after
    the previous was fixed. Detecting that the command *will be expanded at
    all* has a last move, because the question stops being which spelling and
    becomes whether this module can claim to know the targets.

    Plain `$VAR` is excluded: expand_path_text resolves it exactly, so it is
    not unresolvable. What remains is substitution and the parameter operators,
    where the value is computed rather than substituted.

    Read off the single-quote-masked text for the same reason the tokeniser is:
    `'${VAR%/}'` quoted inside a `--request` is eleven literal characters, and
    calling that unresolvable put the session's own checkout into the verdict
    for a command that names no path at all.
    """

    masked = single_quote_masked(command)
    if "$(" in masked or "`" in masked:
        return True
    return any(
        not PLAIN_PARAMETER_RE.fullmatch(brace)
        for brace in PARAMETER_BRACE_RE.findall(masked)
    )


# ---------------------------------------------------------------------------
# Which program a raw command line runs, through prefixes and wrappers.
#
# The token reader above answers "does this write" on one lexed line. The
# publication hold asks something narrower -- which program each segment of a
# raw line runs, through wrappers and `$(...)` -- and it used to carry its own
# copy of this grammar inside the gate. Two copies drifted: `env -S "git push"`
# and `time -o out -P git push` were each fixed in one and not the other.
# The vocabulary lives here; claude_bash_raw_lines splits the raw text.
# ---------------------------------------------------------------------------

# A prefix assignment, matched on its name alone. Unlike ENV_ASSIGNMENT_RE this
# does not require the value to end the token, so a value holding a newline is
# still stepped over and the program behind it is still found.
ENV_ASSIGNMENT_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A shell given `-c` carries the command inside a string.
SHELL_PROGRAMS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Wrappers whose options are modelled, so the command after them is read.
# `!` is the shell's own negation and takes nothing.
WRAPPER_FLAGS_BY_NAME = {
    "!": frozenset(),
    "command": frozenset({"-p", "-v", "-V"}),
    "exec": frozenset({"-c", "-l"}),
    "nohup": frozenset(),
    "setsid": frozenset({"-c", "-f", "-w"}),
    "time": frozenset({"-p", "-a", "-v", "--portability", "--verbose", "--append"}),
}
WRAPPER_VALUES_BY_NAME = {
    "exec": frozenset({"-a"}),
    "time": frozenset({"-o", "-f", "--output", "--format"}),
}
# Wrappers that run another program through arguments this does not model --
# `nice -n 5 cmd`, `timeout 30 cmd`, `xargs cmd` -- so the program behind them
# is held rather than guessed at.
OPAQUE_WRAPPERS = frozenset(
    {
        "chroot", "doas", "ionice", "nice", "script", "stdbuf", "sudo",
        "taskset", "timeout", "unbuffer", "xargs",
    }
)
# Words and brackets that open a construct the raw reader does not model.
SHELL_STRUCTURE_WORDS = frozenset(
    {
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
        "done", "case", "esac", "in", "select", "function", "coproc",
        "{", "}", "(", ")", "[[", "]]",
    }
)
# Clause words that carry at most one ordinary command, and the words that
# close them. `case`, `select`, functions and groups stay unread.
CLAUSE_WORDS = frozenset({"if", "elif", "then", "else", "while", "until", "do"})
LOOP_CLOSING_WORDS = frozenset({"done", "fi"})
# Every marker that runs a command where it stands. `=(` is zsh's temporary
# file substitution and counts only at the start of an unquoted word, where
# zsh expands it: `arr=(a b)` is an array, `cat =(git push)` runs git.
RUNNING_SUBSTITUTION_MARKERS = ("$(", "`", "<(", ">(")
ZSH_FILE_SUBSTITUTION = "=("
# What a judged `$(...)` leaves behind: one word that names no program, so a
# substitution in command position still reads as computed.
SUBSTITUTED_WORD = "__tao_substituted__"


def computed_word(word: str) -> bool:
    return "$" in word or "`" in word or SUBSTITUTED_WORD in word


def past_assignments(tokens: list[str], index: int) -> int:
    while index < len(tokens) and ENV_ASSIGNMENT_PREFIX_RE.match(tokens[index]):
        index += 1
    return index


def past_wrapper_options(tokens: list[str], index: int, name: str) -> "int | None":
    """Step over one wrapper's options, or None for an option it does not model.

    Unknown means unread, not skipped: `time -o out git push` puts a filename
    where the program would be, and guessing past it is how `-P` got missed.
    """

    flags = WRAPPER_FLAGS_BY_NAME.get(name, frozenset())
    values = WRAPPER_VALUES_BY_NAME.get(name, frozenset())
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index].split("=", 1)[0]
        if tokens[index] == "--":
            return index + 1
        if option in values:
            index += 1 if "=" in tokens[index] else 2
            continue
        if option in flags:
            index += 1
            continue
        return None
    return index


def command_behind_wrappers(tokens: list[str]) -> "list[str] | None":
    """The program a prefix or wrapper runs, or None when it cannot be read.

    Assignments are stepped over here although `strip_env_assignments` refuses
    them: that answers what a command does, this only which program runs, and
    the shell executes git behind `LD_PRELOAD=...` either way. None is the
    answer for a wrapper whose program is not a token here -- `env -S`, an
    unknown option, `sudo` -- and callers hold it rather than release it.
    """

    index = 0
    for _ in range(len(tokens) + 1):
        index = past_assignments(tokens, index)
        if index >= len(tokens):
            return []
        head = tokens[index]
        name = head if head == "!" else Path(head).name
        if name == "env":
            stepped = past_env_options(tokens, index + 1)
        elif name in WRAPPER_FLAGS_BY_NAME:
            stepped = past_wrapper_options(tokens, index + 1, name)
        elif name in OPAQUE_WRAPPERS:
            return None
        else:
            return tokens[index:]
        if stepped is None:
            return None
        index = stepped
    return None


def shell_c_payload(tokens: list[str], index: int) -> "tuple[str | None, bool]":
    """The string a shell's `-c` carries, and whether the form was read.

    `-c` is not always its own token: `-lc` says the same thing. Anything
    before the payload that is neither an understood option nor the
    end-of-options marker leaves the form unread, because an option taking a
    value would shift which word the payload is.
    """

    saw_option = False
    while index < len(tokens) and tokens[index].startswith("-"):
        token = tokens[index]
        if token == "--":
            return None, True
        saw_option = True
        if not token.startswith("--") and "c" in token[1:]:
            following = index + 1
            return (tokens[following], True) if following < len(tokens) else (None, False)
        index += 1
    # `bash script.sh` runs a script, which is an ordinary program, but an
    # option this did not recognise may have taken the payload's place.
    return None, not saw_option
