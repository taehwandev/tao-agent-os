from __future__ import annotations

import json
import io
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_common import requires_retrospective
from agent_finish_gate_policy import (
    PLATFORM_SELECTION_GATE,
    PRD_DRAFT_GATE,
    REVIEW_READINESS_GATE,
    VALIDATED_GATES,
    validate_gate_evidence,
)
from agent_finish_check_steps import (
    check_request_intake,
    check_required_gates,
    validate_grill_me_skill_evidence,
)
from agent_gate_evidence import (
    canonical_gate_fields,
    gate_evidence_path_for_preflight,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    record_many_gate_evidence,
    reset_gate_evidence_ledger,
    synthesize_gate_evidence,
)
from agent_worker_evidence import worker_reservation_matches
from agent_delegation_plan import validate_delegation_plan_evidence
from agent_global_lessons import (
    lesson_summary,
    retrospective_candidate,
    write_retrospective_candidate,
)
from agent_lesson_store import upsert_retrospective_candidate
from agent_hook_runtime import hook_failure_policy, repair_context_failures
import agent_skill_hooks
from agent_preflight_runtime import (
    AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES as PREFLIGHT_AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES,
    _claude_spill_warnings,
)
from agent_review_hook import review_hook, review_vibeguard_command, workflow_validate_failure_detail
from agent_review_structure import structure_review
from agent_vibeguard_cache import cached_vibeguard
from support.agy_setup import AGY_RUNTIME_BRIDGE_REQUIRED_PHRASES, _agy_runtime_bridge_block
from support.claude_setup import _merge_claude_user_prompt_submit
from support.permission_entries import agy_permission_entries, claude_permission_entries, codex_prefix_rule_entries
from support.runtime_bridge import (
    CODEX_DISPATCH_BRIDGE_PHRASE,
    RUNTIME_BRIDGE_GRAPH_PHRASES,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.stable_launcher import stable_launcher_path
from workflow_catalog import COMMANDS, CONCERNS, SPILL_ACTION_LABELS
from workflow_doc_resolution import resolve_guidance_docs
from workflow_route import CORE_REQUIRED_DOCS
from workflow_gate_policy import (
    AGENTIC_RUN_STATE_GATE,
    AMBIGUITY_GATE,
    ALIGNMENT_BRIEF_GATE,
    BOUNDARY_PLAN_GATE,
    CYCLE_CONTRACT_GATE,
    DOCUMENTATION_IMPACT_GATE,
    DOCUMENTATION_GATE,
    MULTI_AGENT_GATE,
    PRODUCT_REENTRY_GATE,
    PRODUCT_REENTRY_COMMANDS,
    SKILL_FEEDBACK_HOOK,
    SIDE_EFFECT_AUDIT_GATE,
    SOURCE_DOCS_GATE,
    SOURCE_DOCS_COMMANDS,
    TEST_GATE,
    ALIGNMENT_BRIEF_COMMANDS,
    WORK_PRODUCING_COMMANDS,
)
from workflow_request import infer_concerns_from_request
from workflow_request import classify_request
from workflow_request import classified_route_block_reason
from workflow_request import route_block_reason
from agent_route_state import request_fingerprint
from workflow_dispatch import (
    build_dispatch_manifest,
    execute_dispatch_manifest,
    print_dispatch_manifest,
)
from workflow_dispatch_profiles import profile_for_work_kind, select_work_kind
from workflow_doc_surfaces import (
    extract_request_surface_paths,
    git_status_surface_paths,
    infer_surface_docs,
    load_doc_surface_rules,
    surface_rule_doc_refs,
)
from workflow_doc_graph import (
    clear_doc_graph_cache,
    expand_doc_matches,
    graph_required_docs,
)
from workflow_parallel_validate import validate_parallel_execution_plan
from workflow_route import resolve_docs, route_hooks
from workflow_search import SearchOutcome, search_docs, search_docs_outcome
from workflow_skill_paths import canonical_doc_path
from workflow_spill import spill_tool_label, validate_spill_label_contracts
from workflow import build_parser, print_dispatch
from workflow_validate import (
    STRICT_CARD_REQUIRED_HEADINGS,
    markdown_files_to_validate,
    removed_cli_option_failures,
)


_PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "agent_preflight_under_test", ROOT / "scripts" / "agent-preflight.py"
)
assert _PREFLIGHT_SPEC and _PREFLIGHT_SPEC.loader
agent_preflight = importlib.util.module_from_spec(_PREFLIGHT_SPEC)
_PREFLIGHT_SPEC.loader.exec_module(agent_preflight)

_FINISH_CHECK_SPEC = importlib.util.spec_from_file_location(
    "agent_finish_check_under_test", ROOT / "scripts" / "agent-finish-check.py"
)
assert _FINISH_CHECK_SPEC and _FINISH_CHECK_SPEC.loader
agent_finish_check = importlib.util.module_from_spec(_FINISH_CHECK_SPEC)
_FINISH_CHECK_SPEC.loader.exec_module(agent_finish_check)

