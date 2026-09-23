"""Repository-shared reference messages, independent of execution evidence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json
from agent_mailbox_store import (
    _MAX_ACKS, _MAX_BODY_BYTES, _MAX_PENDING, _MAX_TTL_SECONDS, _MESSAGE_ID,
    _aware, _expired, _json_files, _parse_time, _require_local_path, _runtime,
    _validate_content,
)
from agent_project_memory import repository_key
from agent_state_lock import state_lock
from support.global_state import global_state_dir, user_store_write_error


class ReferenceMailboxStore:
    """Own bounded local reference exchange; packets never attest execution."""

    def __init__(self, project: Path, *, clock=None) -> None:
        if not project.is_dir():
            raise ValueError("mailbox project directory does not exist")
        self.repository_id = repository_key(project)
        state_home = global_state_dir().expanduser().absolute()
        self.state_home = state_home.parent.resolve() / state_home.name
        self.root = self.state_home / "agent-mailbox" / self.repository_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _check_path(self, path: Path) -> None:
        if self.state_home.is_symlink():
            raise OSError("local agent mailbox must not use symbolic links")
        _require_local_path(self.state_home, path)

    def _writable(self) -> None:
        error = user_store_write_error()
        if error:
            raise RuntimeError(error)
        self._check_path(self.root)

    def enqueue(self, *, sender: str, recipient: str, kind: str,
                body: str, ttl_seconds: int) -> dict[str, object]:
        sender, recipient = _runtime(sender), _runtime(recipient)
        _validate_content(kind, body, ttl_seconds)
        self._writable()
        now = _aware(self._clock())
        packet = {
            "schema_version": 2, "message_id": uuid.uuid4().hex,
            "repository_id": self.repository_id,
            "sender": sender, "recipient": recipient, "kind": kind,
            "body": body.strip(), "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        inbox = self.root / "inbox" / recipient
        self._check_path(inbox)
        inbox.mkdir(parents=True, exist_ok=True)
        with state_lock(self.root / ".mailbox"):
            paths = _json_files(inbox)
            for path in paths:
                if _expired(self._read(path, recipient), now):
                    path.unlink()
            if len(_json_files(inbox)) >= _MAX_PENDING:
                raise RuntimeError(f"local agent mailbox pending limit is {_MAX_PENDING}")
            atomic_write_json(inbox / f"{packet['message_id']}.json", packet)
        return packet

    def consume(self, recipient: str, *, limit: int = 8) -> list[dict[str, object]]:
        recipient = _runtime(recipient)
        if limit < 1 or limit > 8:
            raise ValueError("mailbox receive limit must be between 1 and 8")
        self._check_path(self.root)
        if not self.root.exists():
            return []
        self._writable()
        consumed = []
        with state_lock(self.root / ".mailbox"):
            for path in self._paths("inbox", recipient):
                packet = self._read(path, recipient)
                receipt = self.root / "acked" / recipient / path.name
                self._check_path(receipt)
                if _expired(packet, self._clock()) or receipt.exists():
                    path.unlink()
                    continue
                atomic_write_json(receipt, {
                    "schema_version": 2, "message_id": packet["message_id"],
                    "repository_id": self.repository_id, "recipient": recipient,
                    "consumed_at": _aware(self._clock()).isoformat(),
                })
                path.unlink()
                for stale in self._paths("acked", recipient)[:-_MAX_ACKS]:
                    stale.unlink()
                consumed.append(packet)
                if len(consumed) == limit:
                    break
        return consumed

    def status(self, recipient: str) -> dict[str, int | str]:
        recipient = _runtime(recipient)
        self._check_path(self.root)
        packets = [self._read(path, recipient) for path in self._paths("inbox", recipient)]
        expired = sum(_expired(packet, self._clock()) for packet in packets)
        return {"runtime": recipient, "pending": len(packets) - expired,
                "expired": expired, "acked": len(self._paths("acked", recipient))}

    def _paths(self, category: str, recipient: str) -> list[Path]:
        directory = self.root / category / recipient
        self._check_path(directory)
        return _json_files(directory) if directory.exists() else []

    def _read(self, path: Path, recipient: str) -> dict[str, object]:
        self._check_path(path)
        if path.stat().st_size > _MAX_BODY_BYTES + 4096:
            raise ValueError("local agent mailbox packet exceeds its size limit")
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("local agent mailbox packet is malformed") from error
        fields = {"schema_version", "message_id", "repository_id", "sender", "recipient",
                  "kind", "body", "created_at", "expires_at"}
        if not isinstance(packet, dict) or set(packet) != fields or packet["schema_version"] != 2:
            raise ValueError("local agent mailbox packet uses an unsupported schema")
        if packet["repository_id"] != self.repository_id or packet["recipient"] != recipient:
            raise ValueError("local agent mailbox packet has an invalid repository/runtime binding")
        if packet["message_id"] != path.stem or not _MESSAGE_ID.fullmatch(path.stem):
            raise ValueError("local agent mailbox packet has an invalid message id")
        _runtime(str(packet["sender"]))
        if not isinstance(packet["body"], str):
            raise ValueError("mailbox body must be text")
        _validate_content(str(packet["kind"]), packet["body"], 1)
        lifetime = (_parse_time(packet["expires_at"]) - _parse_time(packet["created_at"])).total_seconds()
        if lifetime <= 0 or lifetime > _MAX_TTL_SECONDS:
            raise ValueError("local agent mailbox packet has an invalid TTL")
        return packet
