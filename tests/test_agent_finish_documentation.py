from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_execution_capsule import create_preflight_snapshot
from agent_finish_documentation import (
    documented_required_doc_updates,
    required_doc_target_failures,
)
from agent_gate_evidence import record_gate_evidence


class RequiredDocTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.route = {"required_docs": ["AGENTS.md"]}

    def test_exact_required_doc_target_is_allowed(self) -> None:
        self.assertEqual(
            [],
            required_doc_target_failures(target="AGENTS.md", route=self.route),
        )

    def test_combined_target_is_rejected_early(self) -> None:
        self.assertEqual(
            [
                "documentation target embeds route required_docs but is not one exact "
                "route-relative path: AGENTS.md; record one documentation SUCCESS "
                "entry per required doc"
            ],
            required_doc_target_failures(
                target="AGENTS.md; workflows/README.md",
                route=self.route,
            ),
        )

    def test_distinct_nested_path_with_same_basename_is_allowed(self) -> None:
        self.assertEqual(
            [],
            required_doc_target_failures(
                target="docs/AGENTS.md",
                route=self.route,
            ),
        )

    def test_path_with_required_doc_prefix_is_allowed(self) -> None:
        self.assertEqual(
            [],
            required_doc_target_failures(
                target="AGENTS.md.backup",
                route=self.route,
            ),
        )

    def test_each_documentation_record_authorizes_one_required_doc_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rules = Path(temp_dir).resolve()
            evidence_path = rules / "preflight.json"
            route = {
                "command": "docs",
                "gates": ["documentation"],
                "required_docs": [
                    "AGENTS.md",
                    "platforms/android/skills/source-coverage/SKILL.md",
                ],
            }
            for relative in route["required_docs"]:
                doc_path = rules / relative
                doc_path.parent.mkdir(parents=True, exist_ok=True)
                doc_path.write_text(f"# {relative}\n", encoding="utf-8")
            preflight = {
                "route": route,
                "rules": str(rules),
                "execution_snapshot": create_preflight_snapshot(
                    rules,
                    route,
                    {"request": "update the routed required docs"},
                ),
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")

            for target in route["required_docs"]:
                record_gate_evidence(
                    evidence_path=evidence_path,
                    preflight=preflight,
                    gate="documentation",
                    fields={
                        "decision": "updated",
                        "target": target,
                        "reason": "explicit required-doc migration",
                    },
                )

            self.assertEqual(
                set(route["required_docs"]),
                set(
                    documented_required_doc_updates(
                        evidence_path=evidence_path,
                        route=route,
                    )
                ),
            )


if __name__ == "__main__":
    unittest.main()
