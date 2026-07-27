"""Finish evidence validation for lightweight retrospective learning."""

from __future__ import annotations

import re

from agent_skill_catalog import NO_SKILL_IDS, normalize_skill_id, parse_skill_ids


RETROSPECTIVE_OUTCOMES = {
    "no_reusable_gap",
    "reusable_gap",
    "no_skill_used",
}
RETROSPECTIVE_OBSERVATION_STATES = {
    "not_needed",
    "recorded",
    "deferred",
}


def validate_retrospective_check(
    evidence: str,
    *,
    allowed_skill_ids: set[str] | None = None,
) -> list[str]:
    """Require an explicit skill check while keeping follow-up non-blocking."""

    text = evidence.strip()
    if not text:
        return ["retrospective check evidence is required"]

    skills_checked = _field(text, "skills checked")
    outcome = _field(text, "outcome").lower()
    observation = _field(text, "observation").lower()
    missing = [
        label
        for label, value in (
            ("skills checked", skills_checked),
            ("outcome", outcome),
            ("observation", observation),
        )
        if not value
    ]
    if missing:
        return [
            "retrospective check evidence must state " + ", ".join(missing)
        ]

    failures: list[str] = []
    if outcome not in RETROSPECTIVE_OUTCOMES:
        failures.append(
            "retrospective check outcome must be no_reusable_gap, "
            "reusable_gap, or no_skill_used"
        )
    if observation not in RETROSPECTIVE_OBSERVATION_STATES:
        failures.append(
            "retrospective check observation must be not_needed, recorded, or deferred"
        )
    if failures:
        return failures

    if outcome == "reusable_gap" and observation not in {"recorded", "deferred"}:
        failures.append(
            "retrospective check with reusable_gap must record or defer one skill observation"
        )
    if outcome in {"no_reusable_gap", "no_skill_used"} and observation != "not_needed":
        failures.append(
            f"retrospective check with {outcome} must use observation: not_needed"
        )
    normalized_skills = parse_skill_ids(skills_checked)
    if outcome == "no_skill_used" and skills_checked.lower() not in NO_SKILL_IDS:
        failures.append(
            "retrospective check with no_skill_used must set skills checked to none"
        )
    if outcome != "no_skill_used" and skills_checked.lower() in NO_SKILL_IDS:
        failures.append(
            "retrospective check must name the skill or skills evaluated"
        )
    if outcome != "no_skill_used":
        raw_skills = [item.strip() for item in skills_checked.split(",") if item.strip()]
        if not raw_skills or len(normalized_skills) != len(raw_skills) or any(
            not skill for skill in normalized_skills
        ):
            failures.append(
                "retrospective check skills checked must contain canonical skill slugs"
            )
        elif allowed_skill_ids is not None:
            unknown = [
                raw
                for raw, normalized in zip(raw_skills, normalized_skills)
                if normalize_skill_id(normalized) not in allowed_skill_ids
            ]
            if unknown:
                failures.append(
                    "retrospective check named unknown canonical skills: "
                    + ", ".join(unknown)
                )
    return failures


def _field(evidence: str, label: str) -> str:
    match = re.search(
        rf"(?:^|[;\n])\s*{re.escape(label)}\s*[:=]\s*([^;\n]+)",
        evidence,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""
