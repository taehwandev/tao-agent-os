"""The one line a runtime keeps on screen: where you are, what is left, what is running.

Claude Code and Antigravity both render a status line the same way -- they run a
command on every draw, hand it the session as JSON on stdin, and print whatever
it writes -- so the line itself is written once here and each runtime keeps only
its own entry point.

That sharing is not tidiness. The two renderers were copies, and the copy is how
a defect travelled: a status word outside the installer's vocabulary was written
in one and inherited by the other, so a correctly installed status line reported
as missing on both. A third segment written twice would have been the same
mistake again.

Two rules shape everything below. The line is drawn constantly, so nothing may
block: every read is guarded and every failure degrades to a shorter line rather
than an error. And the slot is shared with other tools, so `chain` forwards the
untouched payload to whatever held it before and keeps that output.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from support.runtime_quota import DIM, SEPARATOR, paint, remaining_summary
from support.tao_run_state import work_segment


# Long enough for a local file read behind a cold page cache, short enough that
# a wedged chain target cannot hold the frame. The status line redraws often;
# one slow draw is invisible, a hung one is the whole terminal.
CHAIN_TIMEOUT_SECONDS = 2.0

# Past this, the path is shortened. It is set so the ordinary checkout and one
# directory inside it still print whole, because those are the paths an operator
# reads rather than scans.
PATH_LIMIT = 34

# What replaces the segments that are dropped.
ELISION = "…"


def render(payload_text: str, chain: str = "", *, color: bool = False) -> str:
    """The whole line, for a payload the runtime already sent.

    The quota is the part that has to be seen without being looked for, so it
    keeps its colour while the two segments around it are dimmed. Where you are
    and what is running are context: worth having on screen, not worth
    competing with the number that says when to stop.
    """

    payload = parse(payload_text)

    # Tao's own segments are divided the same way the windows inside the quota
    # summary are, so the line reads as one thing. What the chain returns is
    # someone else's text and gets plain space instead: a divider would claim it
    # as part of this layout.
    #
    # Quota, then where, then what -- the order this line already shipped with.
    # Reordering it would be a change nobody asked for, and the quota leading
    # suits it anyway: that is the segment worth seeing without looking for it.
    context = [location_segment(payload), work_segment(payload)]
    if color:
        context = [paint(segment, DIM) for segment in context]
    mine = SEPARATOR.join(
        segment
        for segment in (
            remaining_summary(payload.get("rate_limits"), color=color),
            *context,
        )
        if segment
    )
    chained = run_chained(chain, payload_text)
    return "  ".join(segment for segment in (mine, chained) if segment)


def color_enabled(environment: dict[str, str] | None = None) -> bool:
    """Whether to emit colour at all.

    `NO_COLOR` is honoured because a status line is exactly the sort of output
    someone captures, diffs, or reads through a tool that does not interpret
    escapes, and the line says everything it says without colour anyway.
    """

    values = os.environ if environment is None else environment
    return not str(values.get("NO_COLOR", "")).strip()


def parse(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def location_segment(payload: dict[str, Any]) -> str:
    """Where this session lives, written the way a shell prompt writes it."""

    return shorten_path(session_directory(payload))


def session_directory(payload: dict[str, Any]) -> str:
    """The directory the session was started in.

    The runtime reports two directories, and the difference decides whether
    this segment is worth reading. `project_dir` is where the session began and
    stays put; `current_dir` follows the session as it moves. A label that
    changed under you would be answering a question nobody asked -- the point of
    naming the path is to recognise, at a glance, which checkout this window
    belongs to, and that is fixed when the window opens.

    `current_dir` is still the fallback, because a runtime that reports only one
    directory is reporting the one it has.
    """

    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        named = str(workspace.get("project_dir") or workspace.get("current_dir") or "")
        if named:
            return named
    return str(payload.get("cwd") or "")


def shorten_path(directory: str, home: Path | None = None) -> str:
    """`~/git/tao-agent-os/…/gauge` -- the home prefix folded, the middle dropped.

    Two names carry the answer to "where am I": the project and the leaf. What
    sits between them is fixed boilerplate -- every task worktree lives under
    the same `.tao/worktrees` -- so that is what gives way when the line would
    otherwise run past the terminal. The leaf is never truncated, because a
    half-written worktree name is worse than a long one.
    """

    if not directory:
        return ""
    text = _fold_home(directory, home)
    if len(text) <= PATH_LIMIT:
        return text
    parts = text.split("/")
    if len(parts) <= 4:
        return text
    return "/".join([*parts[:3], ELISION, parts[-1]])


def _fold_home(directory: str, home: Path | None = None) -> str:
    try:
        root = str(home or Path.home())
    except (OSError, RuntimeError):
        return directory
    if directory == root:
        return "~"
    if root and directory.startswith(f"{root}/"):
        return f"~{directory[len(root):]}"
    return directory


def run_chained(command: str, payload_text: str) -> str:
    """Give the payload to whatever held this slot and keep what it prints."""

    if not command.strip():
        return ""
    try:
        done = subprocess.run(
            ["/bin/sh", "-c", command],
            input=payload_text,
            capture_output=True,
            text=True,
            timeout=CHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()
