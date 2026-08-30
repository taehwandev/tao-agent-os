"""Atomic, project/run-bound storage for local cross-runtime handoffs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json, is_sha256
from agent_state_lock import state_lock


_MAX_BODY_BYTES = 32 * 1024
_MAX_PENDING = 32
_MAX_SCAN_FILES = 128
_MAX_SCAN_RUNS = 64
_MAX_TTL_SECONDS = 7 * 24 * 60 * 60
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_MESSAGE_ID = re.compile(r"^[0-9a-f]{32}$")
_PACKET_FIELDS = {
    "schema_version", "message_id", "project_fingerprint", "source_run_id",
    "evidence_fingerprint", "sender", "recipient", "kind", "body",
    "created_at", "expires_at",
}
_RUNTIME_ALIASES = {
    "agy": "antigravity",
    "antigravity": "antigravity",
    "claude": "claude",
    "codex": "codex",
}


class MailboxStore:
    """Own bounded pending messages and body-free acknowledgement receipts."""

    def __init__(
        self,
        project: Path,
        *,
        evidence_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.project = project.expanduser().resolve()
        self.evidence_path = evidence_path.expanduser().resolve() if evidence_path else None
        self.root = self.project / ".tao" / "agent-mailbox"
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def enqueue(
        self,
        *,
        sender: str,
        recipient: str,
        kind: str,
        body: str,
        ttl_seconds: int,
    ) -> dict[str, object]:
        sender = _runtime(sender)
        recipient = _runtime(recipient)
        _validate_content(kind, body, ttl_seconds)
        run_id, evidence_fingerprint = _source_binding(self.project, self.evidence_path)
        now = _aware(self._clock())
        packet: dict[str, object] = {
            "schema_version": 1,
            "message_id": uuid.uuid4().hex,
            "project_fingerprint": _project_fingerprint(self.project),
            "source_run_id": run_id,
            "evidence_fingerprint": evidence_fingerprint,
            "sender": sender,
            "recipient": recipient,
            "kind": kind,
            "body": body.strip(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        _require_local_path(self.project, self.root)
        inbox = self.root / "runs" / run_id / "inbox" / recipient
        inbox.mkdir(parents=True, exist_ok=True)
        _require_local_path(self.project, inbox)
        with state_lock(self.root / ".mailbox"):
            pending = _json_files(inbox)
            if len(pending) >= _MAX_PENDING:
                raise RuntimeError(f"local agent mailbox pending limit is {_MAX_PENDING}")
            atomic_write_json(inbox / f"{packet['message_id']}.json", packet)
        return packet

    def consume(self, recipient: str, *, limit: int = 8) -> list[dict[str, object]]:
        recipient = _runtime(recipient)
        if limit < 1 or limit > 8:
            raise ValueError("mailbox receive limit must be between 1 and 8")
        if not self.root.exists():
            return []
        _require_local_path(self.project, self.root)
        consumed: list[dict[str, object]] = []
        with state_lock(self.root / ".mailbox"):
            for path, run_id in _pending_paths(self.project, self.root, recipient):
                packet = _read_packet(path, self.project, run_id, recipient)
                if _expired(packet, self._clock()):
                    path.unlink()
                    continue
                receipt = _receipt_path(self.root, run_id, recipient, str(packet["message_id"]))
                _require_local_path(self.project, receipt.parent)
                if receipt.exists():
                    path.unlink()
                    continue
                atomic_write_json(receipt, _acknowledgement(packet, self._clock()))
                path.unlink()
                consumed.append(packet)
                if len(consumed) == limit:
                    break
        return consumed

    def status(self, recipient: str) -> dict[str, int | str]:
        recipient = _runtime(recipient)
        if not self.root.exists():
            return {"runtime": recipient, "pending": 0, "expired": 0, "acked": 0}
        _require_local_path(self.project, self.root)
        pending = expired = 0
        for path, run_id in _pending_paths(self.project, self.root, recipient):
            packet = _read_packet(path, self.project, run_id, recipient)
            expired += int(_expired(packet, self._clock()))
            pending += int(not _expired(packet, self._clock()))
        return {
            "runtime": recipient,
            "pending": pending,
            "expired": expired,
            "acked": len(_ack_paths(self.project, self.root, recipient)),
        }


def _source_binding(project: Path, evidence_path: Path | None) -> tuple[str, str]:
    if evidence_path is None or not evidence_path.is_file():
        raise ValueError("preflight evidence does not exist")
    try:
        relative = evidence_path.relative_to(project / ".tao" / "runs")
    except ValueError as error:
        raise ValueError("preflight evidence must stay under this project's .tao/runs root") from error
    if len(relative.parts) != 2 or not _RUN_ID.fullmatch(relative.parts[0]):
        raise ValueError("preflight evidence must belong to one opaque Tao run")
    fingerprint = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()
    return relative.parts[0], fingerprint


def _validate_content(kind: str, body: str, ttl_seconds: int) -> None:
    if kind not in {"opinion", "review", "task"}:
        raise ValueError("mailbox kind must be opinion, review, or task")
    if not body.strip():
        raise ValueError("mailbox body must be provided on stdin")
    if len(body.encode("utf-8")) > _MAX_BODY_BYTES:
        raise ValueError(f"mailbox body exceeds the {_MAX_BODY_BYTES}-byte limit")
    if ttl_seconds < 1 or ttl_seconds > _MAX_TTL_SECONDS:
        raise ValueError(f"mailbox TTL must be between 1 and {_MAX_TTL_SECONDS} seconds")


def _pending_paths(project: Path, root: Path, recipient: str) -> list[tuple[Path, str]]:
    runs = root / "runs"
    if not runs.exists():
        return []
    _require_local_path(project, runs)
    run_dirs = sorted(path for path in runs.iterdir() if path.is_dir() or path.is_symlink())
    if len(run_dirs) > _MAX_SCAN_RUNS:
        raise RuntimeError(f"local agent mailbox run scan limit is {_MAX_SCAN_RUNS}")
    selected: list[tuple[Path, str]] = []
    for run_dir in run_dirs:
        _require_local_path(project, run_dir)
        if not _RUN_ID.fullmatch(run_dir.name):
            raise ValueError("local agent mailbox contains an invalid Tao run directory")
        inbox = run_dir / "inbox" / recipient
        if not inbox.exists():
            continue
        _require_local_path(project, inbox)
        selected.extend((path, run_dir.name) for path in _json_files(inbox))
        if len(selected) > _MAX_SCAN_FILES:
            raise RuntimeError(f"local agent mailbox scan limit is {_MAX_SCAN_FILES}")
    return sorted(selected, key=lambda item: item[0].name)


def _ack_paths(project: Path, root: Path, recipient: str) -> list[Path]:
    paths: list[Path] = []
    for run_dir in (root / "runs").iterdir() if (root / "runs").exists() else ():
        acked = run_dir / "acked" / recipient
        if acked.exists():
            _require_local_path(project, acked)
            paths.extend(_json_files(acked))
    return paths


def _read_packet(path: Path, project: Path, run_id: str, recipient: str) -> dict[str, object]:
    _require_local_path(project, path)
    if path.stat().st_size > _MAX_BODY_BYTES + 4096:
        raise ValueError("local agent mailbox packet exceeds its size limit")
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("local agent mailbox packet is malformed") from error
    _validate_packet(packet, project, run_id, recipient, path.stem)
    return packet


def _validate_packet(packet: object, project: Path, run_id: str, recipient: str, message_id: str) -> None:
    if not isinstance(packet, dict) or set(packet) != _PACKET_FIELDS or packet.get("schema_version") != 1:
        raise ValueError("local agent mailbox packet uses an unsupported schema")
    if packet.get("project_fingerprint") != _project_fingerprint(project):
        raise ValueError("local agent mailbox packet belongs to a different project")
    if packet.get("source_run_id") != run_id:
        raise ValueError("local agent mailbox packet belongs to a different Tao run")
    if packet.get("message_id") != message_id or not _MESSAGE_ID.fullmatch(message_id):
        raise ValueError("local agent mailbox packet has an invalid message id")
    if packet.get("recipient") != recipient or _runtime(str(packet.get("sender") or "")) == "":
        raise ValueError("local agent mailbox packet has an invalid runtime binding")
    if not is_sha256(packet.get("evidence_fingerprint")):
        raise ValueError("local agent mailbox packet has an invalid evidence binding")
    _validate_content(str(packet.get("kind") or ""), str(packet.get("body") or ""), 1)
    if _parse_time(packet.get("expires_at")) <= _parse_time(packet.get("created_at")):
        raise ValueError("local agent mailbox packet has an invalid TTL")


def _require_local_path(project: Path, path: Path) -> None:
    try:
        relative = path.relative_to(project)
    except ValueError as error:
        raise OSError("local agent mailbox escaped the selected project") from error
    current = project
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise OSError("local agent mailbox must not use symbolic links")
    if path.exists():
        try:
            path.resolve().relative_to(project)
        except ValueError as error:
            raise OSError("local agent mailbox escaped the selected project") from error


def _json_files(directory: Path) -> list[Path]:
    paths = sorted(path for path in directory.iterdir() if path.suffix == ".json")
    if any(path.is_symlink() for path in paths):
        raise OSError("local agent mailbox must not use symbolic links")
    return paths


def _receipt_path(root: Path, run_id: str, recipient: str, message_id: str) -> Path:
    return root / "runs" / run_id / "acked" / recipient / f"{message_id}.json"


def _acknowledgement(packet: Mapping[str, object], now: datetime) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_id": packet["message_id"],
        "project_fingerprint": packet["project_fingerprint"],
        "source_run_id": packet["source_run_id"],
        "recipient": packet["recipient"],
        "consumed_at": _aware(now).isoformat(),
    }


def _expired(packet: Mapping[str, object], now: datetime) -> bool:
    return _parse_time(packet.get("expires_at")) <= _aware(now)


def _parse_time(value: object) -> datetime:
    try:
        return _aware(datetime.fromisoformat(str(value)))
    except ValueError as error:
        raise ValueError("local agent mailbox packet has an invalid timestamp") from error


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("local agent mailbox clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _runtime(value: str) -> str:
    selected = _RUNTIME_ALIASES.get(value.strip().lower())
    if not selected:
        raise ValueError("runtime must be agy, antigravity, claude, or codex")
    return selected


def _project_fingerprint(project: Path) -> str:
    return hashlib.sha256(str(project).encode("utf-8")).hexdigest()
