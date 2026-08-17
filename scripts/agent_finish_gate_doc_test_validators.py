"""Documentation and test finish gate validators."""

from __future__ import annotations

import re

from agent_finish_gate_skip_policy import _evidence_records_skip_reason
from agent_finish_gate_validators import (
    DOC_COVERAGE_STATE_PHRASES,
    DOC_INSPECTION_PROOF_PHRASES,
    NO_DOC_DECISIONS,
    accepted,
    UNCHANGED_DECISIONS,
    _explicit_documentation_decision,
    _has_durable_doc_change_signal,
    _unchanged_evidence_is_grounded,
    documentation_decision_has_any,
    has_any,
)


DOCUMENTATION_EVIDENCE_REQUIRED = (
    "documentation evidence is required and cannot be empty: name the "
    "documentation decision (updated/created/unchanged), the affected "
    "source-of-truth doc path, and why that decision matches the change"
)

# Skipping documentation is never self-approved. When the agent believes docs
# should truly not be written, it must ask the user ("문서를 스킵할까요?" /
# "Should I skip the doc?") and record their explicit approval. A reason alone
# is not enough — these phrases prove the human review happened.
DOC_SKIP_APPROVAL_PHRASES = (
    "user approved", "user confirmed", "user agreed", "user reviewed and approved",
    "approved skipping", "approved the skip", "skip approved by",
    "user said skip", "user asked to skip", "user chose to skip",
    "human approved", "operator approved", "confirmed with the user to skip",
    "user approved skipping",
    "사용자 승인", "사용자가 승인", "사용자 확인", "사용자 검토 후",
    "검토받아", "검토받고", "스킵 승인", "문서 스킵 승인", "물어보고 승인",
    "사용자에게 확인받",
)

DOCUMENTATION_SKIP_NEEDS_APPROVAL = (
    "documentation cannot be skipped (not-applicable/no-docs/skipped) on the "
    "agent's own judgment or a reason alone: ask the user '문서를 스킵할까요?' / "
    "'Should I skip the doc?', get explicit approval, and record that approval "
    "in the evidence — otherwise write the doc"
)


