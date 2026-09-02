#!/usr/bin/env python3
"""The one line Antigravity (AGY) keeps on screen: quota left, and what Tao is doing.

Antigravity renders a status line by running a command on every draw and
printing whatever it writes. The command is handed the session as JSON on
stdin, and that JSON already carries the runtime's own rate limits -- so the
number the operator actually wants is available here and nowhere cheaper.

Two rules shape everything below. The line is drawn constantly, so nothing may
block: every read is guarded and every failure degrades to a shorter line
rather than an error. And the slot is shared, so `--chain` forwards the
untouched payload to whatever held it before and keeps that output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.runtime_quota import SEPARATOR, remaining_summary  # noqa: E402


# Long enough for a local file read behind a cold page cache, short enough that
# a wedged chain target cannot hold the frame. The status line redraws often;
# one slow draw is invisible, a hung one is the whole terminal.
CHAIN_TIMEOUT_SECONDS = 2.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the Tao status line for Antigravity (AGY)."
    )
    parser.add_argument(
        "--chain",
        default="",
        help="shell command that previously held the status line; it is given "
        "the same payload and its output is kept",
    )
    arguments = parser.parse_args(argv)

    payload_text = _read_stdin()
    payload = _parse(payload_text)

    # Tao's own segments are divided the same way the windows inside the quota
    # summary are, so the line reads as one thing. What the chain returns is
    # someone else's text and gets plain space instead: a divider would claim
    # it as part of this layout.
    mine = SEPARATOR.join(
        segment
        for segment in (
            remaining_summary(payload.get("rate_limits")),
            location_segment(payload),
            work_segment(payload),
        )
        if segment
    )
    chained = run_chained(arguments.chain, payload_text)

    line = "  ".join(segment for segment in (mine, chained) if segment)
    if line:
        sys.stdout.write(line)
    return 0


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def _parse(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def location_segment(payload: dict[str, Any]) -> str:
    """`~/git/tao-agent-os` -- where the session is standing, relative to ~ when inside it."""

    workspace = payload.get("workspace")
    named = ""
    if isinstance(workspace, dict):
        named = str(workspace.get("current_dir") or workspace.get("project_dir") or "")
    if not named:
        named = str(payload.get("cwd") or "")
    if not named:
        return ""
    try:
        current = Path(named).expanduser().resolve()
        if not current.exists():
            return ""
        home = Path.home().resolve()
        try:
            rel = current.relative_to(home)
            return f"~/{rel}" if str(rel) != "." else "~"
        except ValueError:
            return str(current)
    except OSError:
        return ""


def work_segment(payload: dict[str, Any]) -> str:
    """`task 14/20` -- the run open in this project, and how far it has to go.

    Silent when no run is open, because a status line that names something on
    every draw stops being read for the times it names something real.
    """

    project = project_root(payload)
    if project is None:
        return ""
    run = open_run(project)
    if run is None:
        return ""
    command = str(run.get("command") or "").strip() or "run"
    progress = gate_progress(project, run)
    return f"{command} {progress}" if progress else command


def project_root(payload: dict[str, Any]) -> Path | None:
    """The Tao project the session is standing in, if it is standing in one."""

    workspace = payload.get("workspace")
    named = ""
    if isinstance(workspace, dict):
        named = str(workspace.get("current_dir") or workspace.get("project_dir") or "")
    if not named:
        named = str(payload.get("cwd") or "")
    if not named:
        return None
    try:
        current = Path(named).expanduser().resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / ".tao").is_dir():
            return candidate
    return None


def open_run(project: Path) -> dict[str, Any] | None:
    """The most recently started run this project still has open."""

    registry = _read_json(project / ".tao" / "run-registry.json")
    runs = registry.get("runs")
    if not isinstance(runs, list):
        return None
    running = [
        run
        for run in runs
        if isinstance(run, dict) and str(run.get("state") or "") == "running"
    ]
    if not running:
        return None
    return max(running, key=lambda run: str(run.get("started_at") or ""))


def gate_progress(project: Path, run: dict[str, Any]) -> str:
    """`14/20`: gates recorded out of the gates this route ends on."""

    ledger = gate_ledger(project, run)
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ""
    recorded = {
        str(entry.get("gate") or "")
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("status") or "") == "SUCCESS"
    }
    recorded.discard("")

    evidence = _read_json(Path(str(ledger.get("preflight_evidence") or "")))
    route = evidence.get("route")
    gates = route.get("gates") if isinstance(route, dict) else None
    if not isinstance(gates, list) or not gates:
        return str(len(recorded)) if recorded else ""
    return f"{len(recorded & set(gates))}/{len(gates)}"


def gate_ledger(project: Path, run: dict[str, Any]) -> dict[str, Any]:
    """This run's gate ledger, or nothing if none of the candidates is its own.

    A ledger sits beside the evidence it is bound to, and evidence lives either
    at `.tao/<name>.json` or under `.tao/evidence/`, so the name alone does not
    say where to look. Rather than guess, every candidate is read and the one
    that names this run's evidence is kept.

    The binding is what makes the count trustworthy. `.tao/gate-evidence.json`
    is tracked, so a fresh worktree starts life holding a finished run's ledger;
    without this check a new run would inherit that run's gates and report
    progress it never made.
    """

    evidence_name = str(run.get("evidence_name") or "").strip()
    if not evidence_name:
        return {}
    stem = Path(evidence_name).stem
    tao = project / ".tao"
    candidates = [
        tao / "evidence" / f"{stem}-gate-evidence.json",
        tao / f"{stem}-gate-evidence.json",
    ]
    if stem == "preflight":
        candidates.append(tao / "gate-evidence.json")
    for candidate in candidates:
        ledger = _read_json(candidate)
        bound = str(ledger.get("preflight_evidence") or "")
        if bound and Path(bound).name == evidence_name:
            return ledger
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    if not str(path) or str(path) == ".":
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


if __name__ == "__main__":
    raise SystemExit(main())
