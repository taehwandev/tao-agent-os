"""Deliver pending mailbox messages to one runtime session without losing them.

`receive` consumes a message the moment it is read, which suits an agent that
asks for it. A hook that pushes messages into a prompt cannot do that: if its
output never reaches the conversation, the message would be gone. Delivery is
therefore split. A session first *claims* a message (a lease naming it), the
hook prints it, and the claim is marked *delivered*. Only a later turn boundary
of that same session -- its Stop hook, or its next prompt -- acknowledges it,
which writes the store's ordinary receipt and removes the packet.

A claim that was never marked delivered is offered to the same session again;
a lease that outlives its window is offered to any session, so a session that
ended mid-turn does not hold a message forever. Message ids let a reader tell a
redelivery from a new message. Acknowledging is idempotent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json
from agent_mailbox_reference import ReferenceMailboxStore
from agent_mailbox_store import MailboxStore, _aware, _runtime
from agent_state_lock import state_lock

LEASE_SECONDS = 30 * 60
CLAIMED = "claimed"
DELIVERED = "delivered"


def _stores(project: Path, clock: Callable[[], datetime]) -> list:
    return [MailboxStore(project, clock=clock), ReferenceMailboxStore(project, clock=clock)]


def _read_lease(path: Path) -> dict:
    try:
        lease = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return lease if isinstance(lease, dict) else {}


def _live(lease: dict, now: datetime) -> bool:
    try:
        return _aware(datetime.fromisoformat(str(lease.get("expires_at")))) > now
    except (TypeError, ValueError):
        return False


def leased_elsewhere(lease_dir: Path, packet: dict, session_id: str, now: datetime) -> bool:
    """Whether another session holds a live lease on this packet."""

    lease = _read_lease(lease_dir / f"{packet['message_id']}.json")
    return bool(lease) and lease.get("session_id") != session_id and _live(lease, now)


class SessionDelivery:
    """Claim, mark and acknowledge mailbox messages for one runtime session."""

    def __init__(
        self,
        project: Path,
        runtime: str,
        session_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("mailbox delivery needs a runtime session id")
        self.project = project.expanduser().resolve()
        self.runtime = _runtime(runtime)
        self.session_id = session_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(self, *, limit: int = 8) -> list[dict[str, object]]:
        """Lease up to `limit` messages this session may show now."""

        claimed: list[dict[str, object]] = []
        now = _aware(self._clock())
        for store in _stores(self.project, self._clock):
            if len(claimed) >= limit or not store.root.exists():
                continue
            with state_lock(store.lock_path):
                lease_dir = store.lease_dir(self.runtime)
                for _path, _receipt, packet in store.pending(self.runtime):
                    lease_path = lease_dir / f"{packet['message_id']}.json"
                    lease = _read_lease(lease_path)
                    if lease and _live(lease, now):
                        # Held elsewhere, or already shown to this session and
                        # waiting for its acknowledgement.
                        if lease.get("session_id") != self.session_id or lease.get("state") == DELIVERED:
                            continue
                    lease_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(lease_path, {
                        "session_id": self.session_id,
                        "state": CLAIMED,
                        "leased_at": now.isoformat(),
                        "expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                    })
                    claimed.append(packet)
                    if len(claimed) >= limit:
                        break
        return claimed

    def mark_delivered(self, message_ids: list[str]) -> None:
        """Record that these claims reached the conversation."""

        wanted = set(message_ids)
        for store in _stores(self.project, self._clock):
            if not wanted or not store.root.exists():
                continue
            with state_lock(store.lock_path):
                lease_dir = store.lease_dir(self.runtime)
                for message_id in sorted(wanted):
                    lease_path = lease_dir / f"{message_id}.json"
                    lease = _read_lease(lease_path)
                    if lease.get("session_id") == self.session_id:
                        atomic_write_json(lease_path, {**lease, "state": DELIVERED})
                        wanted.discard(message_id)

    def acknowledge(self) -> list[str]:
        """Commit every message this session was shown; safe to repeat."""

        acknowledged: list[str] = []
        for store in _stores(self.project, self._clock):
            if not store.root.exists():
                continue
            with state_lock(store.lock_path):
                lease_dir = store.lease_dir(self.runtime)
                if not lease_dir.exists():
                    continue
                pending = {str(packet["message_id"]): (path, receipt, packet)
                           for path, receipt, packet in store.pending(self.runtime)}
                for lease_path in sorted(lease_dir.glob("*.json")):
                    lease = _read_lease(lease_path)
                    message_id = lease_path.stem
                    if message_id not in pending:
                        # Committed or expired already: the lease is all that is left.
                        lease_path.unlink(missing_ok=True)
                        continue
                    if lease.get("session_id") != self.session_id or lease.get("state") != DELIVERED:
                        continue
                    store.commit(*pending[message_id])
                    lease_path.unlink(missing_ok=True)
                    acknowledged.append(message_id)
        return acknowledged
