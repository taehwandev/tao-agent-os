"""Find the directory a Codex Bash call actually runs in.

Owner: the Codex half of the pretool gate's cwd. Allowed imports: the standard
library only. Callers/tests: `claude_pretool_gate.decide`;
`tests/test_codex_exec_workdir.py`.

Codex's PreToolUse payload carries the session cwd and `tool_input.command`,
never the `workdir` the call names. Verified 2026-10-02 against codex-cli
0.160.0. A session started in a main checkout that ran `pwd` with workdir set
to a task worktree reached the hook with `cwd` still the main checkout. Every
command an agent correctly ran in its worktree was therefore judged as a
command in the protected checkout. That cost each Codex task blocked calls,
operator questions and retries.

The call is already in the transcript when the hook runs, as the
`exec_command({cmd, workdir})` the model emitted. That workdir is where Codex
executes the command, so judging there describes the real effect rather than
widening it. Anything uncertain falls back to the payload cwd, which is the
behaviour this module replaced:
- the transcript cannot be read;
- the latest call does not name this command;
- one call names this command with two different workdirs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# The current call is the newest record; a long JS batch still fits well inside.
TAIL_BYTES = 512 * 1024
_CALL_KINDS = ('"custom_tool_call"', '"function_call"')
_JS_STRING = r'"((?:[^"\\]|\\.)*)"'
_CMD = re.compile(r'(?:\bcmd|"cmd")\s*:\s*' + _JS_STRING)
_WORKDIR = re.compile(r'(?:\bworkdir|"workdir")\s*:\s*' + _JS_STRING)


def exec_workdir(payload: dict) -> str | None:
    """The workdir the transcript records for this exact command, or None."""

    command = (payload.get("tool_input") or {}).get("command")
    transcript = payload.get("transcript_path")
    if not isinstance(command, str) or not command or not isinstance(transcript, str):
        return None
    record = _latest_call(Path(transcript))
    if record is None:
        return None
    workdirs = {workdir for cmd, workdir in _exec_calls(record) if cmd == command}
    if len(workdirs) != 1:
        return None
    workdir = workdirs.pop()
    return workdir if workdir and Path(workdir).is_absolute() and Path(workdir).is_dir() else None


def _latest_call(transcript: Path) -> dict | None:
    try:
        with transcript.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if not any(kind in line for kind in _CALL_KINDS):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            # The first line of the tail may be cut; an earlier call is not this one.
            return None
        payload = row.get("payload")
        return payload if isinstance(payload, dict) else None
    return None


def _exec_calls(record: dict) -> list[tuple[str, str | None]]:
    """(cmd, workdir) for every exec in the call, in either Codex tool shape."""

    if record.get("type") == "function_call":
        try:
            arguments = json.loads(str(record.get("arguments") or ""))
        except ValueError:
            return []
        if not isinstance(arguments, dict) or not isinstance(arguments.get("cmd"), str):
            return []
        workdir = arguments.get("workdir")
        return [(arguments["cmd"], workdir if isinstance(workdir, str) else None)]
    calls = []
    code = str(record.get("input") or "")
    for chunk in code.split("exec_command(")[1:]:
        # A chunk ends where the next exec begins; its first cmd/workdir belong to it.
        cmd = _CMD.search(chunk)
        if not cmd:
            continue
        workdir = _WORKDIR.search(chunk)
        decoded = _decode(cmd.group(1))
        if decoded is not None:
            calls.append((decoded, _decode(workdir.group(1)) if workdir else None))
    return calls


def _decode(literal: str) -> str | None:
    try:
        return json.loads(f'"{literal}"')
    except ValueError:
        return None
