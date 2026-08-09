"""The structured judgement a runtime hands to Tao, and its schema.

Tao does not read natural language here. The runtime already understands the
conversation, so it states what it concluded; this module only checks that the
statement is well formed and content-free. Deciding what the statement is
allowed to do lives in ``workflow_effect_policy``, deliberately apart from
parsing, because a claim must never be its own authorisation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_TARGET_SUMMARY_CHARS = 200

MODES = ("answer", "work")
AMBIGUITY_STATES = ("resolved", "blocking")
# Ordered from least to most dangerous. The rank, not the name, is what any
# comparison uses, so adding a level later cannot silently reorder the others.
EFFECTS = ("read", "local_write", "git_write", "external_write", "destructive")
EFFECT_RANK = {effect: rank for rank, effect in enumerate(EFFECTS)}

REQUIRED_FIELDS = (
    "schema_version",
    "request_fingerprint",
    "runtime_session_id",
    "mode",
    "intent",
    "target_summary",
    "requested_effects",
    "ambiguity",
)
OPTIONAL_FIELDS = ("prohibited_effects", "approval_ref")
_ALLOWED_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)

_SAFE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def read_intent_envelope(value: str) -> dict[str, Any] | None:
    """Read inline JSON or a JSON file, preserving malformed-as-present."""

    return _read_json_object(value)


def read_approval_record(value: str) -> dict[str, Any] | None:
    """Read the separate user-approval record used by the effect policy."""

    return _read_json_object(value)


def _read_json_object(value: str) -> dict[str, Any] | None:
    """Read inline JSON or a JSON file, preserving malformed-as-present."""

    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith("{"):
        try:
            text = Path(text).read_text(encoding="utf-8")
        except OSError:
            return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_envelope(envelope: Any) -> list[str]:
    """Return every schema failure, or an empty list when the envelope is usable."""

    if not isinstance(envelope, dict):
        return ["intent envelope must be a JSON object"]
    failures: list[str] = []
    unknown = sorted(set(envelope) - _ALLOWED_FIELDS)
    if unknown:
        failures.append(f"intent envelope has unknown fields: {', '.join(unknown)}")
    for field in REQUIRED_FIELDS:
        if field not in envelope:
            failures.append(f"intent envelope is missing required field `{field}`")
    if failures:
        return failures

    if envelope["schema_version"] != SCHEMA_VERSION:
        failures.append(f"intent envelope schema_version must be {SCHEMA_VERSION}")
    for field in ("request_fingerprint", "runtime_session_id"):
        value = envelope[field]
        # Coercing with str() accepted a number and any object with a __str__,
        # so a malformed field was normalised into a valid-looking id instead
        # of failing closed.
        if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
            failures.append(f"intent envelope `{field}` must be an opaque id string")
    if envelope["mode"] not in MODES:
        failures.append(f"intent envelope mode must be one of {', '.join(MODES)}")
    if envelope["ambiguity"] not in AMBIGUITY_STATES:
        failures.append(
            f"intent envelope ambiguity must be one of {', '.join(AMBIGUITY_STATES)}"
        )
    if not _SAFE_SLUG_RE.fullmatch(str(envelope["intent"])):
        failures.append("intent envelope `intent` must be a safe lowercase slug")
    failures.extend(_target_summary_failures(envelope["target_summary"]))
    failures.extend(_effects_failures("requested_effects", envelope["requested_effects"]))
    if "prohibited_effects" in envelope:
        failures.extend(
            _effects_failures("prohibited_effects", envelope["prohibited_effects"])
        )
    if "approval_ref" in envelope:
        approval_ref = envelope["approval_ref"]
        if not isinstance(approval_ref, str) or not _OPAQUE_ID_RE.fullmatch(
            approval_ref
        ):
            failures.append("intent envelope `approval_ref` must be an opaque id string")
    failures.extend(_contradiction_failures(envelope))
    return failures


def _target_summary_failures(value: Any) -> list[str]:
    if not isinstance(value, str):
        return ["intent envelope `target_summary` must be a bounded string"]
    text = value.strip()
    if not text:
        return ["intent envelope `target_summary` cannot be empty"]
    if len(text) > MAX_TARGET_SUMMARY_CHARS:
        return [
            "intent envelope `target_summary` exceeds the "
            f"{MAX_TARGET_SUMMARY_CHARS}-character bounded summary limit"
        ]
    if "\n" in text or "\x00" in text:
        return ["intent envelope `target_summary` must be a single bounded line"]
    return []


def _effects_failures(field: str, value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return [f"intent envelope `{field}` must be a list"]
    failures: list[str] = []
    # Every entry must be a plain effect name. Allowing any object here let an
    # unhashable one reach the rank lookup and abort validation with a
    # TypeError, which is a crash rather than a refusal.
    unknown = [repr(item) for item in value if not isinstance(item, str) or item not in EFFECTS]
    if unknown:
        failures.append(
            f"intent envelope `{field}` has unknown effects: {', '.join(sorted(unknown))}"
        )
    if field == "requested_effects" and not value:
        failures.append("intent envelope `requested_effects` cannot be empty")
    return failures


def _contradiction_failures(envelope: dict[str, Any]) -> list[str]:
    """Reject an envelope that asks for what it also forbids.

    A runtime that both requests and prohibits an effect has not resolved the
    request, and letting the pair through would make the later union depend on
    which side a caller happened to read.
    """

    # Only well-formed entries are compared. Building a set straight from the
    # raw lists aborted validation with a TypeError on an unhashable entry,
    # turning a refusal into a crash; the malformed entry is already reported.
    requested = _effect_names(envelope.get("requested_effects"))
    prohibited = _effect_names(envelope.get("prohibited_effects"))
    overlap = sorted(requested & prohibited)
    if overlap:
        return [
            "intent envelope requests effects it also prohibits: " + ", ".join(overlap)
        ]
    if envelope.get("mode") == "answer" and requested - {"read"}:
        return [
            "intent envelope in answer mode may request only the read effect"
        ]
    return []


def _effect_names(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {item for item in value if isinstance(item, str)}


def highest_effect(effects: Any) -> str:
    """Return the most dangerous effect in a collection, defaulting to read."""

    known = [
        effect
        for effect in (effects or ())
        if isinstance(effect, str) and effect in EFFECT_RANK
    ]
    if not known:
        return "read"
    return max(known, key=lambda effect: EFFECT_RANK[effect])
