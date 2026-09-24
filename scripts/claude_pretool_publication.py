"""What a command publishes while its run is still open.

Owner: the publication hold -- whether any segment of a command line pushes,
tags, opens or merges a pull request, or runs a project publication, and
whether a wrapper hides the program so that cannot be read.
Allowed imports: the standard library, claude_bash_syntax,
claude_bash_raw_lines, claude_bash_git, claude_command_effect and
claude_worktree_gate.
Forbidden imports: claude_pretool_gate and run evidence; a hold is decided
from the command alone.
Callers/tests: claude_pretool_gate (which re-exports these names);
tests/test_claude_pretool_gate.py, test_claude_pretool_merge_and_loops.py,
test_claude_shell_parser_parity.py.
Verification: those modules.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_git import git_subcommand
from claude_bash_raw_lines import raw_command_segments, read_substitutions
from claude_bash_syntax import (
    CLAUSE_WORDS,
    ENV_NAME_RE,
    LOOP_CLOSING_WORDS,
    SHELL_PROGRAMS,
    SHELL_STRUCTURE_WORDS,
    command_behind_wrappers,
    computed_word,
    shell_c_payload,
)
from claude_command_effect import github_pr_merge, github_publication
from claude_worktree_gate import project_publication_kind

PUBLICATION_LEAVES_THIS_MACHINE = frozenset({"push", "tag"})


def publication_before_finish_reason(root: Path, *, unreadable: bool = False) -> str:
    """Said from both places that can answer a publishing command."""

    if unreadable:
        return (
            f"Tao lifecycle: this session's run in {root} is still open, and "
            "this command hides the program it runs behind a wrapper, so "
            "whether it publishes cannot be read. Next: spell the command "
            "plainly, or record the route's remaining gates, run the review "
            "hook and run finish."
        )
    return (
        f"Tao lifecycle: this session's run in {root} is still open, so no gate "
        "ledger is closed and no review attestation covers what this would "
        "publish. Next: record the route's remaining gates, run the review "
        "hook, then run finish. Publication still requires matching action "
        "authority and unchanged finished inputs."
    )


def publishes_before_finish(tokens: list[str]) -> str:
    """Why this is held while its run is open: `publishes`, `unreadable`, or "".

    Only reached from the active-run branch, so the run has not finished: no
    gate ledger is closed and no review attestation covers what is about to
    leave. A local commit stays out of this set because it can be amended or
    reset, and a task legitimately commits while it works; a push, and the pull
    request opened from it, is what other people start acting on.

    `unreadable` is a wrapper that hides its program. Releasing those meant
    `env -S`, `env -P` and `command` each walked the publication straight out,
    and each was a separate option nobody had enumerated yet.
    """

    return _segment_hold(tokens, 0)


def publication_hold(
    command: str,
    depth: int = 0,
    root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """The strongest hold any segment of this command line asks for.

    Running only on a lone simple command let `git push && echo done` past,
    and calling every chain unreadable refused `bash -c "echo hi; echo bye"`.
    Segments answer both: one publishing segment holds the line, and a line
    whose segments all read and none publish is left alone.

    Each `$(...)` body is judged like any command line; the word left behind
    is data unless it lands where a program name goes, where `_segment_hold`
    still calls it computed.
    """

    if depth >= 3:
        return "unreadable"
    read = read_substitutions(
        command, lambda body: publication_hold(body, depth + 1, root, cwd), "publishes"
    )
    if read is None:
        return "unreadable"
    command, verdict = read
    if verdict == "publishes":
        return "publishes"
    segments = raw_command_segments(command)
    if segments is None:
        return "unreadable"
    for tokens in segments:
        found = _segment_hold(tokens, depth, root, cwd)
        if found == "publishes":
            return "publishes"
        if found == "unreadable":
            verdict = "unreadable"
    return verdict


def _segment_hold(
    tokens: list[str],
    depth: int,
    root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """One simple command: what it publishes, or that its program is hidden."""

    command = command_behind_wrappers(tokens)
    if command is None:
        return "unreadable"
    if not command:
        return ""
    head = command[0]
    # A loop or conditional is read, not refused: each clause word carries at
    # most one ordinary command, which is judged like any other segment, so
    # `for u in a b; do curl ...; done` is the curl it runs and
    # `if true; then git push; fi` is still the push.
    if head in LOOP_CLOSING_WORDS:
        return "" if len(command) == 1 else "unreadable"
    if head in CLAUSE_WORDS:
        return _segment_hold(command[1:], depth, root, cwd) if len(command) > 1 else ""
    if head == "for":
        # The word list is data. `$(...)` in it was already judged, and an
        # arithmetic `for ((...))` header is not modelled.
        plain = len(command) >= 2 and ENV_NAME_RE.fullmatch(command[1]) and (
            len(command) == 2 or command[2] == "in"
        )
        return "" if plain else "unreadable"
    # Checked on what the reader returned, so `! (git push)` is seen as the
    # construct it is rather than as a command called `!`.
    if head in SHELL_STRUCTURE_WORDS or head[0] in "({":
        return "unreadable"
    # A program the shell computes -- `$cmd push`, `bash -c "$cmd"`,
    # `$(echo git) push`, `eval "$cmd"` -- names nothing this can read.
    if computed_word(head) or Path(head).name == "eval":
        return "unreadable"
    if Path(command[0]).name in SHELL_PROGRAMS:
        payload, readable = shell_c_payload(command, 1)
        if not readable:
            return "unreadable"
        # `bash script.sh` runs a script, which is an ordinary program.
        return (
            publication_hold(payload, depth + 1, root, cwd)
            if payload is not None
            else ""
        )
    program = Path(command[0]).name
    if program == "git":
        subcommand, _arguments = git_subcommand(command)
        if subcommand and computed_word(subcommand):
            return "unreadable"
        return "publishes" if subcommand in PUBLICATION_LEAVES_THIS_MACHINE else ""
    # Every merge spelling is held before finish; only the admitted one is
    # later let through by a finished run.
    if github_publication(command) or github_pr_merge(command):
        return "publishes"
    if root is not None:
        return project_publication_kind(root, command, cwd or root)
    return ""
