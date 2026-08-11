#!/usr/bin/env python3
"""Codex Stop gate for exact-session Tao Agent OS closeout.

An active run proves that this Codex session started project work and has not
yet passed the provider-neutral finish lifecycle. The first Stop continues the
turn with an actionable closeout request. If the continued turn still has the
same active run, stop it explicitly instead of creating an infinite hook loop.

The gate deliberately does not inspect prompts, transcripts, diffs, or the last
assistant message. Retrospective and reusable-skill decisions remain owned by
the structured finish ledger and its skill follow-up validators.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from agent_project_search import instruction_files, project_markers
    from agent_runtime_session import resolve_runtime_evidence
    from support.global_state import prefer_git_root as _prefer_git_root
    from support.setup_config_files import read_json
    from support.stable_launcher import stable_launcher_path
except ImportError:  # pragma: no cover - only a broken installation reaches this
    instruction_files = None
    project_markers = None
    resolve_runtime_evidence = None
    read_json = None
    stable_launcher_path = None

    def _prefer_git_root(candidates: "list[Path]") -> "Path | None":
        for candidate in candidates:
            if (candidate / ".git").exists():
                return candidate
        return candidates[0] if candidates else None


def _allow() -> int:
    return 0


def _continue_closeout(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def _stop_incomplete(reason: str) -> int:
    print(json.dumps({"continue": False, "stopReason": reason}))
    return 0


def _gate_enabled() -> bool:
    return os.environ.get("TAO_CODEX_STOP_GATE", "").strip() != "0"


def _find_project_root(cwd: Path) -> Path | None:
    if instruction_files is None or project_markers is None:
        return None
    candidates = [
        candidate
        for candidate in (cwd, *cwd.parents)
        if instruction_files(candidate) or project_markers(candidate)
    ]
    return _prefer_git_root(candidates)


def _closeout_reason(root: Path, evidence: Path) -> str:
    preflight = read_json(evidence) if read_json is not None else {}
    rules = Path(str(preflight.get("rules") or root))
    launcher = (
        stable_launcher_path()
        if stable_launcher_path is not None
        else Path("tao-hook")
    )
    return (
        "Tao Agent OS closeout is incomplete for this Codex session. "
        "Complete every missing route gate, review, and verification, then run "
        f"`{launcher} finish --project {root} --rules {rules} --evidence {evidence}`. "
        "Do not call finish while a route gate or fresh user authority is still "
        "pending; continue the task or obtain that authority first, then complete "
        "the work and gate evidence. "
        "If the retrospective outcome is reusable_gap, complete skill-draft, "
        "skill-curate, skill-review, and skill-maintenance in this same closeout "
        "before retrying finish."
    )


def decide(payload: dict) -> int:
    if not _gate_enabled() or resolve_runtime_evidence is None:
        return _allow()
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return _allow()
    try:
        cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
        root = _find_project_root(cwd)
    except (OSError, ValueError):
        return _allow()
    if root is None:
        return _allow()
    evidence = resolve_runtime_evidence(
        root, {"runtime": "codex", "session_id": session_id}
    )
    if evidence is None:
        return _allow()

    reason = _closeout_reason(root, evidence)
    if payload.get("stop_hook_active"):
        return _stop_incomplete(
            "Tao Agent OS closeout is still incomplete after one continuation. "
            "The turn was stopped without reporting completion. " + reason
        )
    return _continue_closeout(reason)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return _allow()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return _allow()
        return decide(payload)
    except Exception:
        return _allow()


if __name__ == "__main__":
    sys.exit(main())
