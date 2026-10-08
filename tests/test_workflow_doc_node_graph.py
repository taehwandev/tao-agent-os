"""Typed node relations and the validation that keeps them routable.

Guidance nodes reach each other through `requires`, `refines` and
`verified_by` frontmatter. A route follows the first two for every command and
the third only for review work; validation rejects nodes a route cannot use.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_doc_graph import (
    clear_doc_graph_cache,
    expand_doc_matches,
    expand_required_doc_matches,
    graph_required_docs,
)
from workflow_doc_node_rules import node_graph_failures
from workflow_doc_resolution import resolve_guidance_docs
from workflow_route import VERIFICATION_NODE_COMMANDS


def _node(
    *,
    requires: str = "",
    refines: str = "",
    verified_by: str = "",
    use_when: str = "editing desktop windows",
    skip_when: str = "no desktop target",
    body: str = "# Node\n\n## Rules\n\n- One rule.\n\n## Verification\n\n- Run a check.\n",
) -> str:
    header = ["---", "keyflow_id: test_node", "status: draft", "type: ai-generated"]
    if use_when:
        header.append(f"use_when: {use_when}")
    if skip_when:
        header.append(f"skip_when: {skip_when}")
    for key, value in (("requires", requires), ("refines", refines), ("verified_by", verified_by)):
        if value:
            header.append(f"{key}:")
            header.extend(f"  - {item}" for item in value.split(","))
    header.append("---")
    return "\n".join(header) + "\n" + body


class NodeRelationExpansionTest(unittest.TestCase):
    def _project(self, directory: str) -> Path:
        root = Path(directory)
        nodes = root / "kmp" / "nodes"
        nodes.mkdir(parents=True)
        (root / "android" / "nodes").mkdir(parents=True)
        (nodes / "shell.md").write_text(
            _node(
                refines="android/nodes/base.md",
                requires="kmp/nodes/scope.md",
                verified_by="kmp/nodes/shell-review.md",
            ),
            encoding="utf-8",
        )
        (root / "android" / "nodes" / "base.md").write_text(_node(), encoding="utf-8")
        (nodes / "scope.md").write_text(_node(), encoding="utf-8")
        (nodes / "shell-review.md").write_text(_node(), encoding="utf-8")
        return root

    def test_refines_parent_is_promoted_with_requires(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            matches = expand_required_doc_matches(root, ["kmp/nodes/shell.md"])

        relations = {match["path"]: match["relation"] for match in matches}
        self.assertEqual("frontmatter:refines", relations["android/nodes/base.md"])
        self.assertEqual("frontmatter:requires", relations["kmp/nodes/scope.md"])
        self.assertNotIn("kmp/nodes/shell-review.md", relations)
        self.assertEqual(
            {"android/nodes/base.md", "kmp/nodes/scope.md"},
            set(graph_required_docs(matches)),
        )

    def test_verification_node_is_promoted_only_for_review_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            matches = expand_required_doc_matches(
                root, ["kmp/nodes/shell.md"], include_verification=True
            )

        self.assertIn("kmp/nodes/shell-review.md", graph_required_docs(matches))
        self.assertIn("review", VERIFICATION_NODE_COMMANDS)
        self.assertNotIn("feature", VERIFICATION_NODE_COMMANDS)

    def test_node_files_are_read_as_they_are(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            resolved = resolve_guidance_docs(root, ["kmp/nodes/shell.md"])

        self.assertEqual(["kmp/nodes/shell.md"], resolved)

    def test_document_set_membership_alone_adds_no_graph_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "a.md").write_text("# A\n", encoding="utf-8")
            (root / "docs" / "b.md").write_text("# B\n", encoding="utf-8")
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
            matches = expand_doc_matches(root, ["docs/a.md"], max_depth=1)

        self.assertEqual([], matches)


class NodeValidationTest(unittest.TestCase):
    def _failures(self, files: dict[str, str], entries: tuple[str, ...] = ()) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, text in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return node_graph_failures(root, files, entries)

    def test_reachable_well_formed_node_passes(self) -> None:
        failures = self._failures(
            {"kmp/nodes/a.md": _node(requires="kmp/nodes/b.md"), "kmp/nodes/b.md": _node()},
            entries=("kmp/nodes/a.md",),
        )

        self.assertEqual([], failures)

    def test_node_without_trigger_or_exclusion_fails(self) -> None:
        failures = self._failures(
            {"kmp/nodes/a.md": _node(use_when="", skip_when="")}, entries=("kmp/nodes/a.md",)
        )

        self.assertTrue(any("`use_when`" in item for item in failures))
        self.assertTrue(any("`skip_when`" in item for item in failures))

    def test_node_without_verification_section_fails(self) -> None:
        failures = self._failures(
            {"kmp/nodes/a.md": _node(body="# Node\n\n## Rules\n\n- One rule.\n")},
            entries=("kmp/nodes/a.md",),
        )

        self.assertTrue(any("## Verification" in item for item in failures))

    def test_oversized_node_fails(self) -> None:
        body = "# Node\n\n## Verification\n\n" + "- line\n" * 200
        failures = self._failures({"kmp/nodes/a.md": _node(body=body)}, entries=("kmp/nodes/a.md",))

        self.assertTrue(any("split it below" in item for item in failures))

    def test_unreachable_node_is_an_orphan(self) -> None:
        failures = self._failures({"kmp/nodes/a.md": _node()})

        self.assertEqual(["kmp/nodes/a.md: orphan node; no route rule or document reaches it"], failures)

    def test_dangling_relation_fails_for_any_document(self) -> None:
        failures = self._failures(
            {"common/skills/x/SKILL.md": _node(refines="common/skills/missing/SKILL.md")}
        )

        self.assertEqual(
            ["common/skills/x/SKILL.md: refines target does not exist: common/skills/missing/SKILL.md"],
            failures,
        )

    def test_missing_backtick_reference_in_node_fails(self) -> None:
        body = "# Node\n\nSee `kmp/nodes/gone.md`.\n\n## Verification\n\n- Check.\n"
        failures = self._failures({"kmp/nodes/a.md": _node(body=body)}, entries=("kmp/nodes/a.md",))

        self.assertEqual(["kmp/nodes/a.md: node references a missing document: kmp/nodes/gone.md"], failures)

    def test_requires_and_refines_cycle_is_reported_once(self) -> None:
        failures = self._failures(
            {
                "kmp/nodes/a.md": _node(requires="kmp/nodes/b.md"),
                "kmp/nodes/b.md": _node(refines="kmp/nodes/a.md"),
            },
            entries=("kmp/nodes/a.md",),
        )

        self.assertEqual(
            ["frontmatter dependency cycle: kmp/nodes/a.md -> kmp/nodes/b.md -> kmp/nodes/a.md"],
            failures,
        )

    def test_verified_by_back_edge_is_not_a_cycle(self) -> None:
        failures = self._failures(
            {
                "kmp/nodes/a.md": _node(verified_by="kmp/nodes/b.md"),
                "kmp/nodes/b.md": _node(refines="kmp/nodes/a.md"),
            },
            entries=("kmp/nodes/a.md",),
        )

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
