"""Bind post-finish publication to admitted effects and finished source bytes.

Owner: post-finish admission. Allowed: read-only input capture, atomic receipt.
Forbidden: execution of publication commands or inference of user authority.
Callers: finish and Claude pretool gate; tests: test_agent_publication_admission.
"""

import hashlib
import json
from pathlib import Path

from agent_evidence_inputs import EvidenceInputs
from agent_execution_capsule_state import atomic_write_json
from workflow_intent_envelope import EFFECT_RANK


class PublicationAdmission:
    @staticmethod
    def record_finish(project: Path, evidence: Path) -> bool:
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
                'project_content': EvidenceInputs.capture(project.resolve(), []),
                'rules_content': EvidenceInputs.capture(rules, []),
            }
            atomic_write_json(evidence.with_name('publication.json'), receipt)
            return True
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return False

    @staticmethod
    def allows(project: Path, evidence: Path, required_effect: str) -> bool:
        try:
            receipt = json.loads(evidence.with_name('publication.json').read_text())
            rules = Path(receipt['rules'])
            return (
                receipt.get('schema_version') == 1
                and receipt['project'] == str(project.resolve())
                and receipt['evidence_sha256'] == hashlib.sha256(evidence.read_bytes()).hexdigest()
                and EFFECT_RANK[receipt['effect']] >= EFFECT_RANK[required_effect]
                and receipt['project_content'] == EvidenceInputs.capture(project.resolve(), [])
                and receipt['rules_content'] == EvidenceInputs.capture(rules, [])
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return False
