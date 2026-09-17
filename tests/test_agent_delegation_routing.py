from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_delegation_plan import validate_delegation_plan_structure
from agent_gate_evidence import (
    gate_evidence_path_for_preflight,
    incomplete_gate_evidence_failures,
    merge_gate_evidence_from_ledger,
    missing_structured_gate_fields,
    record_many_gate_evidence,
)
from agent_hook_gate_records import record_hook_gate_batch
from support.runtime_bridge import (
    AUTO_DELEGATION_BRIDGE_PHRASE,
    CODEX_DISPATCH_BRIDGE_PHRASE,
    RUNTIME_NATIVE_DELEGATION_PHRASES,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from workflow_gate_policy import MULTI_AGENT_GATE
from workflow_common import SCOPE_CHANGE_LIFECYCLE_COMMANDS
from workflow_parallel import parallel_execution_plan
from workflow_route import resolve_docs


MULTI_AGENT_SKILL = "workflows/skills/multi-agent-collaboration/SKILL.md"


def valid_delegation_plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "parallel",
        "workers": [
            {
                "id": "finish-a",
                "role": "finish investigator",
                "owned_scope": ["scripts/agent_finish_*"],
                "forbidden_scope": ["all edits"],
                "contract": "trace validation flow",
                "acceptance": ["report paths and symbols"],
                "verification": ["focused unittest"],
            }
        ],
        "integration_review": {
            "owner": "root lead agent",
            "contract_drift_check": "compare gate and plan schema",
            "final_verification": ["focused unittest"],
        },
    }


def guidance_area(path: str) -> str:
    """The skill bundle a document belongs to, entrypoint or reference alike."""
    canonical = canonical_doc_path(path)
    for suffix in ("/references/current-guidance.md", "/SKILL.md"):
        if canonical.endswith(suffix):
            return canonical[: -len(suffix)]
    return canonical


def routed_areas(route: dict) -> set[str]:
    """Guidance areas the route puts in front of the agent, required or not.

    Required-doc membership is budget-bounded, so a surface match that fires
    may leave its lower-ranked areas in `reference_docs` rather than
    `required_docs`. Both are routed; only the first is mandatory reading.
    """
    return {
        guidance_area(doc)
        for doc in [*route["required_docs"], *route["reference_docs"]]
    }


