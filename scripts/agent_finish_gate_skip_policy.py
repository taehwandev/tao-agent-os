"""Skip and unresolved-issue guards for required finish gates."""

from __future__ import annotations

from agent_finish_gate_validators import accepted, triggers

# The refusal message renders these, so the wording a validator accepts and the
# wording it advertises cannot drift apart.
_SKIP_PHRASES = (
    "skipped because", "skipped due", "skipped:", "was skipped", "gate skipped",
    "verification skipped", "check skipped", "test skipped", "docs skipped",
    "review skipped", "skip because", "skip reason", "skip/not",
    "recording a skip", "deferred until", "deferred to", "will do later",
    "스킵", "생략", "해당 없음", "미실행",
)
_RESOLVED_PHRASES = (
    "no unresolved", "none unresolved", "no known issue", "no blocking issue",
    "none found", "resolved", "없음", "해결",
)


def validate_required_gate_not_skipped(
    gate: str,
    evidence: str,
    skip_allowed_gates: set[str],
) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    failures: list[str] = []
    has_skip = _evidence_records_skip_reason(text)
    if has_skip and gate not in skip_allowed_gates:
        failures.append(
            f"{gate} evidence cannot pass by recording a skip/not-applicable reason; "
            "complete the required gate or report FAIL and run missed-gate recovery."
            + triggers(text, _SKIP_PHRASES)
        )

    if _evidence_names_unresolved_issue(text):
        failures.append(
            f"{gate} evidence names an unresolved issue; required gates must fail instead of "
            "passing with a deferred fix. State that nothing is outstanding instead."
            + accepted(_RESOLVED_PHRASES)
        )
    return failures


def _evidence_records_skip_reason(text: str) -> bool:
    if any(phrase in text for phrase in _SKIP_PHRASES):
        return True

    leading_skip_reasons = (
        "not applicable",
        "not run",
        "did not run",
        "unable to run",
        "unable to complete",
        "unable because",
        "cannot run",
        "cannot complete",
        "can't run",
        "can't complete",
    )
    normalized = text.strip()
    if normalized.startswith(leading_skip_reasons):
        return True
    if any(f"; {phrase}" in text or f"\n{phrase}" in text for phrase in leading_skip_reasons):
        return True

    scoped_skip_phrases = (
        "gate not applicable",
        "gate not run",
        "gate not checked",
        "gate not reviewed",
        "evidence not applicable",
        "evidence not checked",
        "verification not run",
        "verification not checked",
        "check not run",
        "check not checked",
        "test not run",
        "docs not checked",
        "review not run",
        "review not checked",
        "넘어감",
        "실행 안",
        "실행 못",
        "확인 안",
        "못함",
        "못 함",
    )
    return any(phrase in text for phrase in scoped_skip_phrases)


def _evidence_names_unresolved_issue(text: str) -> bool:
    no_unresolved = any(phrase in text for phrase in _RESOLVED_PHRASES)
    if no_unresolved:
        return False
    return any(
        phrase in text
        for phrase in (
            "must fix:",
            "must fix -",
            "needs fix",
            "needs to be fixed",
            "should fix:",
            "should fix -",
            "should fix later",
            "must fix later",
            "needs fix later",
            "should be fixed",
            "unresolved issue",
            "unresolved:",
            "not fixed",
            "left unfixed",
            "fix later",
            "follow-up required",
            "known issue remains",
            "known issue left",
            "known issue:",
            "blocking issue",
            "고쳐야",
            "수정 필요",
            "미해결",
            "남겨",
            "후속",
            "문제 있음",
        )
    )
