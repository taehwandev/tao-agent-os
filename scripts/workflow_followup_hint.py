"""Tell a follow-up turn that this session's last run is already finished.

Owner: the one-line follow-up hint the prompt advisory adds.
Allowed imports: the standard library, claude_stop_gate.session_projects,
agent_runtime_session (lazily), support.stable_launcher.
Forbidden imports: claude_pretool_gate; this only reads run state and never
admits, denies or records anything.
Callers/tests: workflow._print_advisory_once; tests/test_workflow_followup_hint.py.
Verification: that test module.

A week of Claude transcripts showed most run-less write denials came after a
finish: 74 on the user's next turn, when the agent went straight to an edit,
commit or merge as if the finished run were still open. The gate refuses that
correctly -- a finished run admits no new action -- but only after the attempt.
Saying it when the turn begins, with the run id `--continue-from` needs, lets
the start come first.
"""

from __future__ import annotations

from pathlib import Path

# A paused run is resumed, not continued from; the gate already says so.
PAUSED = frozenset({"interrupted", "blocked"})


def followup_hint(session_id: str, cwd_root: Path | None, runtime: str = "claude") -> str:
    """One line when the session's latest run is finished and none is open."""

    if not session_id:
        return ""
    from claude_stop_gate import session_projects

    roots = [root for root in session_projects(session_id, cwd_root) if root.is_dir()]
    if not roots:
        return ""
    try:
        import agent_runtime_session as runs
    except ImportError:  # pragma: no cover - broken install stays silent
        return ""
    identity = {"runtime": runtime, "session_id": session_id}
    finished: list[tuple[float, Path, Path]] = []
    for root in roots:
        try:
            if runs.resolve_runtime_evidence(root, identity) is not None:
                return ""
            if runs.resolve_runtime_evidence(
                root, identity, PAUSED, latest_of_several=True
            ) is not None:
                return ""
            evidence = runs.resolve_runtime_evidence(
                root, identity, frozenset({"completed"}), latest_of_several=True
            )
        except (OSError, ValueError, RuntimeError):
            continue
        if evidence is not None:
            try:
                finished.append((evidence.stat().st_mtime, root, evidence))
            except OSError:
                continue
    if not finished:
        return ""
    _mtime, root, evidence = max(finished)
    run_id = evidence.parent.name
    from support.stable_launcher import stable_launcher_path

    return (
        f"Tao lifecycle: this session's last run {run_id} in {root} is finished and "
        "admits no new edit, commit, merge or push. If this request writes, first run "
        f"`{stable_launcher_path()} start --project <project> --rules <TAO_ROOT> "
        f"--command <route> --request \"<this request>\" --continue-from {run_id}` "
        "(with --approved-effect when the request authorizes git_write or more). "
        "A read-only answer needs no start."
    )
