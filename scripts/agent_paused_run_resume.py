"""Resume a session's own paused run when that same session needs it again.

The Stop hook pauses an open run at every turn boundary. The same session then
continuing its own task is the ordinary case, not an interruption, and making
it run `resume` by hand before each turn's first edit only stalled the work.
This takes the exact path `resume --last --run-id` takes -- the claim keeps its
generation check, so another session's live run is still refused -- and then
re-stamps the binding the evidence already records, as that hook does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_continuation_resume import resume_last
from agent_runtime_session import (
    rebind_recorded_runtime_session,
    resolve_runtime_evidence,
    runtime_session,
)


def resume_own_paused_run(project: Path, evidence: Path) -> dict:
    """Claim the paused run behind ``evidence``; return the resume result.

    ``result`` is ``ready`` only when the run was claimed and rebound. Every
    other value is the claim's own refusal (drift, a live owner, a missing
    packet), which the caller reports instead of resuming silently.
    """

    try:
        rules = json.loads(evidence.read_text(encoding="utf-8")).get("rules")
    except (OSError, ValueError):
        return {"result": "unreadable_evidence"}
    result = resume_last(
        project,
        run_id=evidence.parent.name,
        rules=Path(rules) if rules else None,
    )
    if result.get("result") != "ready":
        return result
    try:
        rebound = rebind_recorded_runtime_session(
            project=project,
            evidence_path=Path(result["evidence_path"]),
            run_id=result["run_id"],
            resume_generation=int(result["resume_generation"]),
        )
    except (OSError, RuntimeError, ValueError, KeyError):
        rebound = False
    return result if rebound else {**result, "result": "runtime_binding_refused"}


# The states a turn boundary leaves an open run in. `failed` is not here: it
# stays writable so its owner can record the missing gates and rerun finish.
PAUSED_RUN_STATES = frozenset({"interrupted", "blocked"})


def resume_session_paused_run(project: Path, evidence: Path | None) -> tuple[Path | None, str]:
    """Reclaim this session's paused run before a hook writes its ledger.

    The Stop hook pauses the run at every turn end, and a gate record, review
    or finish in the next turn was then refused as "not writable by the
    caller" until the agent ran `resume` by hand. Returns the resumed evidence
    path and a line to report, or ``(None, reason)``. Nothing is resumed for a
    worker, while the session already holds an active run, or when an explicit
    ``evidence`` names a different run.
    """

    if os.environ.get("TAO_WORKER_EVIDENCE") or os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        return None, ""
    session = runtime_session()
    if not session:
        return None, ""
    try:
        if resolve_runtime_evidence(project, session) is not None:
            return None, ""
        paused = resolve_runtime_evidence(
            project, session, PAUSED_RUN_STATES, latest_of_several=True
        )
    except (OSError, RuntimeError, ValueError):
        return None, ""
    if paused is None:
        return None, ""
    if evidence is not None and evidence.resolve() != paused.resolve():
        return None, ""
    run_id = paused.parent.name
    result = resume_own_paused_run(project, paused)
    if result.get("result") != "ready":
        signals = ", ".join(result.get("changed_signals") or [])
        reason = str(result.get("result") or "refused") + (f" (changed: {signals})" if signals else "")
        return None, f"paused run {run_id} was not resumed: {reason}"
    return Path(result["evidence_path"]), f"resumed this session's paused run {run_id}"
