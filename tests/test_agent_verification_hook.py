"""Execution results, source drift and admission through the optional runner."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _tao_test_support import ROOT, TemplateRepository
import agent_verification_hook as verify
from agent_gate_evidence import gate_evidence_path_for_preflight


def _build_fixture(project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".tao/\n__pycache__/\n")
    subprocess.run(["git", "-C", str(project), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)


_FIXTURE = TemplateRepository(_build_fixture)


def tearDownModule():
    _FIXTURE.cleanup()


class VerificationHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        _FIXTURE.copy_to(self.project)
        (self.project / "tests").mkdir()
        self.path = self.project / ".tao" / "preflight.json"
        self.path.parent.mkdir()
        self.session = {"runtime": "codex", "session_id": "fixture"}
        self.preflight = {"project": str(self.project), "rules": str(self.project),
                          "runtime_session": self.session, "route": {"gates": ["tests"]}}
        self.path.write_text(json.dumps(self.preflight))
        self.args = SimpleNamespace(project=self.project, rules=self.project, evidence=self.path,
                                    test_directory="tests", test_pattern="test_*.py", verify_timeout=5)
        self.addCleanup(patch.stopall)
        patch.object(verify, "runtime_session", return_value=self.session).start()
        self.bound = patch.object(verify, "resolve_runtime_evidence", return_value=self.path).start()

    def run_hook(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return verify.verification_hook(self.args)

    def entries(self):
        return json.loads(gate_evidence_path_for_preflight(self.path).read_text())["entries"]

    def write_test(self, body="self.assertTrue(True)"):
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\nfrom pathlib import Path\nimport time\n"
            f"class Case(unittest.TestCase):\n    def test_case(self):\n        {body}\n")

    def test_pass_records_observed_count_and_failure_replaces_pass(self):
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.assertEqual("SUCCESS", self.entries()[-1]["status"])
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])
        self.write_test("self.fail('expected')")
        self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=1", self.entries()[-1]["fields"]["result"])

    def test_zero_tests_does_not_pass(self):
        self.assertEqual(1, self.run_hook())
        self.assertIn("tests=0", self.entries()[-1]["fields"]["result"])

    def test_project_packages_take_priority_over_hook_packages(self):
        (self.project / "tests" / "__init__.py").write_text("")
        (self.project / "tests" / "helper.py").write_text("VALUE = 'project tests'\n")
        support = self.project / "support"
        support.mkdir()
        (support / "__init__.py").write_text("VALUE = 'project support'\n")
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\n"
            "from tests.helper import VALUE as TESTS_VALUE\n"
            "from support import VALUE as SUPPORT_VALUE\n"
            "class Case(unittest.TestCase):\n"
            "    def test_imports(self):\n"
            "        self.assertEqual('project tests', TESTS_VALUE)\n"
            "        self.assertEqual('project support', SUPPORT_VALUE)\n"
        )
        self.assertEqual(0, self.run_hook())
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])

    def test_a_module_only_tao_has_is_not_importable_by_project_tests(self):
        """A project lacking `agent_gate_reuse` must fail, not import Tao's copy."""
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\n"
            "class Case(unittest.TestCase):\n"
            "    def test_imports(self):\n"
            "        with self.assertRaises(ImportError):\n"
            "            import agent_gate_reuse\n"
            "        with self.assertRaises(ImportError):\n"
            "            import stable_launcher\n"
        )
        self.assertEqual(0, self.run_hook())
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])

    def test_project_venv_python_is_selected(self):
        python = self.project / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.assertEqual(str(python), verify._command(self.args)[0])
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.assertIn(str(python), self.entries()[-1]["fields"]["check"])

    def test_zero_exit_without_receipt_fails_closed(self):
        with patch.object(verify, "_command", return_value=[sys.executable, "-c", "pass"]):
            self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=0; tests=0", self.entries()[-1]["fields"]["result"])

    def test_success_receipt_with_nonzero_exit_fails_closed(self):
        script = (
            "import json,sys; "
            "open(sys.argv[1], 'w').write(json.dumps({'tests_run': 1, 'successful': True})); "
            "sys.exit(1)"
        )
        with patch.object(verify, "_command", return_value=[sys.executable, "-c", script]):
            self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=1; tests=1", self.entries()[-1]["fields"]["result"])

    def test_forged_terminal_test_count_does_not_pass(self):
        (self.project / "tests" / "test_case.py").write_text(
            "import atexit\n"
            "atexit.register(lambda: print('Ran 1 test in 0.001s'))\n",
            encoding="utf-8",
        )
        self.assertEqual(1, self.run_hook())
        self.assertIn("tests=0", self.entries()[-1]["fields"]["result"])

    def test_passing_test_that_changes_source_does_not_pass_gate(self):
        self.write_test("Path('changed.py').write_text('changed')")
        self.assertEqual(1, self.run_hook())
        self.assertIn("inputs_unchanged=False", self.entries()[-1]["fields"]["result"])

    def test_timeout_and_interruption_clear_old_success(self):
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.write_test("time.sleep(2)")
        self.args.verify_timeout = 1
        self.assertEqual(1, self.run_hook())
        self.assertIn("exit=124", self.entries()[-1]["fields"]["result"])
        with patch.object(verify, "_execute", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_hook()
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertEqual("incomplete", self.entries()[-1]["fields"]["result"])

    def test_foreign_closed_run_or_missing_gate_never_executes(self):
        with patch.object(verify, "_execute") as execute:
            self.bound.return_value = None
            self.assertEqual(1, self.run_hook())
            self.bound.return_value = self.project / "other.json"
            self.assertEqual(1, self.run_hook())
            self.bound.return_value = self.path
            self.preflight["route"]["gates"] = []
            self.path.write_text(json.dumps(self.preflight))
            self.assertEqual(1, self.run_hook())
            execute.assert_not_called()

    def test_directory_escape_or_invalid_pattern_never_executes(self):
        with patch.object(verify, "_execute") as execute:
            self.args.test_directory = ".."
            self.assertEqual(1, self.run_hook())
            self.args.test_directory = "tests"
            self.args.test_pattern = "../test_case.py"
            self.assertEqual(1, self.run_hook())
            execute.assert_not_called()

    def test_ledger_ownership_rejection_prevents_execution(self):
        with patch.object(verify, "record_hook_gate", side_effect=PermissionError("not owner")):
            with patch.object(verify, "_execute") as execute:
                self.assertEqual(1, self.run_hook())
                execute.assert_not_called()

    def test_generated_launcher_dispatches_verify(self):
        from support.stable_launcher import ensure_stable_launcher, stable_launcher_path
        with patch("support.stable_launcher.Path.home", return_value=self.project):
            ensure_stable_launcher(ROOT, dry_run=False)
            launcher = stable_launcher_path()
        result = subprocess.run([str(launcher), "verify", "--help"],
                                env={**os.environ, "TAO_HOME": str(ROOT)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--test-pattern", result.stdout)

    def test_cli_dispatch_reaches_runner(self):
        spec = importlib.util.spec_from_file_location("verify_cli", ROOT / "scripts/agent-hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        args = hook.build_parser().parse_args(["verify", "--project", str(self.project),
                                              "--test-pattern", "test_case.py"])
        with patch.object(verify, "verification_hook", return_value=0) as runner:
            with patch.object(hook, "checkpoint_after_hook", side_effect=lambda args, code, *a: code):
                self.assertEqual(0, hook._checkpointed_hook(args))
            runner.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