_AGENT_HOOK_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_under_test", ROOT / "scripts" / "agent-hook.py"
)
assert _AGENT_HOOK_SPEC and _AGENT_HOOK_SPEC.loader
agent_hook = importlib.util.module_from_spec(_AGENT_HOOK_SPEC)
_AGENT_HOOK_SPEC.loader.exec_module(agent_hook)


def route_doc(path: str) -> str:
    return canonical_doc_path(path)
def required_doc(path: str) -> str:
    """The document a route actually requires for a guidance area.

    Thin `SKILL.md` entrypoints resolve to `references/current-guidance.md`,
    which is where the rules live; entrypoints with content of their own, and
    skills with no reference, stay as they are. Core docs are exempt from
    resolution in the router, so they are exempt here too.
    """
    canonical = canonical_doc_path(path)
    if canonical in {canonical_doc_path(doc) for doc in CORE_REQUIRED_DOCS}:
        return canonical
    return resolve_guidance_docs(ROOT, [canonical])[-1]


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


def required_areas(route: dict) -> set[str]:
    """Guidance areas the route makes mandatory reading.

    A substantive entrypoint and its reference are two documents for one
    area; the byte budget may admit only the entrypoint. Either document
    form delivers the area as required reading.
    """
    return {guidance_area(doc) for doc in route["required_docs"]}


class WorkflowDocSurfacesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state_home = os.environ.get("TAO_STATE_HOME")

    def tearDown(self) -> None:
        if self._old_state_home is None:
            os.environ.pop("TAO_STATE_HOME", None)
        else:
            os.environ["TAO_STATE_HOME"] = self._old_state_home

    def test_android_screen_request_routes_to_feature(self) -> None:
        classification = classify_request(
            "안드로이드 작업에서 첫 화면에서는 전체 목록이, 두번째 화면에서는 즐겨찾기가 있는 화면을 구성해줘"
        )

        self.assertEqual("vague-action", classification["clarity"])
        self.assertEqual("triage", classification["recommended_route"])
        self.assertTrue(classification["grill_me"])

    def test_commit_dirty_surfaces_stay_reference_only(self) -> None:
        surface_paths = [
            "scripts/agent_preflight_runtime.py",
            "tests/test_agent_preflight_runtime.py",
            "docs/skills/agent-runtime-integration/references/current-guidance.md",
        ]

        route = resolve_docs(
            "git_commit",
            None,
            [],
            request_classified=True,
            request_text="현재 변경사항을 분리해서 커밋해줘",
            surface_paths=surface_paths,
            project_root=ROOT,
        )

        # The contract under test is that dirty-path surfaces stay optional on a
        # commit route -- not the exact required-doc list, which is now bounded
        # by budget and so no longer a fixed set.
        for doc in (
            "AGENTS.md",
            "common/skills/agent-operating-skill/SKILL.md",
            "workflows/skills/review-and-commit/SKILL.md",
            "common/skills/commit-workflow/SKILL.md",
        ):
            self.assertIn(required_doc(doc), route["required_docs"])

        for surface_path in surface_paths:
            self.assertNotIn(required_doc(surface_path), route["required_docs"])
        self.assertIn(
            route_doc("workflows/skills/scripted-agent-workflow/SKILL.md"),
            route["reference_docs"],
        )
        self.assertIn(
            route_doc("common/skills/testing/SKILL.md"),
            route["reference_docs"],
        )
        self.assertTrue(
            any("dirty-path surfaces" in note for note in route["notes"])
        )

    def test_android_performance_route_loads_external_skill_manifest(self) -> None:
        route = resolve_docs(
            "workflow-setup",
            "android",
            ["performance"],
            request_classified=True,
        )

        self.assertIn(route_doc("common/skills/performance-verification/SKILL.md"), route["docs"])
        self.assertIn(route_doc("platforms/android/skills/android-compose-ui/SKILL.md"), route["docs"])
        self.assertIn(route_doc("platforms/android/skills/android-review/SKILL.md"), route["docs"])
        self.assertIn(route_doc("platforms/android/skills/android-external-skill-source-coverage/SKILL.md"), route["docs"])

    def test_android_platform_surfaces_load_external_skill_manifest(self) -> None:
        for concern in ("architecture", "security", "testing", "module", "dependency", "migration", "devtools", "skills", "skill"):
            with self.subTest(concern=concern):
                route = resolve_docs(
                    "workflow-setup",
                    "android",
                    [concern],
                    request_classified=True,
                )

                self.assertIn(route_doc("platforms/android/skills/android-external-skill-source-coverage/SKILL.md"), route["docs"])
                self.assertIn(route_doc("platforms/android/skills/source-coverage/SKILL.md"), route["docs"])

    def test_android_persistence_route_loads_datastore_reference(self) -> None:
        for concern in ("persistence", "cache"):
            with self.subTest(concern=concern):
                route = resolve_docs(
                    "feature",
                    "android",
                    [concern],
                    request_classified=True,
                )

                self.assertIn(route_doc("platforms/android/skills/android-state-data/SKILL.md"), route["docs"])
                self.assertIn("platforms/android/skills/android-state-data/references/android-datastore.md", route["docs"])

    def test_path_surface_promotes_workflow_docs_to_required_docs(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["scripts/workflow_route.py"],
        )

        self.assertIn(guidance_area("workflows/skills/scripted-agent-workflow/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/ci-cd-automation/SKILL.md"), routed_areas(route))
        self.assertIn("doc_surface_matches", route)
        self.assertTrue(any(match["name"] == "workflow_router" for match in route["doc_surface_matches"]))

    def test_graphify_request_records_selected_project_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            route = resolve_docs(
                "task",
                None,
                [],
                request_classified=True,
                request_text="Set up Graphify for the target project.",
                project_root=project,
            )

        self.assertIn(guidance_area("docs/skills/agent-bootstrap/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("docs/skills/graphify-project-integration/SKILL.md"), required_areas(route))
        self.assertIn(guidance_area("common/skills/llm-wiki-documentation/SKILL.md"), routed_areas(route))
        self.assertEqual(False, route["target_project_graphify"]["ready"])
        self.assertIn("graphify readiness", route["gates"])
        self.assertTrue(any(match["name"] == "target_project_graphify" for match in route["doc_surface_matches"]))

    def test_graphify_path_surface_promotes_readiness_docs(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["scripts/support/setup_agent_hooks_impl.py"],
        )

        self.assertIn(guidance_area("docs/skills/agent-bootstrap/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("docs/skills/graphify-project-integration/SKILL.md"), required_areas(route))
        self.assertIn("graphify readiness", route["gates"])
        self.assertTrue(any(match["name"] == "graphify_integration" for match in route["doc_surface_matches"]))

    def test_classified_graphify_evidence_still_infers_route_concern(self) -> None:
        request = "apply the confirmed change in scripts/workflow_doc_surfaces.py"
        session_id = "workflow-doc-surfaces-session"
        envelope = {
            "schema_version": 1,
            "request_fingerprint": request_fingerprint({"request": request}),
            "runtime_session_id": session_id,
            "mode": "work",
            "intent": "configure",
            "target_summary": "the confirmed document surface change",
            "requested_effects": ["local_write"],
            "ambiguity": "resolved",
        }
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "workflow.py"),
                "route",
                "workflow-setup",
                "--project",
                str(ROOT),
                # --request-classified no longer suppresses classification, so the
                # real request must be supplied; the concern still has to come out
                # of the classification evidence, which is where the scope is named.
                "--request",
                request,
                "--intent-envelope",
                json.dumps(envelope),
                "--runtime-session-id",
                session_id,
                "--request-classified",
                "--classification-evidence",
                "answered direct question; separate actionable clear-scoped Graphify project install and readiness workflow",
                "--format",
                "json",
            ],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        route = json.loads(result.stdout)
        self.assertIn("graphify", route["inferred_concerns"])
        self.assertIn("graphify readiness", route["gates"])
        self.assertIn(
            guidance_area("docs/skills/graphify-project-integration/SKILL.md"),
            routed_areas(route),
        )

    def test_graphify_readiness_gate_requires_all_structured_fields(self) -> None:
        success_fields = {
            "cli": "success",
            "skill_doc": "success",
            "runtime_links": "success",
            "runtime_ownership": "success",
            "project_integration": "success",
            "graph": "success",
            "query_smoke": "success",
        }
        evidence, missing = synthesize_gate_evidence(
            "graphify readiness",
            "graph details are recorded outside the status fields",
            success_fields,
        )

        self.assertEqual([], missing)
        self.assertEqual([], validate_gate_evidence({"graphify readiness": evidence}, ["graphify readiness"]))

        for field, value in (("graph", "fresh and valid"), ("query_smoke", "passed")):
            with self.subTest(field=field, value=value):
                values = dict(success_fields)
                values[field] = value
                _, failures = synthesize_gate_evidence("graphify readiness", "", values)
                self.assertTrue(any("exact success" in failure for failure in failures))

        _, missing = synthesize_gate_evidence(
            "graphify readiness",
            "",
            {key: value for key, value in success_fields.items() if key != "query_smoke"},
        )
        self.assertEqual(["query_smoke"], missing)

        _, missing = synthesize_gate_evidence(
            "graphify readiness",
            "",
            {
                key: value
                for key, value in success_fields.items()
                if key != "runtime_ownership"
            },
        )
        self.assertEqual(["runtime_ownership"], missing)

        legacy_fields = {
            **{
                key: value
                for key, value in success_fields.items()
                if key != "runtime_ownership"
            },
            "git_ownership": "success",
        }
        legacy_evidence, missing = synthesize_gate_evidence(
            "graphify readiness",
            "",
            legacy_fields,
        )
        self.assertEqual([], missing)
        self.assertIn("runtime ownership=success", legacy_evidence)
        self.assertNotIn("git ownership=", legacy_evidence)
        self.assertEqual(
            success_fields,
            canonical_gate_fields("graphify readiness", legacy_fields, {}),
        )
        self.assertEqual(
            [],
            validate_gate_evidence(
                {
                    "graphify readiness": legacy_evidence.replace(
                        "runtime ownership=",
                        "git ownership=",
                    )
                },
                ["graphify readiness"],
            ),
        )

    def test_scripted_workflow_guidance_emits_canonical_graphify_fields(self) -> None:
        guidance = (
            ROOT
            / "workflows"
            / "skills"
            / "scripted-agent-workflow"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "`runtime_ownership`, `project_integration`, `graph`, and `query_smoke`",
            guidance,
        )
        self.assertNotIn("`git ownership=`", guidance)

    def test_scripted_workflow_guidance_separates_claim_refusal_from_repair(self) -> None:
        guidance = (
            ROOT
            / "workflows"
            / "skills"
            / "scripted-agent-workflow"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        self.assertIn("`fix_invocation_and_rerun`", guidance)
        self.assertRegex(guidance, r"no\s+checkpoint failed")
        self.assertIn("must not enter `repair-verify`", guidance)

    def test_review_guidance_makes_hook_provenance_executable(self) -> None:
        scripted = (
            ROOT
            / "workflows"
            / "skills"
            / "scripted-agent-workflow"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")
        review = (
            ROOT
            / "workflows"
            / "skills"
            / "review-and-commit"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        for guidance in (scripted, review):
            self.assertIn("hook-owned", guidance)
            self.assertIn("review attestation", guidance)
            self.assertIn("gate-batch", guidance)
            self.assertIn("pathspec", guidance)
        self.assertIn("each changed class", review)
        self.assertIn("owner block exceeds the function", review)

    def test_structure_contract_covers_files_added_to_existing_packages(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        review = (
            ROOT
            / "workflows"
            / "skills"
            / "review-and-commit"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        for guidance in (agents, review):
            normalized = " ".join(guidance.split())
            self.assertIn("added runtime file", normalized)
            self.assertIn("existing multi-role package", normalized)
            self.assertIn("allowed imports", normalized)
            self.assertIn("forbidden imports", normalized)
            self.assertIn("callers/tests", normalized)
            self.assertIn("verification", normalized)

    def test_review_attestation_is_rechecked_after_final_checks(self) -> None:
        scripted = (
            ROOT
            / "workflows"
            / "skills"
            / "scripted-agent-workflow"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")
        review = (
            ROOT
            / "workflows"
            / "skills"
            / "review-and-commit"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        for guidance in (scripted, review):
            self.assertIn("after all final checks", guidance)
            self.assertIn("immediately before", guidance)

    def test_scripted_guidance_requires_atomic_claim_and_ledger_mutation(self) -> None:
        guidance = (
            ROOT
            / "workflows"
            / "skills"
            / "scripted-agent-workflow"
            / "references"
            / "current-guidance.md"
        ).read_text(encoding="utf-8")

        self.assertIn("one atomic transaction", guidance)
        self.assertIn("project-state -> run-registry -> gate-ledger", guidance)
        self.assertIn("second unlocked claim check", guidance)

    def test_request_path_surface_promotes_docs_without_explicit_keyword(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            request_text="`scripts/workflow_route.py` 수정해줘",
        )

        self.assertIn(guidance_area("workflows/skills/scripted-agent-workflow/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/ci-cd-automation/SKILL.md"), routed_areas(route))

    def test_test_path_surface_promotes_testing_docs_to_required_docs(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["tests/test_workflow_routing.py"],
        )

        self.assertIn(required_doc("common/skills/testing/SKILL.md"), route["required_docs"])
        self.assertIn(guidance_area("common/skills/verification-policy/SKILL.md"), routed_areas(route))

    def test_surface_helpers_extract_request_and_git_status_paths(self) -> None:
        self.assertIn(
            "scripts/workflow_request.py",
            extract_request_surface_paths("`scripts/workflow_request.py` 수정해줘"),
        )
        self.assertIn(
            "scripts/workflow_request.py",
            extract_request_surface_paths("`scripts/workflow_request.py:10` 확인해줘"),
        )
        self.assertIn(
            "scripts/workflow_route.py",
            git_status_surface_paths(" M scripts/workflow_route.py\n?? tests/new_test.py\n"),
        )
        self.assertIn(
            "tests/new_test.py",
            git_status_surface_paths(" M scripts/workflow_route.py\n?? tests/new_test.py\n"),
        )

    def test_surface_rule_docs_are_loaded_from_root_map(self) -> None:
        docs, matches = infer_surface_docs(
            command="task",
            surface_paths=["common/skills/code-conventions/SKILL.md"],
        )

        self.assertIn("common/skills/agent-skill-card-anatomy/SKILL.md", docs)
        self.assertIn("docs/skills/tao-skill-bundle-migration/SKILL.md", docs)
        self.assertTrue(any(match["name"] == "skill_docs" for match in matches))

    def test_skill_bundle_structure_request_promotes_migration_docs(self) -> None:
        route = resolve_docs(
            "docs",
            None,
            [],
            request_classified=True,
            request_text=(
                "skills 폴더와 references 구조를 정리하고 중복 source-of-truth를 줄여줘"
            ),
        )

        self.assertIn(
            guidance_area("docs/skills/tao-skill-bundle-migration/SKILL.md"),
            routed_areas(route),
        )
        self.assertIn(guidance_area("common/skills/agent-skill-card-anatomy/SKILL.md"), required_areas(route))
        self.assertTrue(
            any(match["name"] == "skill_bundle_structure_cleanup" for match in route["doc_surface_matches"])
        )

    def test_surface_doc_sets_are_loaded_from_root_map(self) -> None:
        docs, invalid_refs = surface_rule_doc_refs(load_doc_surface_rules())

        self.assertEqual([], invalid_refs)
        self.assertIn("platforms/web/skills/web-react-ui/SKILL.md", docs)
        self.assertIn("platforms/ios/skills/ios-swiftui-ui/SKILL.md", docs)
        self.assertIn("platforms/flutter/skills/flutter-widget-ui/SKILL.md", docs)

    def test_document_graph_expands_markdown_and_required_frontmatter_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "a.md").write_text(
                "---\nrequires_docs:\n  - docs/c.md\n---\n# A\n\nRead [B](b.md).\n",
                encoding="utf-8",
            )
            (docs_dir / "b.md").write_text("# B\n", encoding="utf-8")
            (docs_dir / "c.md").write_text("# C\n", encoding="utf-8")

            clear_doc_graph_cache()
            matches = expand_doc_matches(root, ["docs/a.md"], max_depth=1)
            paths = [str(match["path"]) for match in matches]

            self.assertIn("docs/b.md", paths)
            self.assertIn("docs/c.md", paths)
            self.assertEqual(["docs/c.md"], graph_required_docs(matches))

    def test_document_graph_expands_surface_rule_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "a.md").write_text("# A\n", encoding="utf-8")
            (docs_dir / "b.md").write_text("# B\n", encoding="utf-8")
            (root / "workflow-doc-surfaces.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "doc_sets": {"pair": ["docs/a.md", "docs/b.md"]},
                        "request_intents": [],
                        "path_surfaces": [],
                    }
                ),
                encoding="utf-8",
            )

            clear_doc_graph_cache()
            matches = expand_doc_matches(
                root,
                ["docs/a.md"],
                max_depth=1,
                relation_prefixes=("surface:",),
            )

            self.assertIn("docs/b.md", [str(match["path"]) for match in matches])
            self.assertTrue(any(match["relation"] == "surface:doc_set:pair" for match in matches))

    def test_android_ui_request_promotes_compose_docs_to_required_docs(self) -> None:
        route = resolve_docs(
            "feature",
            "android",
            [],
            request_classified=True,
            request_text=(
                "안드로이드 작업에서 첫 화면에서는 전체 목록이, "
                "두번째 화면에서는 즐겨찾기가 있는 화면을 구성해줘"
            ),
        )

        self.assertIn(required_doc("platforms/android/skills/android-compose-ui/SKILL.md"), route["required_docs"])
        self.assertIn(guidance_area("platforms/android/skills/android-viewmodel-state/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("platforms/android/skills/android-state-data/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/ui-visual-verification/SKILL.md"), routed_areas(route))
        self.assertIn(
            guidance_area("platforms/android/skills/source-coverage/references/compose-performance-source-map.md"),
            routed_areas(route),
        )
        self.assertTrue(any(match["name"] == "android_compose_ui_feature" for match in route["doc_surface_matches"]))

    def test_android_compose_self_selection_promotes_performance_source_docs(self) -> None:
        route = resolve_docs(
            "feature",
            "android",
            [],
            request_classified=True,
            request_text="Compose로 작성하겠다고 정했으면 목록 화면을 구현해줘",
        )

        self.assertIn(required_doc("platforms/android/skills/android-compose-ui/SKILL.md"), route["required_docs"])
        self.assertIn(guidance_area("platforms/android/skills/android-external-skill-source-coverage/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("platforms/android/skills/source-coverage/SKILL.md"), routed_areas(route))
        self.assertIn(
            guidance_area("platforms/android/skills/source-coverage/references/compose-performance-source-map.md"),
            routed_areas(route),
        )
        self.assertIn(
            guidance_area("platforms/android/skills/source-coverage/references/chrisbanes-source-map.md"),
            routed_areas(route),
        )

    def test_android_compose_path_promotes_compose_docs_without_request_keyword(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            surface_paths=["app/src/main/java/com/example/home/HomeScreen.kt"],
        )

        self.assertIn(required_doc("platforms/android/skills/android-compose-ui/SKILL.md"), route["required_docs"])
        self.assertIn(guidance_area("platforms/android/skills/android-review/SKILL.md"), routed_areas(route))
        self.assertIn(
            guidance_area("platforms/android/skills/source-coverage/references/compose-performance-source-map.md"),
            routed_areas(route),
        )
        self.assertTrue(any(match["name"] == "android_compose_paths" for match in route["doc_surface_matches"]))

    def test_query_expands_code_cleanup_natural_language_to_refactor_docs(self) -> None:
        results = search_docs(ROOT, "코드 정리해줘", max_results=8)
        paths = [str(item["path"]) for item in results]

        self.assertIn("workflows/skills/refactor-cleanup/SKILL.md", paths)
        self.assertIn("common/skills/refactoring/SKILL.md", paths)
        self.assertIn("common/skills/verification-policy/SKILL.md", paths)
        self.assertTrue(
            any("code_cleanup" in item.get("matched_facets", []) for item in results),
            results,
        )

    def test_query_uses_wikimap_section_results_behind_existing_api(self) -> None:
        outcome = search_docs_outcome(
            ROOT,
            "When may documentation be skipped with user approval?",
            max_results=8,
        )

        self.assertEqual("wikimap", outcome.backend)
        self.assertEqual("1.0.0", outcome.backend_version)
        self.assertTrue(outcome.results)
        self.assertTrue(
            any(item.get("line") and item.get("heading") for item in outcome.results),
            outcome.results,
        )

    def test_query_expands_android_ui_natural_language_to_compose_docs(self) -> None:
        results = search_docs(
            ROOT,
            "안드로이드 첫 화면에서는 전체 목록이, 두번째 화면에서는 즐겨찾기가 있는 화면을 구성해줘",
            max_results=16,
        )
        paths = [str(item["path"]) for item in results]

        self.assertIn("platforms/android/skills/android-compose-ui/SKILL.md", paths)
        self.assertIn("platforms/android/skills/android-viewmodel-state/SKILL.md", paths)
        self.assertIn("platforms/android/skills/source-coverage/references/compose-performance-source-map.md", paths)
        self.assertTrue(
            any("android_compose_ui" in item.get("matched_facets", []) for item in results),
            results,
        )

    def test_natural_language_doc_routing_request_promotes_workflow_docs(self) -> None:
        route = resolve_docs(
            "workflow-setup",
            None,
            [],
            request_classified=True,
            request_text="훅은 보완이고 자연어 검색 가능한 문서 라우팅을 강화해줘",
        )

        self.assertIn(guidance_area("workflows/skills/scripted-agent-workflow/SKILL.md"), routed_areas(route))
        # The workflow-setup command tier plus the guaranteed gate contracts now
        # fill the bounded required-doc selection, so this surface match lands
        # in reference_docs rather than being promoted to mandatory reading.
        self.assertIn(guidance_area("common/skills/task-intake-effort-routing/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/source-driven-development/SKILL.md"), routed_areas(route))
        self.assertTrue(any(match["name"] == "natural_language_doc_routing" for match in route["doc_surface_matches"]))
        self.assertEqual("wikimap", route["document_search"]["backend"])
        self.assertTrue(route["document_search"]["candidates"])
        self.assertTrue(
            set(route["document_search"]["candidates"]).issubset(
                set(route["required_docs"]) | set(route["reference_docs"])
            )
        )

    def test_document_search_no_matches_is_terminal_not_a_retry_loop(self) -> None:
        outcome = SearchOutcome(
            results=[],
            backend="wikimap",
            backend_version="1.0.0",
        )
        with patch("workflow_route.search_docs_outcome", return_value=outcome):
            route = resolve_docs(
                "workflow-setup",
                None,
                [],
                request_classified=True,
                request_text="no matching project document should be found",
            )

        self.assertEqual("no_matches", route["document_search"]["status"])
        self.assertTrue(route["document_search"]["terminal"])
        self.assertEqual([], route["missing"])
        self.assertTrue(route["required_docs"])
        self.assertTrue(any("terminal no-source outcome" in note for note in route["notes"]))

    def test_missing_required_document_is_invalid_manifest_not_search_retry(self) -> None:
        with patch(
            "workflow_route.route_required_docs",
            return_value=["missing-required-document.md"],
        ):
            route = resolve_docs("review", None, [], request_classified=True)

        self.assertEqual(["missing-required-document.md"], route["missing"])
        self.assertEqual("invalid_manifest", route["document_search"]["status"])
        self.assertTrue(route["document_search"]["terminal"])
        self.assertTrue(any("Stop once" in note for note in route["notes"]))

    def test_planning_change_request_promotes_documentation_impact_docs(self) -> None:
        route = resolve_docs(
            "task",
            None,
            [],
            request_classified=True,
            request_text="기획변경인데 예상 문서 정리가 누락되는 경우를 막아줘",
        )

        self.assertIn(guidance_area("common/skills/doc-conventions/SKILL.md"), required_areas(route))
        self.assertIn(guidance_area("workflows/skills/documentation-update/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/product-spec-to-implementation/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/source-driven-development/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("common/skills/definition-of-done/SKILL.md"), routed_areas(route))
        self.assertIn(guidance_area("workflows/skills/scripted-agent-workflow/SKILL.md"), routed_areas(route))
        self.assertTrue(any(match["name"] == "planning_change_documentation" for match in route["doc_surface_matches"]))

    def test_route_exposes_document_graph_neighbors_as_reference_docs(self) -> None:
        route = resolve_docs(
            "workflow-setup",
            None,
            [],
            request_classified=True,
            request_text="훅은 보완이고 자연어 검색 가능한 문서 라우팅을 강화해줘",
        )

        self.assertIn("doc_graph_matches", route)
        # A markdown-link graph neighbor reaches the agent as a reference doc.
        # `local-tools` anchors this property independently of OVERSIZED_DOC_BYTES:
        # it is a small file, so it demonstrates graph-neighbor exposure on its own
        # merits rather than as a side effect of a size demotion.  This assertion
        # should outlive the guard.
        neighbours = {match["path"] for match in route["doc_graph_matches"]}
        self.assertIn("common/skills/local-tools/SKILL.md", neighbours)
        self.assertIn("common/skills/local-tools/SKILL.md", route["reference_docs"])
        # The original anchor, restored: the oversized scripted-agent-workflow
        # reference is held out of required_docs by OVERSIZED_DOC_BYTES and stays
        # reachable as a reference.  This pins the guard's observable effect on a
        # real route, so it will fail loudly if the guard is removed again before
        # that document is split.
        self.assertIn(
            "workflows/skills/scripted-agent-workflow/references/current-guidance.md",
            route["reference_docs"],
        )
        self.assertNotIn(
            "workflows/skills/scripted-agent-workflow/references/current-guidance.md",
            route["required_docs"],
        )

    def test_query_uses_document_graph_to_promote_related_skill_entrypoints(self) -> None:
        results = search_docs(ROOT, "훅으로 문서 검색하고 읽도록", max_results=12)
        graph_items = [
            item
            for item in results
            if item["path"] == "workflows/skills/scripted-agent-workflow/SKILL.md"
        ]

        self.assertTrue(graph_items, results)
        self.assertTrue(
            graph_items[0].get("graph_reasons")
            or "natural_language_doc_routing" in graph_items[0].get("matched_facets", []),
            graph_items[0],
        )

    def test_query_promotes_skill_bundle_migration_for_structure_cleanup(self) -> None:
        results = search_docs(
            ROOT,
            "스킬 references 구조와 중복 source-of-truth 정리",
            max_results=12,
        )

        self.assertTrue(
            any(
                item["path"] == "docs/skills/tao-skill-bundle-migration/SKILL.md"
                for item in results
            ),
            results,
        )

    def test_ui_feature_request_promotes_docs_for_all_ui_platforms(self) -> None:
        request = "첫 화면에서는 전체 목록이, 두번째 화면에서는 즐겨찾기가 있는 화면을 구성해줘"
        expected_docs = {
            "android": [
                "platforms/android/skills/android-compose-ui/SKILL.md",
                "platforms/android/skills/android-viewmodel-state/SKILL.md",
                "platforms/android/skills/source-coverage/references/compose-performance-source-map.md",
            ],
            "application": [
                "platforms/application/skills/application-command-ui/SKILL.md",
                "platforms/application/skills/application-system-integration/SKILL.md",
            ],
            "flutter": [
                "platforms/flutter/skills/flutter-widget-ui/SKILL.md",
                "platforms/flutter/skills/flutter-state-data/SKILL.md",
            ],
            "ios": [
                "platforms/ios/skills/ios-swiftui-ui/SKILL.md",
                "platforms/ios/skills/ios-uikit-ui/SKILL.md",
                "platforms/ios/skills/ios-state-concurrency/SKILL.md",
            ],
            "kmp": [
                "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
                "platforms/kmp/skills/kmp-state-data/SKILL.md",
            ],
            "swift": [
                "platforms/swift/skills/swift-design-system/SKILL.md",
                "platforms/swift/skills/swift-code-structure/SKILL.md",
            ],
            "web": [
                "platforms/web/skills/web-react-ui/SKILL.md",
                "platforms/web/skills/web-state-data/SKILL.md",
                "platforms/web/skills/web-design-system/SKILL.md",
            ],
        }

        for platform, docs in expected_docs.items():
            with self.subTest(platform=platform):
                route = resolve_docs(
                    "feature",
                    platform,
                    [],
                    request_classified=True,
                    request_text=request,
                )

                for doc in docs:
                    self.assertIn(guidance_area(doc), routed_areas(route))
                self.assertIn(guidance_area("common/skills/ui-visual-verification/SKILL.md"), routed_areas(route))
                self.assertIn(guidance_area("common/skills/performance-verification/SKILL.md"), routed_areas(route))

    def test_server_platform_does_not_receive_ui_surface_docs(self) -> None:
        route = resolve_docs(
            "feature",
            "server",
            [],
            request_classified=True,
            request_text="첫 화면에서는 전체 목록이, 두번째 화면에서는 즐겨찾기가 있는 화면을 구성해줘",
        )

        self.assertNotIn("doc_surface_matches", route)
        self.assertNotIn(required_doc("common/skills/ui-visual-verification/SKILL.md"), route["required_docs"])
        self.assertNotIn(required_doc("platforms/web/skills/web-react-ui/SKILL.md"), route["required_docs"])

    def test_self_selected_ui_frameworks_promote_platform_docs(self) -> None:
        cases = [
            (
                "android",
                "Compose로 목록 화면을 구현해줘",
                "android_compose_self_selected",
                "platforms/android/skills/android-compose-ui/SKILL.md",
            ),
            (
                "application",
                "Tauri React renderer로 목록 화면을 구현해줘",
                "application_react_self_selected",
                "platforms/application/skills/application-react-desktop/SKILL.md",
            ),
            (
                "flutter",
                "Flutter Widget으로 목록 화면을 구현해줘",
                "flutter_widget_self_selected",
                "platforms/flutter/skills/flutter-widget-ui/SKILL.md",
            ),
            (
                "ios",
                "SwiftUI로 목록 화면을 구현해줘",
                "ios_swiftui_self_selected",
                "platforms/ios/skills/ios-swiftui-ui/SKILL.md",
            ),
            (
                "ios",
                "UIKit ViewController로 목록 화면을 구현해줘",
                "ios_uikit_self_selected",
                "platforms/ios/skills/ios-uikit-ui/SKILL.md",
            ),
            (
                "kmp",
                "Compose Multiplatform으로 목록 화면을 구현해줘",
                "kmp_compose_self_selected",
                "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
            ),
            (
                "web",
                "React TSX로 목록 화면을 구현해줘",
                "web_react_self_selected",
                "platforms/web/skills/web-react-ui/SKILL.md",
            ),
        ]

        for platform, request, match_name, doc in cases:
            with self.subTest(platform=platform, match_name=match_name):
                route = resolve_docs(
                    "feature",
                    platform,
                    [],
                    request_classified=True,
                    request_text=request,
                )

                self.assertIn(guidance_area(doc), routed_areas(route))
                self.assertTrue(any(match["name"] == match_name for match in route["doc_surface_matches"]))

    def test_ui_path_surfaces_promote_platform_docs_without_cross_platform_leak(self) -> None:
        cases = [
            (
                "app/src/main/java/com/example/home/HomeScreen.kt",
                "android_compose_paths",
                "platforms/android/skills/android-compose-ui/SKILL.md",
                "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
            ),
            (
                "shared/src/commonMain/kotlin/com/example/home/HomeScreen.kt",
                "kmp_compose_paths",
                "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
                "platforms/android/skills/android-compose-ui/SKILL.md",
            ),
            (
                "src/features/home/HomeScreen.tsx",
                "web_react_paths",
                "platforms/web/skills/web-react-ui/SKILL.md",
                "platforms/application/skills/application-command-ui/SKILL.md",
            ),
            (
                "App/Features/Home/HomeView.swift",
                "ios_swiftui_paths",
                "platforms/ios/skills/ios-swiftui-ui/SKILL.md",
                "platforms/ios/skills/ios-uikit-ui/SKILL.md",
            ),
            (
                "App/Features/Home/HomeViewController.swift",
                "ios_uikit_paths",
                "platforms/ios/skills/ios-uikit-ui/SKILL.md",
                "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
            ),
            (
                "lib/features/home/screens/home_screen.dart",
                "flutter_widget_paths",
                "platforms/flutter/skills/flutter-widget-ui/SKILL.md",
                "platforms/web/skills/web-react-ui/SKILL.md",
            ),
            (
                "Sources/AppDesignSystem/Components/ButtonStyle.swift",
                "swift_design_paths",
                "platforms/swift/skills/swift-design-system/SKILL.md",
                "platforms/ios/skills/ios-uikit-ui/SKILL.md",
            ),
            (
                "src-tauri/src/main.rs",
                "application_desktop_paths",
                "platforms/application/skills/application-command-ui/SKILL.md",
                "platforms/web/skills/web-react-ui/SKILL.md",
            ),
        ]

        for path, match_name, expected_doc, absent_doc in cases:
            with self.subTest(path=path):
                route = resolve_docs(
                    "task",
                    None,
                    [],
                    request_classified=True,
                    surface_paths=[path],
                )

                self.assertIn(required_doc(expected_doc), route["required_docs"])
                self.assertNotIn(required_doc(absent_doc), route["required_docs"])
                self.assertTrue(any(match["name"] == match_name for match in route["doc_surface_matches"]))


if __name__ == "__main__":
    unittest.main()
