"""Figma extraction reads the tool and writes only its output bundle."""
from __future__ import annotations

import ast
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import claude_bash_readonly as readonly
import claude_bash_figma as figma
from tests.test_claude_pretool_gate import _decide, _opt_in_project, _reason, _require_linked_worktree

CLI = ROOT / "scripts/figma-handoff/figma-handoff.py"
URL = "https://www.figma.com/design/example/Example?node-id=123-456&m=dev"


class FigmaCommandTests(unittest.TestCase):
    def tokens(self, *args):
        return ["python3", "-B", str(CLI), "--url", URL, *args]

    def test_dry_run_is_read_only_and_does_not_need_a_product_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp) / "product")
            _require_linked_worktree(root)
            tokens = self.tokens("--out", str(root / "bundle"), "--dry-run")
            self.assertEqual("read_only", readonly.simple_command_kind(tokens, root))
            self.assertEqual((0, ""), _decide({
                "tool_name": "Bash", "cwd": str(root), "session_id": "figma-read",
                "tool_input": {"command": shlex.join(tokens)},
            }))

    def test_extraction_exempts_source_and_url_but_keeps_output(self):
        tokens = self.tokens("--out", "/tmp/output", "--max-flow-depth", "0", "--export-assets")
        indices = readonly.read_only_path_token_indices(tokens, Path("/tmp"))
        self.assertIn(2, indices)
        self.assertIn(4, indices)
        self.assertNotIn(6, indices)
        self.assertEqual("mutating", readonly.simple_command_kind(tokens, Path("/tmp")))

    def test_real_extraction_does_not_demand_entry_for_the_tool_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp)
            with unittest.mock.patch(
                "claude_pretool_gate.worktree_denial",
                side_effect=lambda root, *args, **kwargs: "source misclassified" if root == ROOT else "",
            ):
                code, out = _decide({
                    "tool_name": "Bash", "cwd": str(outside), "session_id": "figma-source",
                    "tool_input": {"command": shlex.join(self.tokens("--out", str(outside / "bundle")))},
                })
            self.assertEqual(0, code)
            self.assertNotIn("source misclassified", out)

    def test_cli_dry_run_creates_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            result = subprocess.run(
                self.tokens("--out", str(output), "--dry-run"),
                cwd=tmp, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(output.exists())

    def test_canonical_validator_reads_summary_but_not_redirect_targets(self):
        tokens = ["python3", "-B", str(CLI.with_name("figma_validate.py")), "/tmp/summary.json"]
        self.assertEqual("read_only", readonly.simple_command_kind(tokens, Path("/tmp")))
        self.assertEqual(frozenset(range(4)), readonly.read_only_path_token_indices(tokens, Path("/tmp")))
        self.assertNotEqual("read_only", readonly.bash_command_kind(
            [*tokens, ">", str(ROOT / "report")], False, Path("/tmp"),
        ))

    def test_canonical_guidance_uses_bytecode_free_and_copy_only_commands(self):
        guidance = (ROOT / "common/skills/figma-handoff/references/current-guidance.md").read_text()
        self.assertEqual(2, guidance.count('python3 -B "$HANDOFF_CLI"'))
        self.assertIn('python3 -B "$REPO_ROOT/scripts/figma-handoff/figma_validate.py"', guidance)
        self.assertIn("copy-only", guidance)
        self.assertIn("--max-flow-depth 0", guidance)
        self.assertIn("without `--export-assets`", guidance)

    def test_closed_grammar_matches_the_cli_parser(self):
        tree = ast.parse((CLI.parent / "figma_cli_arguments.py").read_text())
        values, flags = set(), set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "add_argument":
                continue
            target = flags if any(
                keyword.arg == "action" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "store_true" for keyword in node.keywords
            ) else values
            target.add(node.args[0].value)
        self.assertEqual(values, figma._VALUES)
        self.assertEqual(flags, figma._FLAGS)

    def test_protected_output_still_denied_from_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _opt_in_project(Path(tmp) / "protected")
            _require_linked_worktree(root)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            for option in (("--out", str(root / "bundle")), (f"--out={root}/bundle",)):
                with self.subTest(option=option):
                    code, out = _decide({
                        "tool_name": "Bash", "cwd": str(outside), "session_id": "figma-output",
                        "tool_input": {"command": shlex.join(self.tokens(*option))},
                    })
                    self.assertEqual(0, code)
                    self.assertIn("worktree gate", _reason(out))

    def test_unknown_script_flags_interpreter_and_redirection_keep_protection(self):
        cases = (
            ["python3", str(CLI), "--dry-run"],
            ["python3", "-B", "/tmp/figma-handoff.py", "--dry-run"],
            ["/tmp/python3", "-B", str(CLI), "--dry-run"],
            self.tokens("--unknown", "--dry-run"),
            self.tokens("--out"),
            self.tokens("--dry-run", ">", "/tmp/file"),
            self.tokens("--dry-run", ";", "touch", str(ROOT / "file")),
        )
        for tokens in cases:
            with self.subTest(tokens=tokens):
                self.assertNotEqual("read_only", readonly.bash_command_kind(tokens, False, Path("/tmp")))
                if ";" in tokens:
                    self.assertNotIn(len(tokens) - 1, readonly.read_only_path_token_indices(tokens, Path("/tmp")))


if __name__ == "__main__":
    unittest.main()
