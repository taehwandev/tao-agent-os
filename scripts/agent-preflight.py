#!/usr/bin/env python3
"""Create executable preflight evidence for Tao Agent OS tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule import create_preflight_snapshot
from agent_execution_capsule_state import atomic_write_json
from agent_route_state import request_fingerprint
from agent_global_lessons import lesson_summary
from agent_runtime_session import runtime_session
from agent_hook_gate_records import reset_and_record_preflight_gate
from agent_preflight_runtime import (
    active_runtime_label,
    agy_runtime_bridge_issue,
    check_agent_hooks,
)
from agent_preflight_spill import write_spill_label
from agent_vibeguard_cache import cached_vibeguard, skipped_vibeguard
from agent_worker_evidence import (
    claim_worker_reservation,
    worker_reservation_matches,
)
from agent_workspace_policy import is_git_status_review_only, non_git_writing_workspace_note
from support.global_state import project_scoped_state_error
from workflow_catalog import COMMANDS, CONCERNS, PLATFORM_CONCERNS, PLATFORMS
from workflow_common import unique
from workflow_doc_surfaces import extract_request_surface_paths, git_status_surface_paths
from workflow_classified_exemption import (
    classified_intake_decision,
    parent_evidence_path,
)
from workflow_intent_dual_run import route_intake_decision
from workflow_intent_envelope import read_approval_record, read_intent_envelope
from workflow_request import infer_concerns_from_request
from workflow_route import resolve_docs


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def clean_output(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "stdout": clean_output(result.stdout),
        "stderr": clean_output(result.stderr),
    }


def vibeguard_command(project: Path, rules: Path) -> list[str]:
    binary = shutil.which("vibeguard")
    if binary:
        return [binary, "audit", str(project), "--rules", str(rules)]
    return [
        "npx",
        "--yes",
        "@taehwandev/vibeguard",
        "audit",
        str(project),
        "--rules",
        str(rules),
    ]


def parse_overall(output: str) -> dict[str, str]:
    for raw_line in clean_output(output).splitlines():
        line = raw_line.strip()
        if not line.startswith("Overall:"):
            continue
        value = line.split("Overall:", 1)[1].strip()
        if "Ready" in value:
            status = "Ready"
        elif "Needs review" in value:
            status = "Needs review"
        elif "Blocked" in value:
            status = "Blocked"
        else:
            status = value or "unknown"
        return {"status": status, "line": line}
    return {"status": "unknown", "line": ""}


def route_command(args: argparse.Namespace, tao_root: Path) -> list[str]:
    command = [
        "python3",
        str(tao_root / "scripts" / "workflow.py"),
        "route",
        args.command,
        "--format",
        "json",
        "--project",
        str(args.project.resolve()),
    ]
    if args.request_classified:
        command.extend(["--request-classified", "--classification-evidence", args.classification_evidence])
        if args.request:
            command.extend(["--request", args.request])
    else:
        command.extend(["--request", args.request])
    continuation_scope = getattr(args, "continuation_scope", "")
    if continuation_scope:
        command.extend(["--continuation-scope", continuation_scope])
    intent_envelope = getattr(args, "intent_envelope", "")
    if intent_envelope:
        command.extend(["--intent-envelope", intent_envelope])
    approval_record = getattr(args, "approval_record", "")
    if approval_record:
        command.extend(["--approval-record", approval_record])
    runtime_session_id = getattr(args, "runtime_session_id", "")
    if runtime_session_id:
        command.extend(["--runtime-session-id", runtime_session_id])
    if getattr(args, "parent_evidence", None):
        command.extend(["--parent-evidence", str(args.parent_evidence)])
    for platform in args.platform:
        command.extend(["--platform", platform])
    for concern in args.concern:
        command.extend(["--concern", concern])
    for path in args.surface_path:
        command.extend(["--surface-path", path])
    return command


def route_result(
    args: argparse.Namespace,
    tao_root: Path,
    project: Path,
    git_status: dict[str, Any],
) -> dict[str, Any]:
    command = route_command(args, tao_root)
    try:
        route, error, returncode = route_payload(args, git_status)
    except Exception as error:
        return {
            "command": command,
            "cwd": str(project),
            "returncode": 1,
            "stdout": "",
            "stderr": f"{error.__class__.__name__}: {error}",
            "in_process": True,
        }
    return {
        "command": command,
        "cwd": str(project),
        "returncode": returncode,
        "stdout": json.dumps(route, indent=2, sort_keys=True) if route else "",
        "stderr": error,
        "in_process": True,
    }


def route_payload(
    args: argparse.Namespace,
    git_status: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str, int]:
    if args.request_classified and not args.classification_evidence:
        return (
            None,
            "Route --request-classified requires --classification-evidence so request intake cannot be skipped silently.",
            2,
        )
    project_root = args.project.expanduser().resolve()
    request_classification, failures = route_intake_decision(
        args.command,
        read_intent_envelope(getattr(args, "intent_envelope", "")),
        approval=read_approval_record(getattr(args, "approval_record", "")),
        request_fingerprint=request_fingerprint(request_intake(args)),
        runtime_session_id=str(getattr(args, "runtime_session_id", "") or ""),
    )
    if failures:
        return None, "\n".join(failures), 2
    if request_classification is None:
        # A capsule may reuse prior intake only after the envelope boundary has
        # allowed this route. Question-resolution routes are the sole no-envelope
        # path and still use the established classification rules.
        request_classification, block_reason = classified_intake_decision(
            args.command,
            args.request,
            args.request_classified,
            args.classification_evidence or "",
            getattr(args, "continuation_scope", ""),
            project=project_root,
            rules=getattr(args, "rules", None),
            parent_evidence=parent_evidence_path(
                project_root, getattr(args, "parent_evidence", None)
            ),
        )
        if block_reason:
            stderr = block_reason
            if request_classification:
                stderr += (
                    "\nClassification: "
                    f"{request_classification['clarity']} / "
                    f"response_mode: {request_classification['response_mode']} / "
                    f"grill_me: {str(request_classification['grill_me']).lower()}"
                )
            return None, stderr, 2

    intent_text = args.request or args.classification_evidence or ""
    inferred_concerns = infer_concerns_from_request(intent_text)
    if args.request_classified and args.classification_evidence and args.request:
        # Classification evidence describes the resolved scope, and it used to be
        # the only intent text available. Now that a request is always required
        # alongside the flag, keep inferring concerns from the evidence too so a
        # scope named only there does not silently drop its route concern.
        inferred_concerns = unique(
            [*inferred_concerns, *infer_concerns_from_request(args.classification_evidence)]
        )
    concerns = unique([*args.concern, *inferred_concerns])
    newly_inferred = [concern for concern in inferred_concerns if concern not in args.concern]
    surface_paths = unique(args.surface_path)
    surface_candidates = {
        "request_paths": [
            path
            for path in extract_request_surface_paths(intent_text)
            if path not in surface_paths
        ],
        "dirty_paths": [
            path
            for path in git_status_surface_paths((git_status or {}).get("stdout", ""))
            if path not in surface_paths
        ],
    }
    route = resolve_docs(
        args.command,
        args.platform[-1] if args.platform else None,
        concerns,
        request_classification=request_classification,
        request_classified=args.request_classified,
        classification_evidence=args.classification_evidence or "",
        request_text=intent_text,
        surface_paths=surface_paths,
        project_root=args.project.resolve(),
    )
    if newly_inferred:
        route["inferred_concerns"] = newly_inferred
        notes = route.get("notes")
        if isinstance(notes, list):
            joined = ", ".join(f"`{concern}`" for concern in newly_inferred)
            notes.append(f"Inferred concern(s) from request keywords: {joined}.")
    if any(surface_candidates.values()):
        route["surface_candidates"] = surface_candidates
        notes = route.get("notes")
        if isinstance(notes, list):
            notes.append(
                "Request and dirty paths are discovery candidates only. Verify the change "
                "owner before passing a path through --surface-path."
            )
    return route, "", 1 if route["missing"] or route.get("blocking") else 0


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def build_parser(tao_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run route, git status, and VibeGuard before agent work."
    )
    parser.add_argument("--command", required=True, choices=sorted(COMMANDS), help="workflow.py route command")
    parser.add_argument("--request", help="current user request")
    parser.add_argument(
        "--intent-envelope",
        default="",
        help=(
            "runtime intent envelope as JSON or a path to it; when supplied it "
            "is the authority for intent, target and effect"
        ),
    )
    parser.add_argument(
        "--approval-record",
        "--user-approval",
        dest="approval_record",
        default="",
        help=(
            "separate bound user-approval record as JSON or a path; "
            "--user-approval is a compatibility alias; required when the "
            "effective route reaches git_write or above"
        ),
    )
    parser.add_argument(
        "--runtime-session-id",
        default="",
        help="current opaque runtime session id that must match the intent envelope",
    )
    parser.add_argument(
        "--continuation-scope",
        default="",
        help=(
            "bounded prior scope for a terse follow-up; supplies target identity "
            "without changing current-request question, action, or risk signals"
        ),
    )
    parser.add_argument(
        "--request-classified",
        action="store_true",
        help=(
            "delegated-worker only: reuse request intake from a ready, valid, "
            "matching parent capsule; also pass the exact bound --request"
        ),
    )
    parser.add_argument(
        "--classification-evidence",
        help=(
            "required with --request-classified; describes the matching parent's "
            "resolved classification or answer-first handling"
        ),
    )
    parser.add_argument("--platform", action="append", choices=sorted(PLATFORMS), default=[])
    parser.add_argument(
        "--surface-path",
        action="append",
        default=[],
        help=(
            "repository-verified change-owner path; can be repeated. Request and "
            "dirty paths remain candidates until owner proof is recorded"
        ),
    )
    parser.add_argument(
        "--concern",
        action="append",
        choices=sorted(set(CONCERNS) | {key[1] for key in PLATFORM_CONCERNS}),
        default=[],
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--rules", type=Path, default=tao_root)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="declare a non-mutating analysis run and skip VibeGuard audits",
    )
    parser.add_argument(
        "--parent-evidence",
        type=Path,
        help=(
            "parent preflight evidence whose execution capsule may honor "
            "--request-classified; defaults to <project>/.tao/preflight.json"
        ),
    )
    parser.add_argument(
        "--worker-reservation-token",
        default="",
        help="opaque token issued by the parent handoff for this worker evidence path",
    )
    return parser


def resolve_evidence_path(args: argparse.Namespace, project: Path) -> Path:
    _enforce_worker_environment(args)
    # Project-scoped state must land in a project. Silently creating it
    # elsewhere is what put a 54 KB preflight.json in the global ~/.tao and left
    # the Stop gate demanding a finish for $HOME. A missing .tao is fine -- a
    # fresh repo has none yet; only the global install directory is refused.
    scope_error = project_scoped_state_error(project)
    if scope_error:
        raise ValueError(scope_error)
    if not args.evidence:
        return project / ".tao" / "preflight.json"
    requested = args.evidence.expanduser().absolute()
    worker_root = project / ".tao" / "workers"
    lexical_worker_root = args.project.expanduser().absolute() / ".tao" / "workers"
    try:
        try:
            relative = requested.relative_to(worker_root)
        except ValueError:
            relative = requested.relative_to(lexical_worker_root)
    except ValueError:
        if args.worker_reservation_token:
            raise ValueError(
                "worker reservation tokens are valid only under the project worker evidence root"
            )
        return requested.resolve()
    requested = worker_root / relative
    if len(relative.parts) != 2 or relative.parts[-1] != "preflight.json":
        raise ValueError(
            "worker evidence must use one reserved worker directory and preflight.json"
        )
    if worker_root.resolve() != worker_root:
        raise ValueError("worker evidence root must not resolve through a symlink")
    if not requested.parent.is_dir() or requested.parent.resolve() != requested.parent:
        raise ValueError(
            "worker evidence directory must already be exclusively reserved and must not be a symlink"
        )
    if not args.worker_reservation_token:
        raise ValueError(
            "worker evidence requires a single-use worker reservation token"
        )
    if not worker_reservation_matches(
        requested.parent,
        args.worker_reservation_token,
    ):
        raise ValueError(
            "worker reservation token does not match this evidence path"
        )
    return requested


def claim_worker_evidence_reservation(
    args: argparse.Namespace,
    evidence_path: Path,
    project: Path,
) -> None:
    if not args.worker_reservation_token:
        return
    worker_root = project / ".tao" / "workers"
    try:
        evidence_path.relative_to(worker_root)
    except ValueError:
        return
    if not claim_worker_reservation(
        evidence_path.parent,
        args.worker_reservation_token,
    ):
        raise ValueError(
            "worker reservation token was already claimed or does not match this evidence path"
        )


def _enforce_worker_environment(args: argparse.Namespace) -> None:
    enforcement = os.environ.get("TAO_CAPABILITY_ENFORCEMENT", "")
    if os.environ.get("TAO_PARENT_EVIDENCE_READONLY") == "1":
        if enforcement != "parent-evidence-readonly":
            raise ValueError("reusable worker is missing parent-evidence-readonly enforcement")
        raise ValueError(
            "this worker received a reusable parent capsule and cannot create or overwrite parent evidence"
        )
    expected = os.environ.get("TAO_WORKER_EVIDENCE")
    if not expected:
        if enforcement and enforcement != "worker-evidence-and-state":
            raise ValueError("worker capability enforcement scope is unsupported")
        return
    if enforcement != "worker-evidence-and-state":
        raise ValueError("isolated worker is missing worker-evidence-and-state enforcement")
    expected_path = Path(expected).expanduser().resolve()
    actual = args.evidence.expanduser().resolve() if args.evidence else None
    if actual != expected_path:
        raise ValueError("worker start must use the launcher-issued isolated evidence path")
    expected_token = os.environ.get("TAO_WORKER_RESERVATION_TOKEN", "")
    if not expected_token or args.worker_reservation_token != expected_token:
        raise ValueError("worker start must use the launcher-issued single-use reservation token")


def request_intake(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "request": args.request or "",
        "continuation_scope": getattr(args, "continuation_scope", "") or "",
        "request_classified": args.request_classified,
        "classification_evidence": args.classification_evidence or "",
    }


def write_early_bridge_failure(
    args: argparse.Namespace,
    tao_root: Path,
    project: Path,
    rules: Path,
    evidence_path: Path,
    failure: str,
) -> int:
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tao_root": str(tao_root),
        "project": str(project),
        "rules": str(rules),
        "request_intake": request_intake(args),
        "early_runtime_bridge_failure": failure,
    }
    write_json(evidence_path, evidence)
    print(f"Preflight evidence: {evidence_path}")
    if not runtime_session():
        # Silently writing an empty session leaves the Claude gate denying every
        # edit later, far from the cause. Say it here, where start can be rerun.
        print(
            "WARNING: no runtime session id in this environment; the Claude edit gate "
            "will deny edits until start runs with CLAUDE_CODE_SESSION_ID set.",
            file=sys.stderr,
        )
    print(f"FAIL: {failure}", file=sys.stderr)
    return 1


def parse_route_payload(route_result: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if route_result["returncode"] != 0:
        return None, ""
    try:
        return json.loads(route_result["stdout"]), ""
    except json.JSONDecodeError as error:
        return None, str(error)


def collect_failures(
    route_result: dict[str, Any],
    route_payload: dict[str, Any] | None,
    route_parse_error: str,
    git_status: dict[str, Any],
    vibeguard: dict[str, Any],
    hook_failures: list[str],
) -> list[str]:
    failures: list[str] = []
    if route_result["returncode"] != 0:
        route_reason = " ".join(
            (route_result.get("stdout", "") + " " + route_result.get("stderr", "")).split()
        )
        failures.append(
            "workflow route failed" + (f": {route_reason[:400]}" if route_reason else "")
        )
    elif route_parse_error:
        failures.append("workflow route output was not valid JSON")
    elif route_payload and route_payload.get("missing"):
        failures.append("workflow route reported missing documents")
    if git_status["returncode"] != 0 and not git_status.get("review_only"):
        failures.append("git status failed")
    if vibeguard["returncode"] != 0:
        failures.append("VibeGuard audit failed")
    failures.extend(hook_failures)
    return failures


def effective_read_only(command: str, requested: bool) -> bool:
    return requested or command == "analysis"


def run_preflight(args: argparse.Namespace, tao_root: Path) -> int:
    project = args.project.resolve()
    rules = args.rules.resolve()
    evidence_path = resolve_evidence_path(args, project)
    read_only = effective_read_only(args.command, args.read_only)

    early_bridge_failure = ""
    if active_runtime_label() == "antigravity":
        early_bridge_failure = agy_runtime_bridge_issue(tao_root)
    if early_bridge_failure:
        return write_early_bridge_failure(
            args,
            tao_root,
            project,
            rules,
            evidence_path,
            early_bridge_failure,
        )

    git_status = run_command(["git", "status", "--short", "--untracked-files=all"], project)
    if is_git_status_review_only(project, git_status):
        git_status["review_only"] = True
        git_status["review_note"] = non_git_writing_workspace_note(project)
    route_result_payload = route_result(args, tao_root, project, git_status)
    route_payload, route_parse_error = parse_route_payload(route_result_payload)
    if route_result_payload["returncode"] == 0:
        claim_worker_evidence_reservation(args, evidence_path, project)
    vibeguard = (
        skipped_vibeguard(project)
        if read_only
        else cached_vibeguard(
            project=project,
            rules=rules,
            run_command=run_command,
            vibeguard_command=vibeguard_command,
            parse_overall=parse_overall,
            git_status_result=git_status,
        )
    )
    global_lessons = lesson_summary()

    write_json(evidence_path, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tao_root": str(tao_root),
        "project": str(project),
        "rules": str(rules),
        "request_intake": request_intake(args),
        "execution_mode": {"read_only": read_only},
        "route": route_payload,
        "route_parse_error": route_parse_error,
        "route_command": route_result_payload,
        "git_status": git_status,
        "vibeguard": vibeguard,
        "global_lessons": global_lessons,
        "runtime_session": runtime_session(),
    })
    hook_warnings, hook_failures = check_agent_hooks(tao_root)
    failures = collect_failures(
        route_result_payload,
        route_payload,
        route_parse_error,
        git_status,
        vibeguard,
        hook_failures,
    )
    if not failures and route_payload:
        try:
            preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
            preflight["execution_snapshot"] = create_preflight_snapshot(
                rules,
                route_payload,
                preflight.get("request_intake") or {},
            )
            write_json(evidence_path, preflight)
            reset_and_record_preflight_gate(evidence_path, preflight)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"preflight gate ledger initialization failed: {error}")

    print(f"Preflight evidence: {evidence_path}")
    if not runtime_session():
        # Silently writing an empty session leaves the Claude gate denying every
        # edit later, far from the cause. Say it here, where start can be rerun.
        print(
            "WARNING: no runtime session id in this environment; the Claude edit gate "
            "will deny edits until start runs with CLAUDE_CODE_SESSION_ID set.",
            file=sys.stderr,
        )
    if route_payload:
        print(f"Route: {route_payload.get('command')} gates={route_payload.get('gates')}")
    print(f"VibeGuard overall: {vibeguard['overall']['status']}")
    print(
        "Global lessons: "
        f"accepted={len(global_lessons['accepted'])} "
        f"promoted={len(global_lessons['promoted'])} "
        f"candidates={global_lessons['candidate_count']}"
    )
    for warning in hook_warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    write_spill_label("analysis", "classify")
    tao_root = Path(__file__).resolve().parents[1]
    parser = build_parser(tao_root)
    args = parser.parse_args()
    if args.request_classified and not args.classification_evidence:
        parser.error(
            "--request-classified requires --classification-evidence so request "
            "intake cannot be skipped silently"
        )
    if not args.request:
        parser.error("preflight requires --request with the real current request")
    try:
        return run_preflight(args, tao_root)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
