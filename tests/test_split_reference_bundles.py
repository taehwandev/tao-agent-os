"""The two references that outlived the oversize guard, and what replaced it.

A split is only safe if it moved text rather than rewrote it, and only useful if
each piece can be selected on its own. Both properties are asserted here for the
two bundles that were still oversized when `OVERSIZED_DOC_BYTES` was deleted, so
a later edit that regrows one fails against the budget it now actually competes
in rather than against a guard that no longer exists.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_route import REQUIRED_DOC_BUDGET_BYTES  # noqa: E402

BUNDLES = {
    "code-structure-ownership": (
        "common/skills/code-structure-ownership",
        ("current-guidance.md", "unit-size.md", "structure-stops.md"),
    ),
    "session-continuation-protocol": (
        "workflows/skills/session-continuation-protocol",
        ("current-guidance.md", "decisions.md", "packet-contract.md"),
    ),
}


def _reference(bundle: str, name: str) -> Path:
    return ROOT / BUNDLES[bundle][0] / "references" / name


class BundleSizeTests(unittest.TestCase):
    """Each piece competes for required reading, so each must fit in it."""

    def test_no_piece_exceeds_the_required_doc_budget(self) -> None:
        oversized = {
            f"{bundle}/{name}": _reference(bundle, name).stat().st_size
            for bundle, (_root, names) in BUNDLES.items()
            for name in names
            if _reference(bundle, name).stat().st_size > REQUIRED_DOC_BUDGET_BYTES
        }

        self.assertEqual({}, oversized)

    def test_every_named_piece_exists(self) -> None:
        # A rename that updates the entrypoint and forgets this list would
        # otherwise leave the size assertion silently checking fewer files.
        missing = [
            f"{bundle}/{name}"
            for bundle, (_root, names) in BUNDLES.items()
            for name in names
            if not _reference(bundle, name).is_file()
        ]

        self.assertEqual([], missing)


class BundleContentPreservationTests(unittest.TestCase):
    """The split was a move, not an edit."""

    # Sentences from inside each moved section, not its heading. The core keeps
    # a pointer stub under the same heading, so a heading anchor finds the
    # pointer and reports success for content that was never moved -- which is
    # what the first version of these tests did.
    ANCHORS = {
        "code-structure-ownership": (
            "Use code size as review pressure, not an automatic split command.",
            "Do not continue implementation when any of these are true:",
            "sketch the structure before",
        ),
        "session-continuation-protocol": (
            "A Stop hook is an optional final flush and never a correctness",
            "Unknown fields and unknown enum values are invalid.",
            "The shared library owns:",
        ),
    }

    def _bundle_text(self, bundle: str) -> str:
        return "\n".join(
            _reference(bundle, name).read_text(encoding="utf-8")
            for name in BUNDLES[bundle][1]
        )

    def test_every_sentence_that_was_there_is_still_reachable(self) -> None:
        for bundle, anchors in self.ANCHORS.items():
            text = self._bundle_text(bundle)
            for anchor in anchors:
                with self.subTest(bundle=bundle, anchor=anchor):
                    self.assertIn(anchor, text)

    def test_moved_content_lives_in_exactly_one_piece(self) -> None:
        """Copied rather than moved is the failure this catches.

        Two copies drift, and the one nobody edits is the one a route loads.
        """

        for bundle, anchors in self.ANCHORS.items():
            for anchor in anchors:
                homes = [
                    name
                    for name in BUNDLES[bundle][1]
                    if anchor in _reference(bundle, name).read_text(encoding="utf-8")
                ]
                with self.subTest(bundle=bundle, anchor=anchor):
                    self.assertEqual(1, len(homes), homes)


class BundleEntrypointTests(unittest.TestCase):
    """A piece a route cannot reach is a piece that was deleted."""

    def test_the_entrypoint_names_every_piece(self) -> None:
        for bundle, (root, names) in BUNDLES.items():
            skill = (ROOT / root / "SKILL.md").read_text(encoding="utf-8")
            for name in names:
                with self.subTest(bundle=bundle, name=name):
                    self.assertIn(f"references/{name}", skill)


class GuardRemovalTests(unittest.TestCase):
    """The stopgap's own deletion condition, kept as a standing property."""

    # The threshold the deleted constant held, kept by value rather than by
    # name so this assertion cannot be satisfied by redefining it.
    FORMER_GUARD_BYTES = 40_000

    def test_no_reference_in_the_repository_trips_the_former_guard(self) -> None:
        """The command the deleted comment told the reader to run.

        `OVERSIZED_DOC_BYTES` skipped a reference too large to admit at all.
        Nothing in the tree trips that any more, which is why the constant is
        gone -- and this keeps it gone rather than trusting nobody adds one back.

        This asserts the guard's threshold, not the budget. Two references sit
        between the two numbers, which is a smaller and separate problem: they
        are selectable, and selecting one exhausts the budget on its own.
        """

        oversized = sorted(
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*/references/*.md")
            if ".tao" not in path.parts
            and path.stat().st_size > self.FORMER_GUARD_BYTES
        )

        self.assertEqual([], oversized)

    def test_the_constant_is_not_reintroduced(self) -> None:
        # Named rather than implied: re-adding the constant would restore a
        # silent skip in the selection loop that ranking does not explain.
        source = (SCRIPTS / "workflow_route.py").read_text(encoding="utf-8")

        self.assertNotIn("OVERSIZED_DOC_BYTES", source)


if __name__ == "__main__":
    unittest.main()
