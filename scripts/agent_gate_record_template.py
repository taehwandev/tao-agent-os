"""Fill-in templates for gate records the gate hooks rejected.

Measured across real sessions, most failed gate-batch calls were argument
mistakes: a tests record without `check`/`result`, a tests result that named no
count or command, a retrospective record whose fields did not pair. The
rejection named the rule and left the agent to compose a valid record from
scratch, so the next call was often wrong again.

Everything here changes messages only. The templates are derived from the
validator's own schema (`FIELD_REQUIREMENTS`, `gate_field_enums`) so they cannot
advertise a field the check does not ask for, and nothing here decides whether a
record is accepted.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from agent_gate_evidence import FIELD_REQUIREMENTS, gate_field_enums


class GateRecordRejected(ValueError):
    """A pre-write rejection carrying copyable repair lines for the caller."""

    def __init__(self, message: str, hints: list[str]) -> None:
        super().__init__(message)
        self.hints = hints


_PLACEHOLDERS = {
    ("tests", "check"): "<command run>",
    ("tests", "result"): "<observed result>",
    ("retrospective check", "skills_checked"): "<canonical skill slugs this run loaded>",
}


def gate_record_template(gate: str, *, hook: str = "gate-batch", extra_fields: Iterable[str] = ()) -> str:
    """Return one copyable record for exactly this gate, every required field a placeholder."""

    names = list(dict.fromkeys([*FIELD_REQUIREMENTS.get(gate, ()), *extra_fields]))
    enums = gate_field_enums(gate)
    fields = {name: _placeholder(gate, name, enums) for name in names}
    if hook == "gate":
        flags = " ".join(f'--field "{name}={value}"' for name, value in fields.items())
        return f'fill-in template for {gate}: --gate-name "{gate}" {flags}'.rstrip()
    record = {"gate": gate, "status": "SUCCESS", "fields": fields}
    return f"fill-in template for {gate}: " + json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _placeholder(gate: str, name: str, enums: dict[str, tuple[str, ...]]) -> str:
    if name in enums:
        return "<" + "|".join(enums[name]) + ">"
    return _PLACEHOLDERS.get((gate, name), f"<{name.replace('_', ' ')}>")


def gate_value_hints(gate: str, failures: list[str], loaded_skills: Iterable[str] = ()) -> list[str]:
    """Name the exact field a content rule rejected and one valid value shape."""

    text = " ".join(failures).lower()
    if gate == "tests":
        return [
            'tests: put the falsifiable part in fields.result -- a count or exit status such as '
            '"result":"1163 tests passed, 0 failures" -- or the exact command in fields.check '
            'such as "check":"python3 -m unittest discover -s tests"'
        ]
    if gate != "retrospective check":
        return []
    hints: list[str] = []
    if "skill" in text:
        skills = ", ".join(sorted(loaded_skills)) or "agent_operating_skill"
        hints.append(
            "retrospective check: fields.skills_checked takes canonical slugs this run loaded, "
            f'not paths, such as "skills_checked":"{skills}"'
        )
    if "outcome" in text or "observation" in text:
        hints.append(
            "retrospective check: fields.outcome and fields.observation pair as "
            '"no_reusable_gap" + "not_needed", "no_skill_used" + "not_needed" '
            '(with "skills_checked":"none"), or "reusable_gap" + "recorded"'
        )
    if "efficiency" in text:
        hints.append(
            'retrospective check: fields.efficiency is "no_waste", "unmeasured" or '
            '"improvement_needed" and needs fields.efficiency_evidence such as '
            '"efficiency_evidence":"<what was measured>"; improvement_needed also needs '
            "efficiency_cause, efficiency_reduction and efficiency_verification"
        )
    return hints
