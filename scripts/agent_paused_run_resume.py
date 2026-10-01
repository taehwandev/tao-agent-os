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
from pathlib import Path

from agent_continuation_resume import resume_last
from agent_runtime_session import rebind_recorded_runtime_session


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