class DelegationEvidenceTests(unittest.TestCase):
    def test_parallel_gate_reports_all_structured_fields_in_one_pass(self) -> None:
        missing = missing_structured_gate_fields(
            MULTI_AGENT_GATE,
            "",
            {
                "mode": "parallel",
                "reason": "disjoint stable scopes",
            },
        )

        self.assertEqual(
            [
                "verification",
                "owned_scope",
                "forbidden_scope",
                "contract",
                "acceptance",
                "integration_owner",
            ],
            missing,
        )

    def test_gate_batch_rejects_incomplete_parallel_record_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps({"route": {"gates": [MULTI_AGENT_GATE]}}),
                encoding="utf-8",
            )
            (project / ".tao" / "agent-delegation-plan.json").write_text(
                json.dumps(valid_delegation_plan()),
                encoding="utf-8",
            )
            args = SimpleNamespace(evidence=evidence_path, project=project)
            records = [
                {
                    "gate": MULTI_AGENT_GATE,
                    "status": "SUCCESS",
                    "source": "manual",
                    "evidence": "",
                    "fields": {
                        "mode": "parallel",
                        "reason": "disjoint stable scopes",
                        "owned_scope": "scripts/agent_finish_*",
                        "forbidden_scope": "all edits",
                        "contract_brief": "trace finish validation",
                        "acceptance_checks": "report paths and symbols",
                        "integration_owner": "root lead agent",
                        "verification": "focused unittest",
                    },
                }
            ]

            with self.assertRaisesRegex(ValueError, "contract, acceptance"):
                record_hook_gate_batch(args, records)

            self.assertFalse(gate_evidence_path_for_preflight(evidence_path).exists())

    def test_gate_batch_rejects_non_serial_mode_missing_parallel_fields_before_writing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps({"route": {"gates": [MULTI_AGENT_GATE]}}),
                encoding="utf-8",
            )
            (project / ".tao" / "agent-delegation-plan.json").write_text(
                json.dumps(valid_delegation_plan()),
                encoding="utf-8",
            )
            args = SimpleNamespace(evidence=evidence_path, project=project)
            records = [
                {
                    "gate": MULTI_AGENT_GATE,
                    "status": "SUCCESS",
                    "source": "manual",
                    "evidence": "",
                    "fields": {
                        "mode": "delegated",
                        "reason": "disjoint scopes",
                        "verification": "focused unittest",
                    },
                }
            ]

            with self.assertRaisesRegex(
                ValueError,
                "owned_scope, forbidden_scope, contract, acceptance, integration_owner",
            ):
                record_hook_gate_batch(args, records)

            self.assertFalse(gate_evidence_path_for_preflight(evidence_path).exists())

    def test_gate_batch_rejects_whitespace_only_parallel_fields_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps({"route": {"gates": [MULTI_AGENT_GATE]}}),
                encoding="utf-8",
            )
            args = SimpleNamespace(evidence=evidence_path, project=project)
            records = [
                {
                    "gate": MULTI_AGENT_GATE,
                    "status": "SUCCESS",
                    "source": "manual",
                    "evidence": "",
                    "fields": {
                        "mode": "parallel",
                        "reason": " ",
                        "verification": " ",
                        "owned_scope": " ",
                        "forbidden_scope": " ",
                        "contract": " ",
                        "acceptance": " ",
                        "integration_owner": " ",
                    },
                }
            ]

            with self.assertRaisesRegex(ValueError, "reason, verification, owned_scope"):
                record_hook_gate_batch(args, records)

            self.assertFalse(gate_evidence_path_for_preflight(evidence_path).exists())

    def test_gate_batch_cli_rejects_invalid_evidence_without_retry_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps({"route": {"gates": [MULTI_AGENT_GATE]}}),
                encoding="utf-8",
            )
            record = {
                "gate": MULTI_AGENT_GATE,
                "status": "SUCCESS",
                "fields": {
                    "mode": "delegated",
                    "reason": "disjoint scopes",
                    "verification": "focused unittest",
                },
            }

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-hook.py"),
                    "gate-batch",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--gate-record",
                    json.dumps(record),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing required fields", output)
            self.assertNotIn("retrospective", output.lower())
            self.assertNotIn("retry", output.lower())
            self.assertFalse(gate_evidence_path_for_preflight(evidence_path).exists())

    def test_gate_batch_accepts_complete_parallel_record_as_finish_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            route = {"gates": [MULTI_AGENT_GATE]}
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            (project / ".tao" / "agent-delegation-plan.json").write_text(
                json.dumps(valid_delegation_plan()),
                encoding="utf-8",
            )
            args = SimpleNamespace(evidence=evidence_path, project=project)
            fields = {
                "mode": "parallel",
                "reason": "lead and worker own disjoint stable slices",
                "owned_scope": "worker owns finish validation analysis",
                "forbidden_scope": "worker cannot edit shared contracts",
                "contract": "report finish validation findings",
                "acceptance": "findings name paths and symbols",
                "integration_owner": "root lead agent",
                "verification": "focused unittest",
            }

            entries = record_hook_gate_batch(
                args,
                [
                    {
                        "gate": MULTI_AGENT_GATE,
                        "status": "SUCCESS",
                        "source": "manual",
                        "evidence": "",
                        "fields": fields,
                    }
                ],
            )
            merged, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

            self.assertEqual(1, len(entries))
            self.assertEqual({}, diagnostics["missing_fields"])
            for expected in (
                fields["owned_scope"],
                fields["forbidden_scope"],
                fields["contract"],
                fields["acceptance"],
                fields["integration_owner"],
                fields["verification"],
            ):
                self.assertIn(expected, merged[MULTI_AGENT_GATE])

    def test_delegation_plan_reports_every_worker_and_integration_omission(self) -> None:
        plan = {
            "schema_version": 1,
            "mode": "parallel",
            "workers": [{"id": "finish-a", "role": "investigator", "owned_scope": ["scripts"]}],
            "integration_review": {},
        }

        failures = validate_delegation_plan_structure(plan)

        self.assertTrue(any("forbidden_scope" in failure for failure in failures))
        self.assertTrue(any("missing contract" in failure for failure in failures))
        self.assertTrue(any("acceptance" in failure for failure in failures))
        self.assertTrue(any("verification" in failure for failure in failures))
        self.assertTrue(any("owner/integration_owner" in failure for failure in failures))
        self.assertTrue(any("contract_drift_check" in failure for failure in failures))
        self.assertTrue(any("final_verification" in failure for failure in failures))

    def test_legacy_ledger_diagnostics_expose_all_missing_fields(self) -> None:
        failures = incomplete_gate_evidence_failures(
            {
                "missing_fields": {
                    MULTI_AGENT_GATE: [
                        "verification",
                        "owned_scope",
                        "forbidden_scope",
                        "contract",
                        "acceptance",
                        "integration_owner",
                    ]
                }
            }
        )

        self.assertEqual(1, len(failures))
        for field in (
            "verification",
            "owned_scope",
            "forbidden_scope",
            "contract",
            "acceptance",
            "integration_owner",
        ):
            self.assertIn(field, failures[0])

    def test_corrected_gate_record_clears_legacy_missing_field_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            route = {"gates": [MULTI_AGENT_GATE]}
            preflight = {"route": route}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            complete_fields = {
                "mode": "parallel",
                "reason": "disjoint stable scopes",
                "owned_scope": "scripts/finish and scripts/workflow",
                "forbidden_scope": "unrelated files",
                "contract": "preserve the finish and routing contracts",
                "acceptance": "focused regression tests pass",
                "integration_owner": "root lead agent",
                "verification": "focused unittest",
            }
            record_many_gate_evidence(
                evidence_path=evidence_path,
                preflight=preflight,
                records=[
                    {
                        "gate": MULTI_AGENT_GATE,
                        "status": "SUCCESS",
                        "fields": {"mode": "parallel", "reason": "legacy incomplete record"},
                    },
                    {
                        "gate": MULTI_AGENT_GATE,
                        "status": "SUCCESS",
                        "fields": complete_fields,
                    },
                ],
            )

            merged, diagnostics = merge_gate_evidence_from_ledger(
                route=route,
                evidence_path=evidence_path,
            )

            self.assertIn(MULTI_AGENT_GATE, merged)
            self.assertEqual({}, diagnostics["missing_fields"])
            self.assertEqual([], incomplete_gate_evidence_failures(diagnostics))

    def test_delegation_plan_rejects_duplicate_ids_and_overlapping_owned_scopes(self) -> None:
        plan = valid_delegation_plan()
        plan["workers"].append(
            {
                "id": "finish-a",
                "role": "routing investigator",
                "owned_scope": ["scripts/agent_finish_*"],
                "forbidden_scope": ["all edits"],
                "contract": "trace routing flow",
                "acceptance": ["report paths and symbols"],
                "verification": ["focused unittest"],
            }
        )

        failures = validate_delegation_plan_structure(plan)

        self.assertTrue(any("duplicates id finish-a" in failure for failure in failures))
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))


