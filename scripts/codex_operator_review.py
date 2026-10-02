"""Scoped operator decisions attested by the Codex conversation runtime.

The hook never approves its own request. The runtime records an explicit user
answer separately; this store binds that attestation, it does not infer consent.
No prompts, commands, edit contents or answers are persisted. Standing consent
requires the separate always choice and can be revoked explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from agent_state_lock import state_lock
from support.global_state import global_state_dir


def _policy_signature(payload: dict) -> str:
    scripts = Path(__file__).parent
    paths = {scripts / name for name in (
        "codex_operator_review.py", "claude_pretool_gate.py",
        "claude_worktree_gate.py", "claude_command_effect.py", "claude_bash_readonly.py",
        "claude_bash_inspection.py")}
    bases = [Path(str(payload.get("cwd") or ".")).resolve()]
    body = payload.get("tool_input")
    if isinstance(body, dict):
        target = body.get("file_path") or body.get("notebook_path")
        if isinstance(target, str):
            target_path = Path(target)
            bases.append((target_path if target_path.is_absolute() else bases[0] / target_path).parent)
    for base in bases:
        for parent in (base, *base.parents):
            paths.update(parent / name for name in (
                "AGENTS.md", ".agents/AGENTS.md", ".agents/shared/worktree-policy.json"))
            if (parent / ".git").exists():
                break
    signature = [(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
                 for path in sorted(paths) if path.is_file()]
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def _question(request_id: str, reason: str, code: str) -> str:
    """Supply request-specific facts; the Codex session bridge owns procedure."""
    recovery = ""
    if code == "unreadable_command_effect" and "use one literal command" in reason:
        recovery = "Lookup composition: apply Codex session recovery before asking. "
    return recovery + (
        f"Tao operator decision required ({code}); follow Codex session instructions. "
        "Ask the user only if a decision remains. Record an explicit answer with "
        f"<TAO_LAUNCHER> operator-review --request-id {request_id} "
        "--decision approve|always|reject."
    )


def _invocation(payload: dict) -> dict:
    invocation = {key: payload.get(key) for key in ("session_id", "cwd", "tool_name", "tool_input")}
    # These shell transport settings change when/how much output is returned,
    # never the command, target, sandbox or process lifetime. Other tools may
    # give similarly named fields different meanings and retain exact inputs.
    if invocation["tool_name"] in {"Bash", "exec_command"} and isinstance(invocation["tool_input"], dict):
        invocation["tool_input"] = {key: value for key, value in invocation["tool_input"].items()
                                    if key not in {"yield_time_ms", "max_output_tokens"}}
    return invocation


def _lookup_recovery(payload: dict, reason: str, code: str) -> str:
    if code != "unreadable_command_effect" or "use one literal command" not in reason:
        return ""
    from claude_bash_readonly import simple_command_kind
    from claude_bash_syntax import bash_invocation, command_segments, unmodelled_operator
    from claude_local_context_commands import spill_label_kind
    cwd, tokens, _ = bash_invocation(payload, Path(str(payload.get("cwd") or ".")))
    segments = command_segments(tokens)
    if (unmodelled_operator(tokens) or not segments or len(segments) < 2
            or any(token in {"|", "||", "&", "<", ">", ">>", "<<", "<&", ">&"} for token in tokens)):
        return ""
    if not all(simple_command_kind(command, cwd) == "read_only" or
               (command[0] == "node" and spill_label_kind(command[1:]) is not None)
               for command in segments):
        return ""
    return (
        "No new operator decision is needed: submit separate, independently gated tool calls. "
        "Follow Codex session lookup recovery; do not retry the rejected bundle."
    )


class OperatorReview:
    CODES = frozenset({"ticketed_product_branch", "unreadable_command_effect", "paused_run_refused"})
    MAX_AGE = 900

    @staticmethod
    def _path(request_id: str) -> Path:
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{64}", request_id):
            raise ValueError("invalid operator request id")
        return global_state_dir() / "codex-operator-review" / (request_id + ".json")

    @classmethod
    def _standing_path(cls, approval_id: str) -> Path:
        return cls._path(approval_id).parent / "standing" / (approval_id + ".json")

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return record if isinstance(record, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(path: Path, record: dict) -> None:
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(record), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def request(cls, payload: dict, reason: str, code: str) -> tuple[bool, str]:
        session = payload.get("session_id")
        if code not in cls.CODES or not isinstance(session, str) or not session:
            return False, "Operator review needs a bound Codex session."
        if not payload.get("tool_name") or not payload.get("tool_input"):
            return False, "Operator review needs the exact pending tool input."
        # Bind execution inputs, reason and policy; standing consent excludes session.
        policy = _policy_signature(payload)
        invocation = _invocation(payload)
        binding = {"payload": invocation, "reason": reason, "code": code,
                   "policy": policy}
        request_id = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        standing_binding = {**binding, "payload": {key: value for key, value in invocation.items()
                                                   if key != "session_id"}}
        approval_id = hashlib.sha256(json.dumps(standing_binding, sort_keys=True).encode()).hexdigest()
        standing_path = cls._standing_path(approval_id)
        with state_lock(standing_path):
            standing = cls._read(standing_path)
            if (standing.get("status") == "always" and standing.get("code") == code
                    and standing.get("approval_id") == approval_id):
                return True, ""
        path = cls._path(request_id)
        now = time.time()
        with state_lock(path):
            record = cls._read(path)
            fresh = (record.get("session_id") == session and
                     isinstance(record.get("expires_at"), (int, float)) and
                     now < record["expires_at"])
            if fresh and record.get("status") == "approved":
                record["status"] = "consumed"
                cls._write(path, record)
                return True, ""
            if fresh and record.get("status") == "rejected":
                return False, "The user rejected this exact operator request; do not retry it."
            recovery = _lookup_recovery(payload, reason, code)
            if recovery:
                return False, recovery
            if not fresh or record.get("status") != "pending":
                record = {"session_id": session, "code": code, "status": "pending",
                          "approval_id": approval_id,
                          "expires_at": now + cls.MAX_AGE}
                cls._write(path, record)
        return False, _question(request_id, reason, code)

    @classmethod
    def resolve(cls, request_id: str, decision: str, session: str) -> None:
        if decision not in {"approve", "always", "reject", "revoke"} or not session:
            raise ValueError("explicit decision and current Codex session required")
        path = cls._path(request_id)
        with state_lock(path):
            record = cls._read(path)
            if decision == "revoke":
                approval_id = record.get("approval_id", "")
                cls._path(approval_id)  # Validate the stored id before constructing its path.
                standing_path = cls._standing_path(approval_id)
                with state_lock(standing_path):
                    if not standing_path.is_file():
                        raise ValueError("standing approval is missing or already revoked")
                    standing_path.unlink()
                record["status"] = "revoked"
                cls._write(path, record)
                return
            if (record.get("session_id") != session or record.get("status") != "pending"
                    or record.get("code") not in cls.CODES
                    or not isinstance(record.get("expires_at"), (int, float))
                    or time.time() >= record["expires_at"]):
                raise ValueError("operator request is missing, expired, foreign or already settled")
            if decision == "always":
                approval_id = record.get("approval_id", "")
                cls._path(approval_id)
                standing_path = cls._standing_path(approval_id)
                with state_lock(standing_path):
                    cls._write(standing_path, {"approval_id": approval_id,
                                              "code": record["code"], "status": "always"})
            record["status"] = {"approve": "approved", "always": "always", "reject": "rejected"}[decision]
            cls._write(path, record)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Attest the user's explicit operator answer; never self-approve.")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--decision", choices=("approve", "always", "reject", "revoke"), required=True)
    args = parser.parse_args()
    try:
        OperatorReview.resolve(args.request_id, args.decision, os.environ.get("CODEX_THREAD_ID", ""))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("Operator answer recorded for the exact Codex scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
