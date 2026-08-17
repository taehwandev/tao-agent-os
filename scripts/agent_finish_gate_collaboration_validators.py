"""Collaboration and workspace finish gate validators."""

from __future__ import annotations

from agent_finish_gate_validators import accepted


def _has_concrete_serial_reason(text: str) -> bool:
    return any(phrase in text for phrase in SERIAL_REASON_PHRASES)


# Named so the same phrases can be stated before the work as well as after a
# refusal: a serial decision is refused for its reason, not its mode, and that
# distinction is invisible until finish rejects a truthful sentence.
SERIAL_REASON_PHRASES = (
    "small",
    "작은 작업",
    "single-file",
    "same-file",
    "same file",
    "단일 파일",
    "같은 파일",
    "contract",
    "계약",
    "unstable",
    "overlap",
    "겹침",
    "중복",
    "dirty worktree",
    "dirty working tree",
    "migration",
    "dependency",
    "순서 의존",
    "동일 외부 상태",
    "release",
    "not applicable",
    "not safe",
)


def validate_multi_agent(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    serial = any(
        phrase in text
        for phrase in (
            "serial",
            "single-agent",
            "single agent",
            "직렬",
            "단일 에이전트",
            "단일에이전트",
            "not applicable",
            "no subagent",
            "no sub-agent",
            "no parallel",
            "no worker",
            "no workers",
            "워커 없음",
            "워커 불필요",
            "병렬 안 함",
            "병렬하지 않",
        )
    )
    parallel = any(
        phrase in text
        for phrase in (
            "multi-agent",
            "subagent",
            "sub-agent",
            "parallel",
            "병렬",
            "병렬화",
            "split",
            "worker",
            "워커",
        )
    )
    has_serial_reason = _has_concrete_serial_reason(text)
    if serial and has_serial_reason:
        return []
    has_owned = any(phrase in text for phrase in ("owned", "owner", "scope", "소유 범위", "담당 범위"))
    has_forbidden = any(
        phrase in text
        for phrase in ("forbidden", "do not touch", "excluded", "금지 범위", "건드리지 않을 범위")
    )
    has_contract = any(
        phrase in text for phrase in ("contract", "brief", "input", "output", "계약", "브리프", "입력", "출력")
    )
    has_acceptance = any(
        phrase in text
        for phrase in (
            "acceptance",
            "acceptance check",
            "acceptance criteria",
            "done means",
            "인수 조건",
            "완료 조건",
            "수용 기준",
        )
    )
    has_integration_owner = (
        (("integration" in text or "통합" in text)
         and any(phrase in text for phrase in ("owner", "lead", "integrator", "담당", "리드")))
        or "integration_owner" in text
        or "integration owner" in text
        or "통합 담당" in text
    )
    has_verification = any(
        phrase in text
        for phrase in (
            "verification",
            "verify",
            "test",
            "check",
            "manual",
            "smoke",
            "검증",
            "테스트",
            "확인",
        )
    )
    if (
        parallel
        and has_owned
        and has_forbidden
        and has_contract
        and has_acceptance
        and has_integration_owner
        and has_verification
    ):
        return []
    return [
        "multi-agent split decision evidence must state either serial/single-agent with a concrete "
        "reason, or parallel/subagent work with owned scope, forbidden scope, contract/brief, "
        "acceptance checks, integration owner, and verification."
        " For the serial reason," + accepted(SERIAL_REASON_PHRASES)
    ]


def validate_multi_agent_roles(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_lead = "lead" in text or "owner" in text
    has_worker_or_verifier = any(phrase in text for phrase in ("worker", "builder", "verifier", "reviewer"))
    if has_lead and has_worker_or_verifier:
        return []
    return ["roles evidence must name the lead/owner role and worker/builder/verifier roles"]


def validate_multi_agent_write_scopes(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_owned = any(phrase in text for phrase in ("owned", "owner", "write scope", "writes:", "scope:"))
    has_forbidden = any(
        phrase in text for phrase in ("forbidden", "do not touch", "excluded", "read-only", "readonly")
    )
    if has_owned and has_forbidden:
        return []
    return ["write scopes evidence must name owned write scope and forbidden/read-only scope"]


def validate_multi_agent_briefs(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    checks = {
        "worker": any(phrase in text for phrase in ("worker", "agent", "task id")),
        "role": "role" in text,
        "owned": any(phrase in text for phrase in ("owned", "scope")),
        "forbidden": any(phrase in text for phrase in ("forbidden", "do not touch", "excluded")),
        "contract": any(phrase in text for phrase in ("contract", "input", "expected output", "output")),
        "acceptance": "acceptance" in text,
        "verification": any(phrase in text for phrase in ("verification", "verify", "test", "check", "smoke")),
    }
    if all(checks.values()):
        return []
    missing = ", ".join(name for name, present in checks.items() if not present)
    return [
        "agent briefs evidence must include worker id, role, owned scope, forbidden scope, "
        f"contract/output, acceptance checks, and verification; missing: {missing}"
    ]


def validate_multi_agent_integration_review(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_integration = any(phrase in text for phrase in ("integration", "merged", "merge", "combined"))
    has_contract = any(phrase in text for phrase in ("contract", "drift", "schema", "route", "state model", "config"))
    has_final_check = any(
        phrase in text for phrase in ("verification", "verify", "test", "check", "smoke", "final")
    )
    if has_integration and has_contract and has_final_check:
        return []
    return ["integration review evidence must name integration/merge review, contract-drift check, and final verification"]


def validate_workspace_scope_checkpoint(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    has_primary = any(
        phrase in text
        for phrase in (
            "starting primary",
            "primary repo",
            "primary:",
            "primary=",
            "시작 primary",
            "기준 repo",
        )
    )
    has_secondary = any(
        phrase in text
        for phrase in (
            "secondary repo",
            "secondary:",
            "secondary=",
            "source of truth",
            "new source",
            "추가 repo",
            "소스 오브 트루스",
        )
    )
    has_mode = any(
        phrase in text
        for phrase in (
            "single-repo",
            "single_repo",
            "primary-led",
            "primary_led",
            "secondary read",
            "secondary write",
            "multi-session",
            "multi_session",
            "mode:",
            "mode=",
            "모드",
        )
    )
    has_verification = any(
        phrase in text
        for phrase in (
            "verification",
            "verify",
            "test",
            "smoke",
            "check",
            "검증",
            "테스트",
        )
    )
    if has_primary and has_secondary and has_mode and has_verification:
        return []
    return [
        "workspace scope checkpoint evidence must state the starting primary repo, "
        "secondary/source-of-truth repo, chosen mode, and cross-repo verification before "
        "writing to a secondary repo"
    ]
