"""The judge itself has to be provable, since it is what proves everything else.

Three verdicts matter and each has a way of being wrong. A mutant a test catches
must read KILLED even when the module cannot import -- that is the case counting
`FAIL:` lines got backwards. A mutant nothing catches must read SURVIVED, or the
tool reports coverage it does not have. A mutant whose `old` text is absent must
read NOT APPLIED rather than SURVIVED, which would be a false negative dressed
as a finding.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location(
    "mutation_check", SCRIPTS / "mutation-check.py"
)
mutation_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutation_check)


SUBJECT = "VALUE = 1\n"


class ApplyMutantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = self.root / "subject.py"
        self.target.write_text(SUBJECT, encoding="utf-8")

    def test_one_match_is_replaced_and_the_original_returned(self) -> None:
        original = mutation_check.apply_mutant(self.target, "VALUE = 1", "VALUE = 2")

        self.assertEqual(SUBJECT, original)
        self.assertEqual("VALUE = 2\n", self.target.read_text(encoding="utf-8"))

    def test_no_match_changes_nothing(self) -> None:
        self.assertIsNone(mutation_check.apply_mutant(self.target, "absent", "x"))
        self.assertEqual(SUBJECT, self.target.read_text(encoding="utf-8"))

    def test_two_matches_change_nothing(self) -> None:
        # Two matches would test two things at once and report one verdict.
        self.target.write_text("a = 1\nb = 1\n", encoding="utf-8")

        self.assertIsNone(mutation_check.apply_mutant(self.target, "= 1", "= 2"))
        self.assertEqual("a = 1\nb = 1\n", self.target.read_text(encoding="utf-8"))


class JudgeTests(unittest.TestCase):
    """Each verdict is driven by a real subprocess, not by a stubbed exit code."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "subject.py").write_text(SUBJECT, encoding="utf-8")

    def _check(self, script: str) -> list[str]:
        (self.root / "check.py").write_text(script, encoding="utf-8")
        return [sys.executable, "check.py"]

    def _mutant(self, old: str, new: str) -> dict[str, str]:
        return {"label": "m", "file": "subject.py", "old": old, "new": new}

    def test_a_mutant_the_check_catches_is_killed(self) -> None:
        check = self._check(
            "import subject, sys; sys.exit(0 if subject.VALUE == 1 else 1)"
        )

        verdict = mutation_check.judge(self._mutant("1", "2"), check, self.root)

        self.assertEqual(mutation_check.KILLED, verdict)

    def test_a_mutant_that_breaks_the_import_is_killed(self) -> None:
        """The case that made counting FAIL lines wrong.

        A module that cannot be imported prints a traceback and no FAIL line, so
        a grep-based judge reported it as a survivor. The exit code is non-zero
        either way.
        """

        check = self._check("import subject, sys; sys.exit(0)")

        verdict = mutation_check.judge(
            self._mutant("VALUE = 1", "def ("), check, self.root
        )

        self.assertEqual(mutation_check.KILLED, verdict)

    def test_a_mutant_nothing_checks_survives(self) -> None:
        check = self._check("import sys; sys.exit(0)")

        verdict = mutation_check.judge(self._mutant("1", "2"), check, self.root)

        self.assertEqual(mutation_check.SURVIVED, verdict)

    def test_an_absent_mutant_is_not_a_survivor(self) -> None:
        # Reporting SURVIVED here would be a false negative dressed as a
        # finding: the mutant never existed to be caught.
        check = self._check("import sys; sys.exit(0)")

        verdict = mutation_check.judge(
            self._mutant("never-present", "x"), check, self.root
        )

        self.assertEqual(mutation_check.UNAPPLIED, verdict)

    def test_the_target_is_restored_after_every_verdict(self) -> None:
        check = self._check("import sys; sys.exit(0)")

        for old, new in (("1", "2"), ("VALUE = 1", "def ("), ("absent", "x")):
            with self.subTest(old=old):
                mutation_check.judge(self._mutant(old, new), check, self.root)
                self.assertEqual(
                    SUBJECT, (self.root / "subject.py").read_text(encoding="utf-8")
                )

    def test_the_target_is_restored_when_the_run_raises(self) -> None:
        """A mutant left in the tree is a defect this tool introduced."""

        def explode(command: list[str], cwd: Path) -> int:
            raise OSError("no such executable")

        original_run = mutation_check.run_check
        mutation_check.run_check = explode
        try:
            with self.assertRaises(OSError):
                mutation_check.judge(self._mutant("1", "2"), ["x"], self.root)
        finally:
            mutation_check.run_check = original_run

        self.assertEqual(
            SUBJECT, (self.root / "subject.py").read_text(encoding="utf-8")
        )


class LoadSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "spec.json"

    def _write(self, payload: object) -> Path:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def test_a_well_formed_spec_loads(self) -> None:
        spec = [{"label": "a", "file": "x.py", "old": "1", "new": "2"}]

        self.assertEqual(spec, mutation_check.load_spec(self._write(spec)))

    def test_a_missing_field_is_refused(self) -> None:
        for payload in (
            {"label": "a", "file": "x.py", "old": "1"},
            {"label": "", "file": "x.py", "old": "1", "new": "2"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    mutation_check.load_spec(self._write([payload]))

    def test_a_non_list_is_refused(self) -> None:
        """A dict is caught by the next guard; a number is caught by no other.

        Asserted with a dict alone at first, and the tool's own self-check found
        it: removing the list guard still raised, because iterating a dict
        yields strings and the per-mutant guard rejects those. A number is where
        the two differ -- without the list guard it raises TypeError, which is
        not the refusal this promises.
        """

        for payload in ({"label": "a"}, 5, "not-a-list"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    mutation_check.load_spec(self._write(payload))


class ExitCodeTests(unittest.TestCase):
    """The command's own exit code, so a caller can gate on it."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "subject.py").write_text(SUBJECT, encoding="utf-8")
        self.spec = self.root / "spec.json"

    def _run(self, mutants: list[dict[str, str]], script: str) -> int:
        (self.root / "check.py").write_text(script, encoding="utf-8")
        self.spec.write_text(json.dumps(mutants), encoding="utf-8")
        original = mutation_check.check_command
        mutation_check.check_command = lambda _test: [sys.executable, "check.py"]
        try:
            return mutation_check.main(
                ["--spec", str(self.spec), "--test", "ignored", "--root", str(self.root)]
            )
        finally:
            mutation_check.check_command = original

    def test_all_killed_exits_zero(self) -> None:
        code = self._run(
            [{"label": "a", "file": "subject.py", "old": "1", "new": "2"}],
            "import subject, sys; sys.exit(0 if subject.VALUE == 1 else 1)",
        )

        self.assertEqual(0, code)

    def test_a_survivor_exits_non_zero(self) -> None:
        code = self._run(
            [{"label": "a", "file": "subject.py", "old": "1", "new": "2"}],
            "import sys; sys.exit(0)",
        )

        self.assertEqual(1, code)

    def test_an_unapplied_mutant_exits_non_zero(self) -> None:
        # Silence here would read as "no survivors" for a spec that ran nothing.
        code = self._run(
            [{"label": "a", "file": "subject.py", "old": "absent", "new": "x"}],
            "import sys; sys.exit(0)",
        )

        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
