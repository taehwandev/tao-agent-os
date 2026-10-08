"""KMP desktop changes route to the desktop nodes and the parents they refine.

A Compose desktop window, a JVM process adapter or a state holder each needs
its own small node. The node then brings the shared parent it narrows through
`refines`, so the route reads the desktop delta together with the baseline.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_route import resolve_docs


NODES = "platforms/kmp/nodes/"
APPLICATION = "platforms/application/skills/"


def required(command: str, *, paths: list[str] | None = None, request: str = "") -> list[str]:
    route = resolve_docs(
        command,
        "kmp",
        [],
        request_text=request,
        request_classified=True,
        surface_paths=paths or [],
    )
    return route["required_docs"]


class KmpDesktopPathRoutingTest(unittest.TestCase):
    def test_window_file_requires_shell_node_and_its_parent(self) -> None:
        docs = required("feature", paths=["app/src/desktopMain/kotlin/app/MainWindow.kt"])

        self.assertIn(NODES + "desktop-shell.md", docs)
        self.assertIn(APPLICATION + "application-command-ui/references/current-guidance.md", docs)
        self.assertNotIn(NODES + "desktop-review.md", docs)

    def test_process_file_requires_process_node_parent_and_scope_rules(self) -> None:
        docs = required("bugfix", paths=["core/terminal/src/desktopMain/kotlin/term/PtyProcessHost.kt"])

        self.assertIn(NODES + "desktop-process-pty.md", docs)
        self.assertIn(APPLICATION + "application-system-integration/references/current-guidance.md", docs)
        self.assertIn("platforms/compose/nodes/coroutine-flow-ownership.md", docs)

    def test_state_holder_file_requires_kmp_and_compose_holder_nodes(self) -> None:
        docs = required("feature", paths=["feature/git/src/commonMain/kotlin/git/GitStateHolder.kt"])

        self.assertIn(NODES + "state-holder.md", docs)
        self.assertIn("platforms/compose/nodes/state-holder-surface.md", docs)

    def test_review_route_adds_the_desktop_review_checklist(self) -> None:
        docs = required("review", paths=["app/src/desktopMain/kotlin/app/MainWindow.kt"])

        self.assertIn(NODES + "desktop-review.md", docs)

    def test_desktop_route_stays_within_reading_budget(self) -> None:
        docs = required("feature", paths=["core/terminal/src/desktopMain/kotlin/term/PtyProcessHost.kt"])
        size = sum(os.path.getsize(ROOT / doc) for doc in docs if (ROOT / doc).exists())

        self.assertLessEqual(size, 100_000, f"{size}B required")


class KmpDesktopRequestRoutingTest(unittest.TestCase):
    def test_packaging_request_requires_packaging_node(self) -> None:
        docs = required("build", request="notarize the dmg and fix codesign for the pty helper")

        self.assertIn(NODES + "desktop-packaging.md", docs)
        self.assertIn(APPLICATION + "application-security/references/current-guidance.md", docs)

    def test_korean_architecture_enforcement_request_requires_enforcement_node(self) -> None:
        docs = required("refactor", request="모듈 의존 방향 검사를 추가해서 아키텍처 강제")

        self.assertIn(NODES + "architecture-enforcement.md", docs)


if __name__ == "__main__":
    unittest.main()