def validate_documentation(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return [DOCUMENTATION_EVIDENCE_REQUIRED]
    has_decision = any(
        phrase in text
        for phrase in (
            "updated",
            "created",
            "added",
            "not applicable",
            "unchanged",
            "no doc update",
            "no docs update",
            "docs unchanged",
            "source-of-truth updated",
            "source of truth updated",
        )
    )
    names_target = any(
        phrase in text
        for phrase in (
            ".md",
            "readme",
            "agents",
            "prd",
            "spec",
            "ard",
            "runbook",
            "wiki",
            "source-of-truth",
            "source of truth",
            "docs/",
            "workflows/",
            "common/",
            "platforms/",
            "product-patterns/",
        )
    )
    explains_reason = any(
        phrase in text
        for phrase in (
            "because",
            "reason",
            "why",
            "due to",
            "changed",
            "no durable",
            "no user-visible",
            "workflow policy",
            "public contract",
            "acceptance criteria",
            "behavior",
            "architecture",
            "operator action",
            "왜",
            "이유",
            "변경",
            "문서 영향",
        )
    )
    if documentation_decision_has_any(text, NO_DOC_DECISIONS) and _has_durable_doc_change_signal(text):
        return [
            "documentation evidence cannot use not-applicable/no-docs when it "
            "also names a durable planning, requirements, acceptance, workflow "
            "policy, public contract, operator, architecture, API, release, or "
            "test-plan change"
        ]
    if _is_documentation_skip_decision(text) and not has_any(text, DOC_SKIP_APPROVAL_PHRASES):
        return [DOCUMENTATION_SKIP_NEEDS_APPROVAL]
    if documentation_decision_has_any(text, UNCHANGED_DECISIONS) and not _unchanged_evidence_is_grounded(text):
        return [
            "documentation evidence can use unchanged only when it names the "
            "existing doc path it opened/inspected and states why that "
            "already-read doc covers the planning, behavior, contract, or "
            "acceptance change; a bare coverage claim is not enough."
            + accepted(DOC_INSPECTION_PROOF_PHRASES).replace(
                "accepted wording includes", "inspection proof is recognised on"
            )
            + accepted(DOC_COVERAGE_STATE_PHRASES, limit=6).replace(
                "accepted wording includes", "and the coverage claim on"
            )
        ]
    if has_decision and names_target and explains_reason:
        return []
    return [
        "documentation evidence must name the documentation decision "
        "(updated/created/unchanged/not applicable), the affected source-of-truth "
        "doc path or doc class, and why that decision matches the behavior, "
        "workflow policy, public contract, or durable acceptance criteria changed"
    ]


def _is_documentation_skip_decision(text: str) -> bool:
    """True when the documentation evidence declares a skip: an explicit
    not-applicable/no-docs decision or any recorded skip/생략 reason."""
    explicit = _explicit_documentation_decision(text)
    if explicit is not None:
        return has_any(explicit, NO_DOC_DECISIONS)
    return has_any(text, NO_DOC_DECISIONS) or _evidence_records_skip_reason(text)


# validate_tests renders these in its refusal, so the wording it accepts and the
# wording it advertises cannot drift apart.
TEST_SIGNAL_PHRASES = (
    "test", "pytest", "unittest", "unit", "integration", "regression",
    "smoke", "verification", "manual", "not applicable",
)
TEST_PASSED_PHRASES = (
    "passed", "pass", "0 failures", "no failures", "green", "성공", "통과",
)

# A pass word on its own is not a result: "통과" and "passed" are equally true of
# a suite that never ran, which is how a finish gate reports SUCCESS for work
# whose checks were never executed. This gate cannot run the project's suite, so
# it requires the claim to be falsifiable by whoever reads it -- either an
# outcome the run produced (exit status, or a count of tests/cases/failures/
# findings) or the concrete command or selector that produced it, which a reader
# can rerun.
_TEST_RESULT_RE = re.compile(
    r"(?:exit|return|returncode|status|rc)\s*(?:code|status)?\s*[:=]?\s*\d+"
    r"|\d+\s*(?:tests?|cases?|specs?|scenarios?|assertions?|failures?|errors?|"
    r"issues?|findings?|violations?|warnings?|개|건)"
    r"|(?:tests?|cases?|specs?|failures?|errors?|issues?|findings?)\s*[:=]\s*\d+"
    r"|\bok\s*\(?\s*\d+"
)
_TEST_COMMAND_RE = re.compile(
    r"\b(?:gradlew|pytest|unittest|jest|vitest|mocha|rspec|phpunit|mvn|make|"
    r"cargo|xcodebuild|swift\s+test|go\s+test|npm\s+(?:run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|detekt|ktlint|eslint|mypy|ruff|tsc)\b"
    r"|[\w.-]+/[\w./-]*\btest[\w./-]*"
    r"|\btest[\w.-]*\.(?:py|kt|kts|swift|ts|tsx|js|jsx|rb|go|java|cs)\b"
    r"|\b[\w.-]+_test\.[a-z]+\b"
    r"|\b[\w.-]+(?:test|spec)s?\b\s*(?:::|#|\.)\s*\w+"
)

TESTS_RESULT_REQUIRED = (
    "tests evidence claims a check ran but is not falsifiable: name either the "
    "result it produced (exit status, or a count such as \"1163 tests\", "
    "\"tests: 0 failures\") or the exact command/selector that ran "
    "(such as \"unittest discover -s tests\", \"./gradlew testDebugUnitTest\"). A "
    "pass word alone is equally true of a suite that never ran"
)


def validate_tests(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_test_signal = any(phrase in text for phrase in TEST_SIGNAL_PHRASES)
    skipped = any(phrase in text for phrase in ("skipped", "not run", "unable", "cannot run"))
    explained_skip = any(
        phrase in text
        for phrase in (
            "because", "reason", "not applicable", "docs-only", "no useful test",
            "by design", "environment-gated", "environment gated", "intentional",
            "설계", "의도", "환경",
        )
    )
    # A suite that ran and passed is a named test run even when it mentions
    # skipped subtests; the skip guard is for runs that never happened.
    ran_and_passed = any(phrase in text for phrase in TEST_PASSED_PHRASES)
    if has_test_signal and (not skipped or explained_skip or ran_and_passed):
        if (
            _claims_a_run(text, skipped, explained_skip)
            and not _TEST_RESULT_RE.search(text)
            and not _TEST_COMMAND_RE.search(text)
        ):
            return [TESTS_RESULT_REQUIRED]
        return []
    return [
        "tests evidence must name the test/check run or explain skipped/not-applicable tests with a reason."
        + accepted(TEST_SIGNAL_PHRASES)
        + accepted(TEST_PASSED_PHRASES, limit=6).replace(
            "accepted wording includes", "a run that passed also clears it on"
        )
    ]


def _claims_a_run(text: str, skipped: bool, explained_skip: bool) -> bool:
    """True when the evidence asserts a check executed rather than was waived.

    An approved skip and a not-applicable decision owe no result, so the outcome
    requirement applies only to the positive claim.
    """

    if "not applicable" in text:
        return False
    return not (skipped and explained_skip)
