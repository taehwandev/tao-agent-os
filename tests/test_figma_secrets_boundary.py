from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = REPO_ROOT / "scripts" / "figma-handoff"
RUNTIME_FILES = (
    "figma-handoff.py",
    "figma_analyze.py",
    "figma_api.py",
    "figma_fetch.py",
    "figma_parse.py",
    "figma_report.py",
    "figma_util.py",
    "figma_validate.py",
)


class FigmaSecretsBoundaryTests(unittest.TestCase):
    def test_local_work_directory_is_hidden_and_ignored(self) -> None:
        ignore_rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/.figma-handoff-work/", ignore_rules.splitlines())

    def test_tool_text_has_no_local_paths_or_token_material(self) -> None:
        # The docs may NAME the X-Figma-Token header; a header assignment with a
        # literal value, a real token prefix, or a personal absolute path must
        # never appear anywhere in the tool directory.
        forbidden = ("/Users/", "figd_")
        text_suffixes = {".md", ".py"}
        for path in TOOL_DIR.rglob("*"):
            if path.suffix not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(TOOL_DIR)):
                for marker in forbidden:
                    self.assertNotIn(marker, text)

    def test_runtime_imports_do_not_depend_on_verification_code(self) -> None:
        forbidden_roots = {"examples", "tests", "live_smoke"}
        for filename in RUNTIME_FILES:
            path = TOOL_DIR / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
            imported_roots: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".")[0])
            with self.subTest(filename=filename):
                self.assertEqual(imported_roots & forbidden_roots, set())


if __name__ == "__main__":
    unittest.main()
