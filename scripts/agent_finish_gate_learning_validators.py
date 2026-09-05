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
}
# Every one of the 27 routes requires the `retrospective check` gate, and this
# is the skill that governs how to record it, so every run that reaches finish
# has used it whether or not its route listed the document. Leaving it out
# refused the one retrospective most likely to be true: the one about
# retrospectives.
ALWAYS_LOADED_SKILL_IDS = frozenset({"retrospective_learning"})


def validate_retrospective_check(
    evidence: str,
    *,
    allowed_skill_ids: set[str] | None = None,
    loaded_skill_ids: set[str] | None = None,
) -> list[str]:
    """Require an explicit skill check and same-closeout gap resolution."""

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
            "retrospective check observation must be not_needed or recorded"
        )
    if failures:
        return failures

    if outcome == "reusable_gap" and observation != "recorded":
        failures.append(
            "retrospective check with reusable_gap must record one skill observation "
            "before same-closeout maintenance"
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
        else:
            # Only ask which skills this run loaded once the names parse. A
            # list that is not yet canonical slugs has one mistake to fix, and
            # answering it with two failures sends the reader after the wrong
            # one first.
            if allowed_skill_ids is not None:
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
            failures.extend(
                _unloaded_skill_failures(normalized_skills, loaded_skill_ids)
            )
    return failures


def _unloaded_skill_failures(
    normalized_skills: list[str],
    loaded_skill_ids: set[str] | None,
) -> list[str]:
    """Require one named skill to be one this run actually loaded.

    The retrospective documents say the named skill must be one the agent
    "actually loaded and applied" in six places, and nothing enforced it: the
    only skill check proved the slug was *a* known bundle, which every bundle
    in the repository satisfies. A run could therefore close `no_reusable_gap`
    against skills it never opened, and across 140 recorded gate entries 69%
    took exactly that path.

    One overlap is the bar, not all of them. An agent may legitimately consult
    a skill the route did not require, and rejecting the extra names would
    punish the more thorough retrospective. What cannot stand is a list with no
    connection at all to what this run read.
    """

    if not loaded_skill_ids or not normalized_skills:
        # A route with no resolvable skill bundle gives nothing to check
        # against. Refusing here would block every such run on the strength of
        # missing evidence rather than wrong evidence.
        return []
    loaded = set(loaded_skill_ids) | ALWAYS_LOADED_SKILL_IDS
    if any(skill in loaded for skill in normalized_skills):
        return []
    return [
        "retrospective check must name at least one skill this run actually "
        "loaded; this run loaded " + ", ".join(sorted(loaded))
    ]


def _field(evidence: str, label: str) -> str:
    match = re.search(
        rf"(?:^|[;\n])\s*{re.escape(label)}\s*[:=]\s*([^;\n]+)",
        evidence,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""
