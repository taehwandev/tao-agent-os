"""Bind post-finish publication to admitted effects and finished source bytes.

Owner: post-finish admission. Allowed: read-only input capture, atomic receipt.
Forbidden: execution of publication commands or inference of user authority.
Callers: finish and Claude pretool gate; tests: test_agent_publication_admission.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_evidence_inputs import EvidenceInputs
from agent_execution_capsule_state import atomic_write_json
from agent_route_state import request_fingerprint
from agent_runtime_session import resolve_runtime_evidence
from workflow_intent_envelope import EFFECT_RANK


class PublicationAdmission:
    # Publication covers the whole source tree, unlike a bounded local tests gate.
    _MAX_FILES = 20_000
    _MAX_BYTES = 1024 * 1024 * 1024

    @staticmethod
    def already_finished_same_request(
        project: Path,
        rules: Path,
        request_intake: dict,
        required_effect: str,
        session: dict[str, str],
    ) -> bool:
        """Avoid reopening an identical, still-admitted commit/PR action."""
        if required_effect not in EFFECT_RANK or not session.get('session_id'):
            return False
        try:
            evidence = resolve_runtime_evidence(
                project, session, frozenset({'completed'}), latest_of_several=True,
            )
            if evidence is None:
                return False
            prior = json.loads(evidence.read_text(encoding='utf-8'))
            if (
                prior.get('request_fingerprint') != request_fingerprint(request_intake)
                or prior.get('project') != str(project.resolve())
                or prior.get('rules') != str(rules.resolve())
                or (prior.get('route') or {}).get('command') != 'commit'
            ):
                return False
            return PublicationAdmission.allows(project, evidence, required_effect)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return False

    @staticmethod
    def _capture(root: Path) -> str:
        return EvidenceInputs.capture(
            root, [], max_files=PublicationAdmission._MAX_FILES,
            max_bytes=PublicationAdmission._MAX_BYTES,
        )

    @staticmethod
    def record_finish(project: Path, evidence: Path, failure_reason: list[str] | None = None) -> bool:
        """Capture an optional receipt; absence never grants publication."""
        try:
            payload = json.loads(evidence.read_text())
            decision = payload['route']['request_classification']['intent_envelope']
            effect = decision['effective_effect']
            if (decision.get('authority') != 'envelope' or not decision.get('schema_valid')
                    or decision.get('failures') != [] or effect not in EFFECT_RANK
                    or EFFECT_RANK[effect] < EFFECT_RANK['git_write']):
                return False
            rules = Path(payload['rules']).resolve()
            receipt = {
                'schema_version': 1,
                'evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                'effect': effect,
                'project': str(project.resolve()),
                'rules': str(rules),
                'project_content': PublicationAdmission._capture(project.resolve()),
                'rules_content': PublicationAdmission._capture(rules),
            }
            atomic_write_json(evidence.with_name('publication.json'), receipt)
            return True
        except ValueError as error:
            if failure_reason is not None and str(error) in {
                'input snapshot exceeds file limit', 'input snapshot exceeds byte limit',
            }:
                failure_reason.append(str(error))
            return False
        except (OSError, RuntimeError, KeyError, TypeError):
            return False

    @staticmethod
    def allows(project: Path, evidence: Path, required_effect: str) -> bool:
        return not PublicationAdmission.refusal(project, evidence, required_effect)

    @staticmethod
    def refusal(project: Path, evidence: Path, required_effect: str) -> str:
        """Name the first check a receipt fails, or return "" when it admits the effect.

        The checks and their order are exactly what admission requires, so the
        denial can say which one failed instead of listing every possibility.
        Values are enum words or content-free labels, never paths or digests.
        """
        try:
            receipt = json.loads(evidence.with_name('publication.json').read_text())
            rules = Path(receipt['rules'])
        except FileNotFoundError:
            return 'missing_receipt'
        except (OSError, ValueError, KeyError, TypeError):
            return 'unreadable_receipt'
        try:
            if (receipt.get('schema_version') != 1
                    or receipt['project'] != str(project.resolve())
                    or receipt['evidence_sha256'] != hashlib.sha256(evidence.read_bytes()).hexdigest()):
                return 'foreign_receipt'
            if EFFECT_RANK[receipt['effect']] < EFFECT_RANK[required_effect]:
                return f"effect:{receipt['effect']}<{required_effect}"
            if receipt['project_content'] != PublicationAdmission._capture(project.resolve()):
                return 'project_changed'
            if receipt['rules_content'] != PublicationAdmission._capture(rules):
                return 'rules_changed'
            return ''
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return 'unverifiable_receipt'
