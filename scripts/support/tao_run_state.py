"""What Tao run is open in a project, read from what is already on disk.

This is the half of the status line that is about Tao rather than about the
runtime: which project the session is standing in, whether a run is open there,
and how far through its route that run has reached.

It is kept apart from the line that displays it for the reason the review gate
named -- reading run state and composing a status line are different jobs -- and
because everything here is useful to anything else that wants to know whether a
run is open, not only to a status line.

Every read is guarded. This runs on every terminal redraw, so a missing or
half-written file has to shorten the line rather than raise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def working_directory(payload: dict[str, Any]) -> str:
    """The directory work is happening in now.

    The runtime reports two: this is the one that follows the session as it
    moves, which is the one the open run belongs to. Where the session *started*
    is what the status line displays, and that is read elsewhere.
    """

    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        named = str(workspace.get("current_dir") or workspace.get("project_dir") or "")
        if named:
            return named
    return str(payload.get("cwd") or "")


def project_root(payload: dict[str, Any]) -> Path | None:
    """The Tao project the session is standing in, if it is standing in one."""

    named = working_directory(payload)
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

    registry = read_json(project / ".tao" / "run-registry.json")
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

    evidence = read_json(Path(str(ledger.get("preflight_evidence") or "")))
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
        ledger = read_json(candidate)
        bound = str(ledger.get("preflight_evidence") or "")
        if bound and Path(bound).name == evidence_name:
            return ledger
    return {}


def read_json(path: Path) -> dict[str, Any]:
    if not str(path) or str(path) == ".":
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
