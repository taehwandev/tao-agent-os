"""Whether an `xargs` command line runs a program that can never publish.

Owner: the `xargs` option vocabulary and the programs it may run unread.
`claude_bash_syntax` still treats `xargs` as an opaque wrapper; this answers
the narrower question the publication hold asks.
Allowed imports: the standard library and claude_bash_syntax.
Forbidden imports: any gate, policy or run-evidence module.
Callers/tests: claude_pretool_publication;
tests/test_claude_pretool_redirect_and_xargs.py.
Verification: that test module, then tests/test_claude_pretool_merge_and_loops.py.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_syntax import computed_word, past_assignments

# `xargs` appends words it reads to the program it runs, so the program is only
# judged when nothing appended can make it publish: these never push, tag or
# open a pull request whatever their arguments, and none runs a command string
# (which is why `sed`, `awk`, `find` and shells are absent). A replacement
# string (`-I`, `-J`, `-i`, `--replace`) puts words anywhere, so it stays
# unread, as does any option not listed here.
XARGS_FLAGS = frozenset(
    {
        "-0", "-r", "-t", "-p", "-x", "-o", "--null", "--no-run-if-empty",
        "--verbose", "--interactive", "--exit", "--open-tty",
    }
)
XARGS_VALUE_OPTIONS = frozenset(
    {
        "-n", "-L", "-P", "-s", "-d", "-E", "-a", "--max-args", "--max-lines",
        "--max-procs", "--max-chars", "--delimiter", "--eof", "--arg-file",
    }
)
XARGS_LOCAL_PROGRAMS = frozenset(
    {
        "basename", "cat", "chmod", "cp", "dirname", "du", "echo", "egrep",
        "fgrep", "file", "grep", "head", "ln", "ls", "md5", "mkdir", "mv",
        "printf", "readlink", "realpath", "rg", "rm", "rmdir", "sha256sum",
        "shasum", "sort", "stat", "tail", "touch", "uniq", "wc",
    }
)


def xargs_runs_local_program(tokens: list[str]) -> bool:
    """Whether `tokens` (after assignments) is `xargs` running a local program."""

    index = past_assignments(tokens, 0)
    if index >= len(tokens) or Path(tokens[index]).name != "xargs":
        return False
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        word = tokens[index]
        if word == "--":
            index += 1
            break
        option = word.split("=", 1)[0]
        if option in XARGS_FLAGS:
            index += 1
        elif option in XARGS_VALUE_OPTIONS:
            index += 1 if "=" in word else 2
        elif word[:2] in XARGS_VALUE_OPTIONS and not word.startswith("--"):
            index += 1  # a joined value, as in `-n2` or `-P4`
        else:
            return False
    if index >= len(tokens) or computed_word(tokens[index]):
        return False
    return Path(tokens[index]).name in XARGS_LOCAL_PROGRAMS
