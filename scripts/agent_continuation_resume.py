"""Discovery of unfinished continuation packets for one checkout.

``resume_list`` reports and never mutates: the registry is read without its lock
because every write is an atomic replace, so listing unfinished work is always
safe to run. ``resume_last`` resumes, which is what its name promises, and it
targets exactly one packet -- the newest. A blocked newest packet is refused by
name; it never falls through to an older task, because a caller asking for the
last thing they were doing has the least context in which to notice they were
handed something else. Every mutation still happens inside ``claim_resume``,
which remains the only owner of the takeover transaction.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import binding_required_docs, first_unfinished_checkpoint
from agent_continuation_claim import (
    FREE_HOLDER_STATES,
    TERMINAL_RUN_STATES,
    claim_resume,
)
from agent_continuation_drift import verify_drift
from agent_continuation_store import (
    continuation_path,
    list_continuation_run_ids,
    read_continuation_packet,
)
from agent_execution_capsule_state import git_states_for_paths, read_json_object
from agent_run_registry import read_registry_state, registry_path, resume_holder_state


DRIFT_LABELS = (
    ("head", "head_drift"),
    ("project_worktree", "worktree_drift"),
    ("rules_worktree", "worktree_drift"),
    ("required_docs", "required_doc_drift"),
)
UNRESUMABLE_STATUSES = ("invalid_packet", "local_boundary_failed")
RERUN_CONDITIONS = (
    "state_changed",
    "external_freshness_required",
    "different_acceptance_boundary",
)


def resume_list(
    project: Path,
    *,
    rules: Path | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Enumerate this checkout's unfinished packets, newest first.

    Only the selected project root is inspected. Another Git worktree has
    different mutable state and is not a candidate even when it shares object
    storage.

    A packet is listed only while the registry still records its run. The
    registry keeps a bounded number of runs, and a packet outlives the record
    that was pruned from under it -- but claiming one returns ``claim_lost``
    and checkpointing one returns ``unknown_run``, because the owner and
    generation a claim compares against are gone. Listing those as free
    candidates offered work nobody could take, and cost a drift verification
    each to offer it: 56 of the 72 entries in the checkout that prompted this,
    and seconds at every session start. They are counted rather than dropped
    silently, because a packet that exists and cannot be resumed is retention
    debt worth seeing.
    """

    runs, recorded = _registered_runs(project)
    packets = set(list_continuation_run_ids(project))
    states = _CheckoutStates(project)
    entries = [
        _entry(project, rules, run_id, runs, stale_after_seconds, states)
        for run_id in sorted(packets | set(runs))
        if run_id in runs
    ]
    entries.sort(key=lambda entry: entry["updated_at"], reverse=True)
    return {
        "result": "ok",
        "entries": entries,
        # Counted against every run the registry records, not against the
        # unfinished ones alone. Subtracting the listed entries from the
        # candidates counted a run that simply finished: it is absent from
        # `runs`, so nothing filtered it out and nothing listed it, and the
        # difference reported it as a packet the registry had lost. On the
        # checkout that caught this, 39 completed runs were reported as
        # unclaimable debt while the true number was zero.
        "unregistered_packets": len(packets - recorded),
    }


def session_resume_summaries(project: Path) -> list[dict[str, str]]:
    """Return the content-free SessionStart choice set without packet checks.

    Automatic startup needs only two facts before it can choose safely: whether
    this checkout has exactly one unfinished run, and which opaque runs to name
    when it has several.  Packet boundary, drift, and Git checks belong to the
    one run that is actually selected.  Running them for every historical
    failure made startup cost grow with abandoned work even when no run could
    be selected.
    """

    entries = [
        {
            "run_id": run_id,
            "route_command": str(run.get("command") or ""),
            "updated_at": str(run.get("updated_at") or ""),
        }
        for run_id, run in _unfinished_runs(project).items()
    ]
    entries.sort(key=lambda entry: entry["updated_at"], reverse=True)
    return entries