class AutomaticDelegationRoutingTests(unittest.TestCase):
    def test_code_work_routes_keep_multi_agent_guidance_on_demand(self) -> None:
        for command in sorted(SCOPE_CHANGE_LIFECYCLE_COMMANDS - {"test"}):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertNotIn(MULTI_AGENT_SKILL, route["required_docs"])
                self.assertNotIn(MULTI_AGENT_SKILL, route["reference_docs"])
                self.assertEqual(
                    "automatic_when_eligible",
                    route["parallel_execution"]["delegation_policy"]["mode"],
                )

    def test_parallel_plan_requires_automatic_delegation_when_eligible(self) -> None:
        plan = parallel_execution_plan(
            "feature",
            ["request intake", "source docs", MULTI_AGENT_GATE, "implementation", "tests"],
        )

        policy = plan["delegation_policy"]
        self.assertEqual("automatic_when_eligible", policy["mode"])
        self.assertFalse(policy["explicit_user_request_required"])
        self.assertEqual(2, policy["minimum_independent_slices"])
        self.assertTrue(any("concrete serial reason" in note for note in plan["notes"]))

    def test_multi_agent_route_worker_phase_is_parallel(self) -> None:
        route = resolve_docs("multi-agent", None, [], request_classified=True)
        phases = {phase["id"]: phase for phase in route["parallel_execution"]["phases"]}

        self.assertEqual("parallel", phases["worker_execution"]["mode"])

    def test_runtime_bridges_require_auto_delegation_before_codex_leaf_dispatch(self) -> None:
        for runtime_name, instruction_file in (
            ("Codex", "AGENTS.md"),
            ("Claude", "CLAUDE.md"),
            ("Antigravity", "AGENTS.md"),
        ):
            with self.subTest(runtime=runtime_name):
                required = runtime_bridge_required_phrases(runtime_name, instruction_file)
                block = runtime_bridge_block(ROOT, runtime_name, instruction_file)
                self.assertIn(AUTO_DELEGATION_BRIDGE_PHRASE, required)
                self.assertIn(AUTO_DELEGATION_BRIDGE_PHRASE, block)
                self.assertIn(RUNTIME_NATIVE_DELEGATION_PHRASES[runtime_name], required)
                self.assertIn(RUNTIME_NATIVE_DELEGATION_PHRASES[runtime_name], block)

        codex_block = runtime_bridge_block(ROOT, "Codex", "AGENTS.md")
        self.assertLess(
            codex_block.index(AUTO_DELEGATION_BRIDGE_PHRASE),
            codex_block.index(CODEX_DISPATCH_BRIDGE_PHRASE),
        )


if __name__ == "__main__":
    unittest.main()
