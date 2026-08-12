"""Required-doc selection: resolve entrypoints to content, then narrow.

These cover the two halves of the routing change together, because they only
make sense as a pair: resolution decides *which document* represents a guidance
area, and narrowing decides *how many* of them a route may mandate.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_gate_validators import validate_source_docs_evidence  # noqa: E402
from workflow_doc_resolution import (  # noqa: E402
    is_pointer_entrypoint,
    resolve_guidance_docs,
)
from workflow_route import (  # noqa: E402
    CORE_REQUIRED_DOCS,
    MAX_REQUIRED_DOCS,
    resolve_docs,
    route_required_docs,
)

REVIEW_AND_COMMIT_REFERENCE = (
    "workflows/skills/review-and-commit/references/current-guidance.md"
)


class EntrypointResolutionTests(unittest.TestCase):
    def test_pointer_entrypoint_resolves_to_its_reference(self) -> None:
        """A generated pointer is replaced by the document holding the rules."""
        # review-and-commit used to be the fixture here, but its entrypoint now
        # carries the review-hook evidence labels itself and is substantive.
        entrypoint = "common/skills/commit-workflow/SKILL.md"
        self.assertTrue(is_pointer_entrypoint(ROOT, entrypoint))

        self.assertEqual(
            ["common/skills/commit-workflow/references/current-guidance.md"],
            resolve_guidance_docs(ROOT, [entrypoint]),
        )

    def test_entrypoint_without_a_reference_is_kept_as_is(self) -> None:
        """The no-reference fallback: there is nothing else to route."""
        entrypoint = "platforms/android/skills/source-coverage/SKILL.md"
        self.assertFalse((ROOT / entrypoint).parent.joinpath(
            "references", "current-guidance.md"
        ).exists())

        self.assertEqual([entrypoint], resolve_guidance_docs(ROOT, [entrypoint]))

    def test_substantive_entrypoint_is_kept_alongside_its_reference(self) -> None:
        """An entrypoint with content of its own must not be dropped for it."""
        entrypoint = "workflows/skills/multi-agent-collaboration/SKILL.md"
        self.assertFalse(is_pointer_entrypoint(ROOT, entrypoint))

        self.assertEqual(
            [
                entrypoint,
                "workflows/skills/multi-agent-collaboration/references/current-guidance.md",
            ],
            resolve_guidance_docs(ROOT, [entrypoint]),
        )

    def test_non_skill_documents_pass_through_untouched(self) -> None:
        self.assertEqual(["AGENTS.md"], resolve_guidance_docs(ROOT, ["AGENTS.md"]))


class RequiredDocMembershipTests(unittest.TestCase):
    def test_analysis_short_circuits_to_agents_only(self) -> None:
        """A bounded investigation must not pay the full document-read cost."""
        self.assertEqual(
            ["AGENTS.md"], route_required_docs("analysis", None, [], ())
        )

    def test_every_route_enforcing_the_review_hook_delivers_its_contract(self) -> None:
        """The defect that motivated this change: the hook rejected work for a
        labelled structure contract the route never put in front of the agent."""
        checked = 0
        for command in [
            "task",
            "feature",
            "bugfix",
            "refactor",
            "release",
            "review",
            "commit",
            "docs",
            "product",
        ]:
            route = resolve_docs(command, None, [], request_classified=True)
            if "review hook" not in route["gates"]:
                continue
            checked += 1
            with self.subTest(command=command):
                self.assertIn(REVIEW_AND_COMMIT_REFERENCE, route["required_docs"])
        self.assertTrue(checked, "expected at least one review-hook route")

    def test_review_hook_contract_survives_a_crowded_route(self) -> None:
        """Guaranteed gate docs are exempt from the byte budget, so a route
        with many surface matches cannot squeeze the contract out."""
        route = resolve_docs(
            "task",
            "android",
            [],
            request_classified=True,
            request_text="add a compose screen and update the release notes",
            surface_paths=["scripts/workflow_route.py", "app/src/main/Home.kt"],
        )

        self.assertIn("review hook", route["gates"])
        self.assertIn(REVIEW_AND_COMMIT_REFERENCE, route["required_docs"])

    def test_explicit_figma_routes_require_common_and_platform_cards(self) -> None:
        cases = (
            (
                "android",
                "Implement this Figma handoff with Jetpack Compose.",
                "platforms/android/skills/figma-to-android/SKILL.md",
            ),
            (
                "ios",
                "Implement this Figma handoff with UIKit.",
                "platforms/ios/skills/figma-to-ios/SKILL.md",
            ),
            (
                "web",
                "Implement this Figma handoff in the Web application.",
                "platforms/web/skills/figma-to-web/SKILL.md",
            ),
        )
        common_guidance = (
            "common/skills/figma-handoff/references/current-guidance.md"
        )

        for platform, request_text, platform_card in cases:
            with self.subTest(platform=platform):
                route = resolve_docs(
                    "feature",
                    platform,
                    [],
                    request_classified=True,
                    request_text=request_text,
                )

                self.assertIn(common_guidance, route["required_docs"])
                self.assertIn(platform_card, route["required_docs"])

    def test_named_concern_docs_are_never_budget_dropped(self) -> None:
        """An explicitly named concern is the strongest signal available."""
        route = resolve_docs("docs", None, ["branch"], request_classified=True)

        for area in ("branch-strategy", "worktree-hygiene"):
            with self.subTest(area=area):
                self.assertTrue(
                    any(
                        f"common/skills/{area}/" in doc
                        for doc in route["required_docs"]
                    ),
                    f"{area} was dropped from required_docs",
                )

    def test_required_docs_stay_within_the_selection_cap(self) -> None:
        for command in ("triage", "task", "bugfix", "release", "review", "feature"):
            with self.subTest(command=command):
                route = resolve_docs(
                    command, None, [], request_classified=True,
                    request_text="update the router and verify it",
                )
                self.assertLessEqual(len(route["required_docs"]), MAX_REQUIRED_DOCS)

    def test_required_docs_carry_content_not_pointers(self) -> None:
        """The point of the change: mandatory reading must not be boilerplate."""
        route = resolve_docs("release", None, [], request_classified=True)
        core = {doc for doc in CORE_REQUIRED_DOCS}

        pointers = [
            doc
            for doc in route["required_docs"]
            if doc not in core and is_pointer_entrypoint(ROOT, doc)
        ]
        self.assertEqual([], pointers)

    def test_every_routed_document_stays_reachable(self) -> None:
        """Narrowing may only make guidance un-mandatory, never unreachable."""
        route = resolve_docs(
            "task", None, [], request_classified=True,
            request_text="update the workflow router",
        )
        reachable = set(route["required_docs"]) | set(route["reference_docs"])
        self.assertTrue(set(route["docs"]).issubset(reachable))

    def test_required_docs_exist_on_disk(self) -> None:
        for command in ("task", "release", "review", "triage"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                for doc in route["required_docs"]:
                    self.assertTrue((ROOT / doc).exists(), doc)

    def test_no_route_has_an_empty_required_manifest(self) -> None:
        """`source docs` would be vacuous, and the gate has a separate branch."""
        for command in ("task", "release", "review", "triage", "analysis"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertTrue(route["required_docs"])


class EmptyManifestBranchTests(unittest.TestCase):
    """A route that legitimately requires nothing must still be satisfiable."""

    def test_empty_manifest_is_satisfied_by_recording_the_empty_state(self) -> None:
        self.assertEqual(
            [],
            validate_source_docs_evidence(
                "route required_docs was empty; searched before implementation "
                "and found no source docs, so no takeaway was applied",
                required_docs=[],
            ),
        )

    def test_empty_manifest_rejects_evidence_that_omits_the_empty_state(self) -> None:
        self.assertTrue(
            validate_source_docs_evidence(
                "read the docs before implementation and applied the takeaway",
                required_docs=[],
            )
        )

    def test_asserted_empty_state_cannot_mask_a_populated_manifest(self) -> None:
        self.assertTrue(
            validate_source_docs_evidence(
                "route required_docs was empty; searched before implementation "
                "and applied nothing",
                required_docs=["AGENTS.md"],
            )
        )

    def test_populated_manifest_requires_the_docs_to_be_read(self) -> None:
        missing = validate_source_docs_evidence(
            "I started implementing right away",
            required_docs=["AGENTS.md"],
        )
        self.assertTrue(missing)


if __name__ == "__main__":
    unittest.main()
