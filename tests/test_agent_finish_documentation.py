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


class RequiredDocDriftRecoveryTests(unittest.TestCase):
    """The recovery text must name the fields the receipt validator reads.

    It previously asked for `repair_evidence` and `resume_checkpoint`, which the
    validator never looks at, so an agent following it exactly could not clear
    the drift and reasonably concluded the check was unsatisfiable.
    """

    def setUp(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agent_finish_check_under_test", ROOT / "scripts" / "agent-finish-check.py"
        )
        assert spec and spec.loader
        self.finish_check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.finish_check)

    def _recovery(self, rules: Path, relative: str = "GUIDANCE.md") -> str:
        return self.finish_check._required_doc_drift_recovery(
            rules,
            [
                f"execution capsule required doc hash changed: {relative}",
                f"execution capsule required doc size changed: {relative}",
            ],
        )

    def test_it_names_every_field_the_receipt_validator_requires(self) -> None:
        from agent_execution_capsule_docs import validated_required_doc_update_receipt

        with tempfile.TemporaryDirectory() as directory:
            text = self._recovery(Path(directory))

        for field in (
            "artifact_receipt_version",
            "baseline_sha256",
            "final_sha256",
            "final_size_bytes",
        ):
            with self.subTest(field=field):
                self.assertIn(field, text)
        # The named version must be the one the validator accepts.
        self.assertIsNotNone(
            validated_required_doc_update_receipt(
                {
                    "artifact_receipt_version": "1",
                    "baseline_sha256": "a" * 64,
                    "final_sha256": "b" * 64,
                    "final_size_bytes": "10",
                }
            )
        )

    def test_it_offers_a_recovery_for_a_change_the_run_did_not_make(self) -> None:
        """The guidance must not leave a false claim as the only way out.

        A concurrent session can rewrite a shared required document while this
        run works. Naming only `decision=updated` told that run to assert an
        edit it never made, so the recovery has to name `unchanged` too and say
        the document must be re-read first.
        """

        with tempfile.TemporaryDirectory() as directory:
            text = self._recovery(Path(directory))

        self.assertIn("decision=unchanged", text)
        self.assertIn("another session", text)
        self.assertIn("re-read", text)
        self.assertIn("Do not claim decision=updated", text)

    def test_it_hands_over_the_current_bytes_rather_than_describing_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory)
            (rules / "GUIDANCE.md").write_text("# guidance\n", encoding="utf-8")

            text = self._recovery(rules)

        from agent_execution_capsule_state import doc_hash_record

        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory)
            path = rules / "GUIDANCE.md"
            path.write_text("# guidance\n", encoding="utf-8")
            record = doc_hash_record("GUIDANCE.md", path)

        self.assertIn(record["sha256"], text)
        self.assertIn(str(record["size_bytes"]), text)

    def test_a_relative_rules_root_still_yields_the_bytes(self) -> None:
        """Containment compares resolved paths, so a relative root read as an
        escape and silently dropped the values the guidance exists to give."""

        text = self.finish_check._required_doc_drift_recovery(
            Path("."),
            ["execution capsule required doc hash changed: AGENTS.md"],
        )

        self.assertIn("final_sha256=", text)

    def test_it_stays_silent_about_documents_that_did_not_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            text = self._recovery(Path(directory), relative="ONLY_THIS.md")

        self.assertIn("ONLY_THIS.md", text)
        self.assertNotIn("AGENTS.md", text)
