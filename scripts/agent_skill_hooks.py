"""Thin non-blocking CLI adapters for the skill-learning lifecycle."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_hook_gate_records import preflight_evidence_path
from agent_hook_runtime import finish_with_result
from agent_skill_feedback import (
    record_skill_curation,
    record_skill_feedback,
    record_skill_maintenance,
    record_skill_review,
)


def skill_feedback_hook(args: Any) -> int:
    feedback, details = record_skill_feedback(
        project=args.project,
        rules=getattr(args, "rules", Path(__file__).resolve().parents[1]),
        evidence_path=preflight_evidence_path(args),
        outcome=args.skill_feedback_outcome,
        skill_id=args.skill_id,
        signal=args.feedback_signal,
    )
    return finish_with_result(
        "skill-feedback", True, details, args.output, {"skill_feedback": feedback}, 0
    )


def skill_review_hook(args: Any) -> int:
    review, details = record_skill_review(
        candidate_id=args.feedback_candidate_id,
        decision=args.skill_review_outcome,
        gap_type=args.feedback_gap,
        change_type=args.change_type,
        promotion_target=args.promotion_target,
    )
    return finish_with_result(
        "skill-review", True, details, args.output, {"skill_review": review}, 0
    )


def skill_curate_hook(args: Any) -> int:
    curation, details = record_skill_curation()
    return finish_with_result(
        "skill-curate", True, details, args.output, {"skill_curation": curation}, 0
    )


def skill_maintenance_hook(args: Any) -> int:
    maintenance, details = record_skill_maintenance(
        project=args.project,
        rules=args.rules,
        candidate_id=args.feedback_candidate_id,
        outcome=args.skill_maintenance_outcome,
        verification_kind=args.verification_kind,
        target=args.maintenance_target,
        test_selector=args.maintenance_test_selector,
    )
    return finish_with_result(
        "skill-maintenance", True, details, args.output,
        {"skill_maintenance": maintenance}, 0,
    )
