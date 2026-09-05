from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from support.graphify_checkout_repair import repair_checkout_hook

# The relevant upstream shell/Python nesting, with the expensive extractor
# replaced by an observable boundary. Git, shell, arguments and repair are real.
SCRIPT = """#!/bin/sh
# user-before
# graphify-checkout-hook-start
# Installed by: graphify hook install
PREV_HEAD=$1
NEW_HEAD=$2
BRANCH_SWITCH=$3
[ "$BRANCH_SWITCH" != "1" ] && exit 0
"$TEST_PYTHON" -c "
_src = '''
import json, os, sys
from pathlib import Path

def _rebuild_code(root, *, changed_paths=None, force=False):
    print(json.dumps(dict(root=str(root), paths=None if changed_paths is None else [str(p) for p in changed_paths])))

try:
    _root = Path('/copied/graph/root')
    _force = False
    _rebuild_code(_root, force=_force)
except Exception:
    raise
'''
exec(_src)
"
# graphify-checkout-hook-end
# user-after
"""


class GraphifyCheckoutRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("config", "core.hooksPath", ".git/hooks")
        self.source = self.project / "설정.py"
        self.source.write_text("before\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.before = self.git("rev-parse", "HEAD")
        self.source.write_text("after\n")
        self.git("add", ".")
        self.git("commit", "-qm", "change")
        self.after = self.git("rev-parse", "HEAD")
        self.hook = self.project / ".git/hooks/post-checkout"
        self.hook.write_text(SCRIPT)
        self.hook.chmod(0o755)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.project, check=True, capture_output=True, text=True
        ).stdout.strip()

    def run_hook(self, before: str, after: str, **environment: str) -> list[dict]:
        env = {
            **os.environ, "TEST_PYTHON": sys.executable,
            "GRAPHIFY_SKIP_HOOK": "0", **environment,
        }
        done = subprocess.run(
            ["sh", str(self.hook), before, after, "1"], cwd=self.project,
            env=env, capture_output=True, text=True, check=True,
        )
        return [json.loads(line) for line in done.stdout.splitlines() if line]

    def test_same_head_and_skip_do_not_rebuild_with_negative_control(self) -> None:
        # The unmodified upstream shape still rebuilds for both conditions.
        self.assertEqual(1, len(self.run_hook(self.after, self.after)))
        self.assertEqual(1, len(self.run_hook(
            self.before, self.after, GRAPHIFY_SKIP_HOOK="1"
        )))
        self.assertTrue(repair_checkout_hook(self.project)["ready"])
        self.assertEqual([], self.run_hook(self.after, self.after))
        self.assertEqual([], self.run_hook(
            self.before, self.after, GRAPHIFY_SKIP_HOOK="1"
        ))

    def test_real_git_diff_preserves_unicode_and_newlines(self) -> None:
        extra = self.project / "line\nbreak.py"
        extra.write_text("changed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "unusual name")
        last = self.git("rev-parse", "HEAD")
        self.assertTrue(repair_checkout_hook(self.project)["ready"])
        result = self.run_hook(self.before, last)
        self.assertEqual(1, len(result))
        self.assertEqual({"설정.py", "line\nbreak.py"}, set(result[0]["paths"]))
        self.assertEqual(str(self.project), result[0]["root"])

    def test_same_tree_skips_and_unknown_old_commit_retains_full_fallback(self) -> None:
        self.git("commit", "--allow-empty", "-qm", "same tree")
        last = self.git("rev-parse", "HEAD")
        self.assertTrue(repair_checkout_hook(self.project)["ready"])
        self.assertEqual([], self.run_hook(self.after, last))
        self.assertIsNone(self.run_hook("0" * 40, last)[0]["paths"])

    def test_preview_idempotence_backup_and_unrelated_bytes(self) -> None:
        original = self.hook.read_bytes()
        preview = repair_checkout_hook(self.project, dry_run=True)
        self.assertTrue(preview["ready"])
        self.assertTrue(preview["changed"])
        self.assertEqual(original, self.hook.read_bytes())
        backup = self.hook.with_name("post-checkout.tao-before-repair")
        self.assertFalse(backup.exists())
        self.assertTrue(repair_checkout_hook(self.project)["changed"])
        repaired = self.hook.read_bytes()
        self.assertEqual(original, backup.read_bytes())
        self.assertEqual(0o755, self.hook.stat().st_mode & 0o777)
        self.assertTrue(repaired.startswith(b"#!/bin/sh\n# user-before\n"))
        self.assertTrue(repaired.endswith(b"# graphify-checkout-hook-end\n# user-after\n"))
        self.assertFalse(repair_checkout_hook(self.project)["changed"])
        self.assertEqual(repaired, self.hook.read_bytes())
        self.assertEqual(original, backup.read_bytes())

    def test_unknown_or_modified_template_is_not_written(self) -> None:
        unknown = SCRIPT.replace("_rebuild_code(_root, force=_force)", "_new_rebuild(_root)")
        self.hook.write_text(unknown)
        result = repair_checkout_hook(self.project)
        self.assertFalse(result["ready"])
        self.assertEqual(unknown, self.hook.read_text())
        self.hook.write_text(SCRIPT)
        self.assertTrue(repair_checkout_hook(self.project)["ready"])
        altered = self.hook.read_text().replace("changed_paths=_changed", "changed_paths=None")
        self.hook.write_text(altered)
        self.assertFalse(repair_checkout_hook(self.project)["ready"])
        self.assertEqual(altered, self.hook.read_text())

    def test_symlink_and_external_hook_directory_are_refused(self) -> None:
        target = self.project / "other-hook"
        target.write_text(SCRIPT)
        self.hook.unlink()
        self.hook.symlink_to(target)
        self.assertFalse(repair_checkout_hook(self.project)["ready"])
        with tempfile.TemporaryDirectory() as directory:
            external = Path(directory) / "post-checkout"
            external.write_text(SCRIPT)
            self.git("config", "core.hooksPath", directory)
            self.assertFalse(repair_checkout_hook(self.project)["ready"])
            self.assertEqual(SCRIPT, external.read_text())

    def test_cli_preview_does_not_require_or_read_graph(self) -> None:
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/setup-project-graphify.py"),
             "--project", str(self.project), "--repair-checkout-hook", "--check",
             "--format", "json"], capture_output=True, text=True, check=True,
        )
        report = json.loads(done.stdout)["projects"][0]
        self.assertTrue(report["success"])
        self.assertTrue(report["checkout_hook"]["changed"])
        self.assertEqual(SCRIPT, self.hook.read_text())
        self.assertFalse((self.project / ".agents/local/graphify-out").exists())


if __name__ == "__main__":
    unittest.main()
