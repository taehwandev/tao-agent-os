"""The android-module-structure bundle: split into separately routable pieces.

The bundle's reference used to be a single 46 KB document.  A route can only
decide per *file*, so that one file was either forced on every matching route or
dropped entirely -- and the `OVERSIZED_DOC_BYTES` cutoff did the latter,
withholding the most relevant document exactly when it matched.

Splitting the bundle is what makes that cutoff irrelevant *here*: every piece is
now far below both the cutoff and the per-route budget, so each one routes on its
own concern and the guard never touches it.  The guard itself remains in place
for the two references that are still oversized.

These tests hold the fix in place from both ends: every piece must be reachable
through the real selection path for its own concern, and the bundle must retain
its required topics while allowing reviewed rules to evolve.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_doc_resolution import doc_size  # noqa: E402
from workflow_route import (  # noqa: E402
    REQUIRED_DOC_BUDGET_BYTES,
    resolve_docs,
)

BUNDLE = "platforms/android/skills/android-module-structure"
REFS = f"{BUNDLE}/references"
ENTRYPOINT = f"{BUNDLE}/SKILL.md"
CORE = f"{REFS}/current-guidance.md"

BOUNDARIES = f"{REFS}/module-boundaries.md"
LAYOUT = f"{REFS}/module-layout.md"
COMPOSE_ENTRY = f"{REFS}/compose-entry-contracts.md"
DI_BUILD = f"{REFS}/di-build-logic.md"
SPLIT_MIGRATION = f"{REFS}/split-and-migration.md"
SKILL_SOURCE = f"{REFS}/skill-source-coverage.md"
REVIEW_CHECKLIST = f"{REFS}/review-checklist.md"

TOPIC_DOCS = (
    BOUNDARIES,
    LAYOUT,
    COMPOSE_ENTRY,
    DI_BUILD,
    SPLIT_MIGRATION,
    SKILL_SOURCE,
    REVIEW_CHECKLIST,
)

# The bundle's content before the split, recovered from git so the preservation
# check compares against the real original rather than a copy that could drift.
ORIGINAL_REV = "3c871dc"


def android_route(*concerns: str, request_text: str = "") -> dict:
    return resolve_docs(
        "feature",
        "android",
        list(concerns),
        request_classified=True,
        request_text=request_text or "Android module structure work",
    )


def original_reference_text() -> str:
    result = subprocess.run(
        ["git", "show", f"{ORIGINAL_REV}:{CORE}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # This runtime is installed as a copy, so the revision that carried the
        # pre-split reference is unreachable from here. The comparison only
        # means something where that history exists.
        raise unittest.SkipTest(f"revision {ORIGINAL_REV} is unavailable in {ROOT}")
    return result.stdout


class BundlePieceRoutabilityTests(unittest.TestCase):
    """Each piece must be selectable on its own, not merely graph-reachable.

    A sibling reference has no `SKILL.md` entrypoint for `resolve_guidance_docs`
    to resolve, so it reaches a route only if a registry names it directly.
    """

    def test_module_concern_delivers_boundary_and_layout_rules(self) -> None:
        required = android_route("module")["required_docs"]

        self.assertIn(BOUNDARIES, required)
        self.assertIn(LAYOUT, required)

    def test_module_concern_does_not_deliver_unrelated_build_or_source_material(
        self,
    ) -> None:
        """Discrimination is the whole point: the right piece, not every piece."""
        required = android_route("module")["required_docs"]

        self.assertNotIn(DI_BUILD, required)
        self.assertNotIn(SKILL_SOURCE, required)
        self.assertNotIn(COMPOSE_ENTRY, required)

    def test_compose_concern_delivers_the_compose_entry_contract_rules(self) -> None:
        required = android_route("compose")["required_docs"]

        self.assertIn(COMPOSE_ENTRY, required)
        self.assertNotIn(DI_BUILD, required)

    def test_dependency_concern_delivers_the_di_and_build_logic_rules(self) -> None:
        required = android_route("dependency")["required_docs"]

        self.assertIn(DI_BUILD, required)
        self.assertIn(LAYOUT, required)
        self.assertNotIn(SKILL_SOURCE, required)

    def test_migration_concern_delivers_the_split_and_migration_rules(self) -> None:
        self.assertIn(SPLIT_MIGRATION, android_route("migration")["required_docs"])

    def test_skill_concern_delivers_the_external_source_coverage_rules(self) -> None:
        self.assertIn(SKILL_SOURCE, android_route("skill")["required_docs"])

    def test_di_request_text_reaches_build_logic_without_an_explicit_concern(
        self,
    ) -> None:
        """Natural language must reach the piece; not every caller names a concern."""
        required = android_route(
            request_text=(
                "Add a Hilt convention plugin in build-logic and move the route "
                "handler bindings into multibindings"
            )
        )["required_docs"]

        self.assertIn(DI_BUILD, required)

    def test_every_topic_piece_is_reachable_through_some_android_concern(self) -> None:
        concerns = (
            "module",
            "structure",
            "architecture",
            "dependency",
            "config",
            "migration",
            "compose",
            "ui",
            "api",
            "skill",
        )
        reachable: set[str] = set()
        for concern in concerns:
            reachable.update(android_route(concern)["required_docs"])

        unreachable = [doc for doc in TOPIC_DOCS if doc not in reachable]
        self.assertEqual([], unreachable)


class BundleSizeTests(unittest.TestCase):
    def test_no_bundle_document_exceeds_the_required_doc_budget(self) -> None:
        """A piece larger than the budget would monopolise the route again."""
        oversized = {
            path: doc_size(ROOT, path)
            for path in (CORE, *TOPIC_DOCS)
            if doc_size(ROOT, path) > REQUIRED_DOC_BUDGET_BYTES
        }

        self.assertEqual({}, oversized)


class BundleContentCoverageTests(unittest.TestCase):
    """The split retains its topics without freezing every old sentence."""

    def bundle_text(self) -> str:
        return "\n".join(
            path.read_text() for path in sorted((ROOT / REFS).glob("*.md"))
        )

    def test_every_original_section_heading_survives_somewhere_in_the_bundle(
        self,
    ) -> None:
        original = original_reference_text()
        headings = re.findall(r"(?m)^## .*$", original)
        bundle = self.bundle_text()

        self.assertEqual(20, len(headings))
        self.assertEqual([], [h for h in headings if h not in bundle])

    def test_boundary_examples_cover_compose_and_activity_entry_shapes(self) -> None:
        bundle = self.bundle_text()

        self.assertIn("`api` + `ui`", bundle)
        self.assertIn("`api` + `impl`", bundle)
        self.assertIn("`api` + `ui` + `impl`", bundle)


class BundleShapeTests(unittest.TestCase):
    def test_each_topic_piece_has_frontmatter_and_a_single_h1(self) -> None:
        for path in TOPIC_DOCS:
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                self.assertTrue(text.startswith("---\n"), path)
                self.assertIn("keyflow_id:", text.split("---")[1])
                self.assertEqual(1, len(re.findall(r"(?m)^# ", text)), path)

    def test_the_core_document_still_carries_the_always_applicable_rules(self) -> None:
        """Routes that only reach the entrypoint must still get the core rules."""
        text = (ROOT / CORE).read_text()

        self.assertIn("## Default Rule", text)
        self.assertIn("## File And Class Split", text)

    def test_the_core_document_indexes_every_topic_piece(self) -> None:
        text = (ROOT / CORE).read_text()

        for path in TOPIC_DOCS:
            with self.subTest(path=path):
                self.assertIn(Path(path).name, text)


class FeatureUiBoundaryContractTests(unittest.TestCase):
    def test_canonical_contract_puts_complete_compose_feature_in_ui(self) -> None:
        text = (ROOT / BOUNDARIES).read_text()

        self.assertIn("holder `Route`, ViewModel, `UiState`", text)
        self.assertIn("`ui` is standalone from the feature's `impl`", text)
        self.assertIn("`api + ui`", text)
        self.assertIn("`api + impl`", text)
        self.assertIn("`api` + `ui` + `impl`", text)

    def test_dependent_guidance_preserves_ui_dependency_direction(self) -> None:
        layout = (ROOT / LAYOUT).read_text()
        entry = (ROOT / COMPOSE_ENTRY).read_text()

        self.assertIn("`feature-ui -> feature-impl`", layout)
        self.assertRegex(
            entry,
            r"Neither `api`\s+nor `ui` may depend on\s+`impl`",
        )
        self.assertIn("Do not copy the same composable signature", entry)

    def test_activity_platform_code_stays_in_optional_impl(self) -> None:
        boundaries = (ROOT / BOUNDARIES).read_text()
        layout = (ROOT / LAYOUT).read_text()

        self.assertIn("concrete Activities, manifest", boundaries)
        self.assertIn("Intent/request/result mapping", layout)

    def test_route_example_uses_hilt_assisted_creation_for_the_key(self) -> None:
        text = (ROOT / BOUNDARIES).read_text()

        self.assertIn("@HiltViewModel(assistedFactory", text)
        self.assertIn("creationCallback = { factory -> factory.create(key) }", text)
        self.assertNotIn("profileViewModel(", text)
        self.assertNotIn("LaunchedEffect(key)", text)

    def test_legacy_ui_ownership_rules_do_not_return(self) -> None:
        text = "\n".join(
            (ROOT / path).read_text()
            for path in (
                CORE,
                BOUNDARIES,
                LAYOUT,
                COMPOSE_ENTRY,
                SPLIT_MIGRATION,
                REVIEW_CHECKLIST,
            )
        )

        self.assertNotIn("`impl` owns Compose UI by default", text)
        self.assertNotIn("`ui` must not own ViewModels", text)


if __name__ == "__main__":
    unittest.main()