def resume_last(
    project: Path,
    *,
    run_id: str = "",
    rules: Path | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Resume one unfinished packet for this checkout, or refuse by name.

    Exactly one packet is ever a candidate. If it is held, unproven, drifted, or
    invalid, that is the answer; an older task is never substituted for the one
    the caller asked for. Owner policy and drift are decided inside
    ``claim_resume`` so one transaction owns every stable result code.

    Which packet is the candidate is the caller's to say. Without ``run_id`` it
    is the newest, which is right for a checkout one session works at a time.
    Several sessions working the same checkout keep touching that slot, so the
    newest is almost never the one a returning session left behind, and
    refusing to substitute an older task -- correct on its own -- then left that
    session with no way to reach its own work at all. Naming the run makes the
    candidate explicit; the generation check still decides whether the claim is
    allowed, so naming another session's live run is refused, not granted.
    """

    if run_id:
        runs = _unfinished_runs(project)
        if run_id not in runs:
            return _result("not_found", {}, reason="run_id_not_unfinished")
        entries = [
            _entry(
                project,
                rules,
                run_id,
                runs,
                stale_after_seconds,
                _CheckoutStates(project),
            )
        ]
    else:
        entries = resume_list(
            project,
            rules=rules,
            stale_after_seconds=stale_after_seconds,
        )["entries"]
    if not entries:
        return _result("not_found", {}, reason="no_unfinished_packet")
    if run_id:
        named = next((item for item in entries if item["run_id"] == run_id), None)
        if named is None:
            return _result("not_found", {}, reason="run_id_not_unfinished")
        newest = named
    else:
        newest = entries[0]
    if newest["status"] in UNRESUMABLE_STATUSES:
        return _result(newest["status"], newest, reason=newest["status"])
    if newest["status"] != "ok":
        # A packet-less registry entry is recovered by a fresh start, and it
        # still occupies the newest slot rather than yielding it to an older run.
        return _result("not_found", newest, reason=newest["status"])
    if newest["first_unfinished"] is None:
        return _result("not_found", newest, reason="already_finished")
    claim = claim_resume(
        project,
        newest["run_id"],
        expected_generation=newest["resume_generation"],
        rules=rules,
        stale_after_seconds=stale_after_seconds,
    )
    return _claimed(claim, newest)


def _unfinished_runs(project: Path) -> dict[str, dict[str, Any]]:
    """Return registered non-terminal runs keyed by their opaque id."""

    return _registered_runs(project)[0]


def _registered_runs(project: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Return the resumable runs, and every run id the registry still records.

    Both come from one read. A caller that needs to say whether a packet has
    outlived its record needs the whole set, and deriving that from the
    unfinished runs alone reads a finished run as a missing one.
    """

    unfinished: dict[str, dict[str, Any]] = {}
    recorded: set[str] = set()
    for run in read_registry_state(registry_path(project)).get("runs") or []:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            continue
        recorded.add(run_id)
        if run.get("state") not in TERMINAL_RUN_STATES:
            unfinished[run_id] = run
    return unfinished, recorded


def _claimed(
    claim: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    ready = claim["result"] == "ready"
    return _result(
        claim["result"],
        entry,
        reason="" if ready else claim["result"],
        evidence_path=claim.get("evidence_path", ""),
        resume_generation=claim["resume_generation"],
        holder_state=claim["holder_state"] or entry["holder_state"],
        changed_signals=claim["changed_signals"],
        affected_paths=claim["affected_paths"],
        # A refusal returns no semantic work object and no checkpoint to
        # resume from; only a completed claim does.
        work=claim["packet"]["work"] if ready else None,
        checkpoint=entry["first_unfinished"] if ready else None,
        reuse=_reuse_summary(
            claim["packet"]["work"],
            binding_path=Path(claim["evidence_path"]),
            first_unfinished=entry["first_unfinished"],
        ) if ready else None,
    )


def _result(result: str, entry: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result": result,
        "reason": "",
        "run_id": entry.get("run_id", ""),
        "evidence_path": "",
        "route_command": entry.get("route_command", ""),
        "resume_generation": None,
        "checkpoint": None,
        "work": None,
        "reuse": None,
        "holder_state": entry.get("holder_state", ""),
        "changed_signals": entry.get("changed_signals", []),
        "affected_paths": entry.get("affected_paths", []),
    }
    payload.update(overrides)
    return payload


def _reuse_summary(
    work: dict[str, Any],
    *,
    binding_path: Path,
    first_unfinished: str | None,
) -> dict[str, Any]:
    """Expose only content-free proof that unchanged work need not be repeated."""

    accepted = [
        {"id": record["id"], "status": record["status"]}
        for record in work.get("decisions") or []
        if record.get("status") == "accepted"
    ]
    successful = [
        {"id": record["id"], "kind": record["kind"]}
        for record in work.get("verification") or []
        if record.get("result") == "success"
    ]
    return {
        "decision": "reuse_unchanged_evidence",
        "required_docs": _required_docs_reuse(binding_path, first_unfinished),
        "inspected_scope_count": len(work.get("inspected_scope") or []),
        "accepted_decisions": accepted,
        "successful_verification": successful,
        "rerun_when": list(RERUN_CONDITIONS),
    }


def _required_docs_reuse(binding_path: Path, first_unfinished: str | None) -> str:
    """Reuse doc reading only after the authoritative source-doc gate passed."""

    binding = read_json_object(binding_path)
    if not binding_required_docs(binding):
        return "not_applicable"
    gates = [str(gate) for gate in (binding.get("route") or {}).get("gates") or []]
    if "source docs" not in gates:
        return "not_recorded"
    if first_unfinished == "finish":
        return "reuse"
    if first_unfinished not in gates:
        return "not_recorded"
    return (
        "reuse"
        if gates.index(first_unfinished) > gates.index("source docs")
        else "not_recorded"
    )


def _packet_present(path: Path) -> bool:
    """Answer absence from the filesystem, before Git is asked about the path.

    Reading a packet proves its boundary first, and that proof asks Git whether
    this exact path is ignored -- a subprocess. A registry entry that never
    wrote a packet paid it anyway, to learn there was nothing to read: fourteen
    of sixteen candidates in the checkout this was measured in, and the
    listing's dominant cost once the drift capture was shared.

    ``lstat`` rather than ``exists``: a dangling or redirecting symlink is not
    an absence, and it must reach the full boundary proof that refuses it.
    """

    try:
        os.lstat(path)
    except OSError:
        return False
    return True


class _CheckoutStates:
    """One project/rules capture per listing instead of one per packet.

    Every packet in a checkout is compared against the same HEAD and the same
    worktree fingerprint; only the required-document digest is the packet's
    own. Capturing per packet made that fingerprint the listing's dominant
    cost -- 56% of it here -- for an answer that could not differ. Packets
    bound to different rules roots each get their own capture, so the saving
    never comes from comparing a packet against a root it was not written
    against.

    Listing is advisory: `claim_resume` captures again under the lock before
    it takes anything, so one snapshot per listing is also the more honest
    report, describing one moment rather than a smear across the scan.
    """

    def __init__(self, project: Path) -> None:
        self._project = project
        self._captured: dict[str, tuple[dict[str, str], dict[str, str]]] = {}

    def for_rules(self, rules: Path) -> tuple[dict[str, str], dict[str, str]]:
        key = str(rules)
        if key not in self._captured:
            self._captured[key] = git_states_for_paths(self._project, rules)
        return self._captured[key]


def _entry(
    project: Path,
    rules: Path | None,
    run_id: str,
    runs: dict[str, dict[str, Any]],
    stale_after_seconds: int,
    states: _CheckoutStates,
) -> dict[str, Any]:
    run = runs.get(run_id) or {}
    state = (
        resume_holder_state(run, stale_after_seconds=stale_after_seconds)
        if run
        else "dead_proven"
    )
    entry: dict[str, Any] = {
        "run_id": run_id,
        "status": "legacy_no_packet" if run else "unknown_run",
        "route_command": str(run.get("command") or ""),
        "objective": "",
        "updated_at": str(run.get("updated_at") or ""),
        "first_unfinished": None,
        "drift": "",
        "changed_signals": [],
        "affected_paths": [],
        "pending": None,
        "holder_state": state,
        "holder": _holder(state),
        "resume_generation": int(run.get("resume_generation") or 0),
        "run_state": str(run.get("state") or ""),
    }
    packet_path = continuation_path(project, run_id)
    if not _packet_present(packet_path):
        return entry
    result = read_continuation_packet(project, packet_path)
    if result["status"] == "not_found":
        return entry
    if result["status"] != "ok":
        # An invalid packet is listed by opaque run id; its prose is never read.
        entry["status"] = result["status"]
        entry["failures"] = result["failures"]
        return entry
    return _packet_entry(project, rules, entry, result["packet"], states)


def _packet_entry(
    project: Path,
    rules: Path | None,
    entry: dict[str, Any],
    packet: dict[str, Any],
    states: _CheckoutStates,
) -> dict[str, Any]:
    binding_path = continuation_path(project, entry["run_id"]).parent / packet["binding"]["filename"]
    binding = read_json_object(binding_path)
    rules_root = _rules_root(binding, rules, project)
    drift = verify_drift(
        project,
        rules_root,
        packet,
        required_doc_records=binding_required_docs(binding),
        git_states=states.for_rules(rules_root),
    )
    entry.update(
        {
            "status": "ok",
            "objective": packet["work"]["objective"],
            "updated_at": _latest(packet["updated_at"], entry["updated_at"]),
            "route_command": str((binding.get("route") or {}).get("command") or entry["route_command"]),
            "first_unfinished": first_unfinished_checkpoint(
                binding_path, run_state=entry["run_state"]
            ),
            "drift": _drift_label(drift["changed_signals"]),
            "changed_signals": drift["changed_signals"],
            "affected_paths": drift["affected_paths"],
            "pending": drift["pending_state"],
            "phase": packet["phase"],
        }
    )
    return entry


def _latest(*values: str) -> str:
    """Return the most recent evidence that a run was active.

    A packet that cannot be read has no snapshot time of its own, so ordering
    would fall back to its registry heartbeat alone. Taking the later of the two
    for readable packets keeps a stale heartbeat from demoting a fresh packet
    below an older run -- which would hand the caller an older task by exactly
    the silent substitution ``resume_last`` exists to refuse.
    """

    moments = []
    for value in values:
        try:
            moments.append((datetime.fromisoformat(str(value).replace("Z", "+00:00")), value))
        except ValueError:
            continue
    return max(moments)[1] if moments else ""


def _rules_root(binding: dict[str, Any], rules: Path | None, project: Path) -> Path:
    """Resolve the rules root this run was started against, not a guessed one."""

    if binding.get("rules"):
        return Path(str(binding["rules"]))
    return rules or project


def _drift_label(signals: list[str]) -> str:
    for signal, label in DRIFT_LABELS:
        if signal in signals:
            return label
    return "drift_refused" if signals else "clean"


def _holder(state: str) -> str:
    if state in FREE_HOLDER_STATES:
        return "free"
    return "unproven" if state == "unproven_wait" else "held"
