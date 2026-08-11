"""Required-document snapshot helpers for execution capsules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    capsule_path_for_evidence,
    contained_doc_path,
    doc_hash_record,
    execution_capsule_binding_fingerprint,
    is_sha256,
    preflight_snapshot_binding_fingerprint,
    read_json_object,
)
from agent_route_state import (
    preflight_evidence_sha256,
    required_docs_for_route,
    route_fingerprint,
)
from agent_repair_ledger import checkpoint_has_recorded_failure
from agent_repair_receipt_validation import validate_repair_receipt


REQUIRED_DOC_RECEIPT_VERSION = "1"


def current_required_docs(
    rules: Path,
    route: dict[str, Any],
) -> list[dict[str, Any]] | None:
    records: list[dict[str, Any]] = []
    try:
        for relative in required_docs_for_route(route):
            records.append(doc_hash_record(relative, contained_doc_path(rules, relative)))
    except (OSError, ValueError):
        return None
    return records


def bind_required_doc_update_receipt(
    *,
    evidence_path: Path,
    gate: str,
    status: str,
    fields: dict[str, str],
) -> dict[str, str]:
    """Bind an intentional required-doc update to its pre- and post-edit bytes.

    The gate writer, rather than the caller, owns these hashes.  That keeps the
    pre-edit snapshot immutable while allowing finish to recognize one exact
    documented final artifact without turning the documentation decision into
    a blanket hash-check bypass.
    """

    if (
        gate != "documentation"
        or status != "SUCCESS"
        or fields.get("decision", "").strip().lower() != "updated"
    ):
        return fields

    preflight = read_json_object(evidence_path)
    if not preflight or preflight.get("invalid_json"):
        raise ValueError("required-doc update receipt requires valid preflight evidence")
    route = preflight.get("route") or {}
    target = fields.get("target", "").strip()
    if target not in set(required_docs_for_route(route)):
        return fields
    if "documentation" not in {str(item) for item in (route.get("gates") or [])}:
        _validate_off_route_required_doc_repair(
            evidence_path=evidence_path,
            preflight=preflight,
            route=route,
            target=target,
            fields=fields,
        )

    baseline = _required_doc_baseline(evidence_path, preflight, target)
    if baseline is None:
        raise ValueError(
            f"required-doc update receipt has no trusted pre-edit baseline: {target}"
        )
    rules_value = preflight.get("rules")
    if not isinstance(rules_value, str) or not rules_value.strip():
        raise ValueError("required-doc update receipt requires a rules root")
    try:
        rules = Path(rules_value).expanduser().resolve()
        final = doc_hash_record(target, contained_doc_path(rules, target))
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(
            f"required-doc update receipt cannot hash final artifact: {target}"
        ) from error

    bound = dict(fields)
    bound.update(
        {
            "artifact_receipt_version": REQUIRED_DOC_RECEIPT_VERSION,
            "baseline_sha256": str(baseline["sha256"]),
            "final_sha256": str(final["sha256"]),
            "final_size_bytes": str(final["size_bytes"]),
        }
    )
    return bound


def _validate_off_route_required_doc_repair(
    *,
    evidence_path: Path,
    preflight: dict[str, Any],
    route: dict[str, Any],
    target: str,
    fields: dict[str, str],
) -> None:
    """Require structural repair proof before an off-route receipt is minted."""

    checkpoint = fields.get("resume_checkpoint", "").strip()
    repair_evidence = fields.get("repair_evidence", "").strip()
    if not checkpoint or not repair_evidence:
        raise ValueError(
            "off-route required-doc update receipt requires resume_checkpoint "
            "and repair_evidence from repair-verify"
        )
    if not checkpoint_has_recorded_failure(
        route=route,
        evidence_path=evidence_path,
        checkpoint=checkpoint,
    ):
        raise ValueError(
            "off-route required-doc update receipt requires an actual failed checkpoint"
        )
    project_value = preflight.get("project")
    rules_value = preflight.get("rules")
    if not isinstance(project_value, str) or not isinstance(rules_value, str):
        raise ValueError(
            "off-route required-doc update receipt requires project and rules roots"
        )
    project = Path(project_value).expanduser().resolve()
    rules = Path(rules_value).expanduser().resolve()
    receipt_path = Path(repair_evidence).expanduser()
    if not receipt_path.is_absolute():
        receipt_path = project / receipt_path
    failures = validate_repair_receipt(
        project=project,
        rules=rules,
        evidence_path=evidence_path,
        preflight=preflight,
        target=str(contained_doc_path(rules, target)),
        checkpoint=checkpoint,
        receipt_path=receipt_path,
    )
    if failures:
        raise ValueError(
            "off-route required-doc update receipt repair evidence is invalid: "
            + "; ".join(failures)
        )


def validated_required_doc_update_receipt(
    fields: dict[str, str],
) -> dict[str, str] | None:
    """Return a normalized trusted-receipt shape or fail closed."""

    if fields.get("artifact_receipt_version") != REQUIRED_DOC_RECEIPT_VERSION:
        return None
    baseline = fields.get("baseline_sha256")
    final = fields.get("final_sha256")
    final_size = fields.get("final_size_bytes")
    if not is_sha256(baseline) or not is_sha256(final):
        return None
    if not isinstance(final_size, str) or not final_size.isdigit():
        return None
    return {
        "artifact_receipt_version": REQUIRED_DOC_RECEIPT_VERSION,
        "baseline_sha256": baseline,
        "final_sha256": final,
        "final_size_bytes": final_size,
    }


def required_doc_failures(
    recorded: list[dict[str, Any]],
    rules: Path,
    route: dict[str, Any],
    documented_updates: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    expected = required_docs_for_route(route)
    if [str(item.get("path")) for item in recorded] != expected:
        return ["execution capsule required-doc manifest does not match"]
    failures: list[str] = []
    update_receipts = documented_updates or {}
    for item in recorded:
        relative = str(item["path"])
        try:
            current = doc_hash_record(relative, contained_doc_path(rules, relative))
        except (OSError, ValueError):
            failures.append(f"execution capsule required doc is unavailable: {relative}")
            continue
        receipt = validated_required_doc_update_receipt(
            update_receipts.get(relative, {})
        )
        if receipt is not None:
            if receipt["baseline_sha256"] != item["sha256"]:
                failures.append(
                    "execution capsule required doc documentation baseline does not match: "
                    f"{relative}"
                )
            else:
                if (
                    current["size_bytes"] != int(receipt["final_size_bytes"])
                    or current["sha256"] != receipt["final_sha256"]
                ):
                    failures.append(
                        "execution capsule required doc changed after documentation evidence: "
                        f"{relative}"
                    )
                continue
        if current["size_bytes"] != item["size_bytes"]:
            failures.append(f"execution capsule required doc size changed: {relative}")
        if current["sha256"] != item["sha256"]:
            failures.append(f"execution capsule required doc hash changed: {relative}")
    return failures


def _required_doc_baseline(
    evidence_path: Path,
    preflight: dict[str, Any],
    target: str,
) -> dict[str, Any] | None:
    route = preflight.get("route") or {}
    expected_route_fingerprint = route_fingerprint(route)
    snapshot = preflight.get("execution_snapshot")
    if (
        isinstance(snapshot, dict)
        and preflight_snapshot_binding_fingerprint(snapshot)
        and snapshot.get("route_fingerprint") == expected_route_fingerprint
    ):
        baseline = _doc_record_for_target(snapshot.get("required_docs"), target)
        if baseline is not None:
            return baseline

    capsule = read_json_object(capsule_path_for_evidence(evidence_path))
    preflight_record = capsule.get("preflight_evidence")
    if not (
        execution_capsule_binding_fingerprint(capsule)
        and capsule.get("route_fingerprint") == expected_route_fingerprint
        and isinstance(preflight_record, dict)
        and preflight_record.get("sha256") == preflight_evidence_sha256(evidence_path)
    ):
        return None
    return _doc_record_for_target(capsule.get("required_docs"), target)


def _doc_record_for_target(records: Any, target: str) -> dict[str, Any] | None:
    if not isinstance(records, list):
        return None
    for item in records:
        if (
            isinstance(item, dict)
            and item.get("path") == target
            and isinstance(item.get("size_bytes"), int)
            and item["size_bytes"] >= 0
            and is_sha256(item.get("sha256"))
        ):
            return item
    return None
