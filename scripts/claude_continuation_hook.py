#!/usr/bin/env python3
"""Thin Claude lifecycle adapter for Tao continuation checkpoints."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_packet import ContinuationPacketError
from agent_continuation_resume import resume_last
from agent_runtime_session import (
    bind_resumed_runtime_session,
    is_run_local_continuation_evidence,
    resolve_runtime_evidence,
)
from support.global_state import is_project_state_dir


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
OPT_IN_FILES = ("AGENTS.md", "CLAUDE.md", "CODEX.md")

# Continuation storage that cannot exist here yet, as opposed to a packet this
# adapter built wrongly. Blocking an edit is how the protocol stops a mutation
# from running against a checkpoint that claims a pre-mutation state it never
# recorded. That reasoning needs a packet to be stale about; where no packet can
# be written at all there is nothing to protect, and the lifecycle already says
# so out loud rather than failing ("checkpoint: skipped; no packet is
# reachable"). Denying every edit for a setup condition is stricter at the tool
# boundary than the same feature is at its own gates, and it costs the user the
# editor to fix the setup with.
UNAVAILABLE_RULES = frozenset({"not_git_ignored", "local_boundary_unavailable"})


class ClaudeContinuationAdapter:
    """Map Claude session/tool events onto the common continuation contract."""

    @staticmethod
    def pre_mutation(
        payload: dict[str, Any],
        *,
        root: Path,
        cwd: Path,
        session_id: str,
    ) -> str | None:
        evidence = _session_evidence(root, session_id)
        target = _target_path(payload, cwd)
        if evidence is None or target is None:
            return (
                "Tao continuation checkpoint could not bind this edit to an exact "
                "run-local evidence path and declared file."
            )
        try:
            relative = target.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            # Outside the project the packet records nothing: changed scope is
            # project-local by definition, so there is no checkpoint for this
            # edit to contradict. Refusing here blocked every scratch file,
            # runtime config, and sibling checkout an agent legitimately edits
            # while a project run is open -- a scope this adapter never owned.
            return None
        if ".tao" in Path(relative).parts:
            return "Tao continuation checkpoint refuses mutations inside project state."
        kind = (
            "create"
            if payload.get("tool_name") == "Write" and not target.exists()
            else "update"
        )
        return _checkpoint(
            root,
            evidence,
            "pre_mutation",
            mutation={"kind": kind, "paths": [relative]},
        )

    @staticmethod
    def post_mutation(payload: dict[str, Any]) -> str | None:
        """Close the bracket if one is open. Never block: the write already ran.

        This runs after the tool wrote bytes, so refusing here cannot prevent
        anything -- it only reports a mutation that succeeded as failed. The
        protocol's leverage point is the pre-mutation bracket, and its designed
        answer to a checkpoint that never closed is already correct without any
        blocking: the packet keeps the pending record, worktree verification
        fails against it, and resume enters reconciliation instead of calling
        those bytes verified progress.

        There is also no pending to close whenever the pre-mutation side
        legitimately skipped -- an edit outside the project, or storage the
        packet cannot live in. Treating that absence as a failure turned every
        such edit into a reported tool error.
        """
        root = _event_project(payload)
        session_id = str(payload.get("session_id") or "")
        if root is None or not session_id:
            return None
        evidence = _session_evidence(root, session_id)
        if not is_run_local_continuation_evidence(root, evidence):
            return None
        _checkpoint(root, evidence, "post_mutation")
        return None

    @staticmethod
    def session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
        root = _event_project(payload)
        session_id = str(payload.get("session_id") or "")
        if root is None or not session_id:
            return None
        result = resume_last(root)
        if result["result"] == "not_found":
            return None
        if result["result"] != "ready":
            return _context(
                f"Tao continuation was not resumed: {result['result']}. "
                "Resolve the named refusal before continuing this run."
            )
        try:
            bind_resumed_runtime_session(
                project=root,
                evidence_path=Path(result["evidence_path"]),
                run_id=result["run_id"],
                resume_generation=int(result["resume_generation"]),
                runtime="claude",
                session_id=session_id,
            )
        except (OSError, RuntimeError, ValueError):
            return _context(
                "Tao continuation claimed the run but could not bind this exact "
                "Claude session. Resolve the session binding before continuing."
            )
        return _context(_resume_brief(result))

    @staticmethod
    def run(payload: dict[str, Any]) -> dict[str, Any] | None:
        event = str(payload.get("hook_event_name") or "")
        if event == "SessionStart":
            return ClaudeContinuationAdapter.session_start(payload)
        if event in {"PostToolUse", "PostToolUseFailure"}:
            reason = ClaudeContinuationAdapter.post_mutation(payload)
            return {"decision": "block", "reason": reason} if reason else None
        return None


def _checkpoint(
    root: Path,
    evidence: Path,
    kind: str,
    *,
    mutation: dict[str, Any] | None = None,
) -> str | None:
    try:
        binding = json.loads(evidence.read_text(encoding="utf-8"))
        rules = Path(str(binding.get("rules") or root)).resolve()
        write_continuation_checkpoint(
            project=root,
            rules=rules,
            run_id=evidence.parent.name,
            kind=kind,
            binding_path=evidence,
            mutation=mutation,
        )
    except ContinuationPacketError as error:
        rules = [item["rule"] for item in error.failures]
        if all(rule in UNAVAILABLE_RULES for rule in rules):
            return None
        return f"Tao continuation {kind} checkpoint was refused: {', '.join(rules)}."
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        # The binding evidence is missing or unreadable, so no checkpoint exists
        # to be wrong about this mutation. Same class as the rules above.
        return None
    return None


def _session_evidence(root: Path, session_id: str) -> Path | None:
    return resolve_runtime_evidence(
        root, {"runtime": "claude", "session_id": session_id}
    )


# NotebookEdit names its target `notebook_path`; every other edit tool uses
# `file_path`. Reading only the latter makes a notebook edit look like a
# mutation with no declared file, which this adapter refuses.
TARGET_KEYS = ("file_path", "notebook_path")


def _target_path(payload: dict[str, Any], cwd: Path) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = next(
        (tool_input[key] for key in TARGET_KEYS if isinstance(tool_input.get(key), str)),
        None,
    )
    if not isinstance(raw, str) or not raw.strip():
        return None
    target = Path(raw)
    return target if target.is_absolute() else cwd / target


def _event_project(payload: dict[str, Any]) -> Path | None:
    try:
        cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
    except OSError:
        return None
    target = _target_path(payload, cwd)
    for start in (target.parent if target is not None else cwd, cwd):
        for candidate in (start, *start.parents):
            if _opts_in(candidate):
                return candidate
    return None


def _opts_in(path: Path) -> bool:
    if is_project_state_dir(path / ".tao"):
        return True
    for name in OPT_IN_FILES:
        try:
            head = (path / name).read_text(encoding="utf-8", errors="ignore")[:8192]
        except OSError:
            continue
        if "tao" in head.lower():
            return True
    return False


def _resume_brief(result: dict[str, Any]) -> str:
    work = result.get("work") or {}
    reuse = result.get("reuse") or {}
    lines = [
        "Tao continuation resumed this unfinished project-local run.",
        f"Objective: {work.get('objective', '')}",
        f"First unfinished checkpoint: {result.get('checkpoint') or 'unknown'}",
    ]
    lines.extend(
        f"Decision [{item.get('status')}]: {item.get('text')}"
        for item in work.get("decisions") or []
    )
    lines.extend(
        f"Remaining [{item.get('checkpoint')}]: {item.get('action')}"
        for item in work.get("remaining_work") or []
    )
    lines.extend(f"Blocker: {item}" for item in work.get("blockers") or [])
    if reuse.get("decision") == "reuse_unchanged_evidence":
        accepted = reuse.get("accepted_decisions") or []
        successful = reuse.get("successful_verification") or []
        lines.extend(
            [
                f"Reuse [{reuse['decision']}]: required_docs={reuse.get('required_docs')}; "
                f"inspected_scope_count={reuse.get('inspected_scope_count')}; "
                f"accepted_decisions={len(accepted)}; successful_checks={len(successful)}.",
                "Recorded analysis, accepted decisions, and successful checks are reusable; "
                "do not rerun identical checks merely to rebuild context.",
                "Rerun evidence only when: "
                + ", ".join(item.replace("_", " ") for item in reuse.get("rerun_when") or []),
            ]
        )
        if reuse.get("required_docs") == "reuse":
            lines.append("Unchanged required docs are reusable.")
        elif reuse.get("required_docs") == "not_recorded":
            lines.append("Required-doc reading is not recorded reusable; complete that gate before continuing.")
        inspected = work.get("inspected_scope") or []
        lines.extend(
            f"Inspected [{item.get('role')}]: "
            f"{item.get('path') or item.get('to') or item.get('from')}"
            for item in inspected[:8]
        )
        lines.extend(
            f"Accepted [{item.get('status')}]: {item.get('id')}"
            for item in accepted[:8]
        )
        lines.extend(
            f"Verified [{item.get('kind')}]: {item.get('id')}"
            for item in successful[:8]
        )
        omitted = len(inspected) - 8
        if omitted > 0:
            lines.append(f"Inspected: {omitted} additional bounded records omitted.")
        omitted = len(accepted) - 8
        if omitted > 0:
            lines.append(f"Accepted: {omitted} additional accepted records omitted.")
        omitted = len(successful) - 8
        if omitted > 0:
            lines.append(f"Verified: {omitted} additional successful records omitted.")
    return "\n".join(lines)


def _context(text: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }


def _main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            return 0
        output = ClaudeContinuationAdapter.run(payload)
        if output is not None:
            print(json.dumps(output, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
