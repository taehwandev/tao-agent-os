"""What `start` tells an agent about filling the packet it just created.

Split from ``tests/test_agent_hook_continuation.py``. The subject is one
advertisement and whether it can be followed: the command it prints is taken
out of a real start's own output and run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import agent_hook_continuation as wiring

RUN_ID = "0123456789abcdef0123456789abcdef"


def _load_hook_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "agent-hook.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_hook_script("agent_hook_for_test_agent_work_checkpoint_advice")


class WorkCheckpointAdviceTests(unittest.TestCase):
    """A packet that binds correctly can still be useless to resume.

    `resume --last` hands back the packet's whole `work` object, and the
    listing renders its objective. A lifecycle that never records one leaves
    `objective` as the route enum and every other field empty -- which is what
    happened, because the `checkpoint` hook is named only inside the session
    continuation reference that a work route does not require, and no hook
    output mentioned it.
    """

    def _args(self, project: Path, evidence: Path) -> Namespace:
        return Namespace(project=project, evidence=evidence)

    def test_a_run_with_a_packet_is_told_how_to_fill_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            advice = wiring.work_checkpoint_advice(self._args(project, evidence))

        printed = "\n".join(advice)

        self.assertIn("tao-hook checkpoint", printed)
        self.assertIn("--work-stdin", printed)
        self.assertIn("--checkpoint-kind", printed)

    def test_the_advice_names_the_fields_a_resume_is_handed(self) -> None:
        """Naming the hook without naming what it carries is not actionable."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        from agent_continuation_packet import WORK_FIELDS

        missing = [
            field
            for field in WORK_FIELDS
            if not any(
                spelling in advice
                for spelling in (field, field.replace("_", " "), field.replace("_", "-"))
            )
        ]
        self.assertEqual([], missing, advice)


    def test_the_advice_spells_the_object_shapes_from_the_schema(self) -> None:
        """Field names alone did not let a checkpoint be recorded.

        The first attempt failed on object shape: the entries are closed key
        sets with enum values, and the advice named none of them. Reading the
        enums from the validator is what keeps a new role or verification kind
        from silently going unmentioned.
        """

        from agent_continuation_packet import (
            DECISION_STATUSES,
            SCOPE_ROLES,
            VERIFICATION_KINDS,
            VERIFICATION_RESULTS,
        )

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        for group in (
            DECISION_STATUSES, SCOPE_ROLES, VERIFICATION_KINDS, VERIFICATION_RESULTS
        ):
            for value in group:
                with self.subTest(value=value):
                    self.assertIn(value, advice)
        for key in ("id", "status", "text", "path", "role", "checkpoint", "action"):
            with self.subTest(key=key):
                self.assertIn(key, advice)

    def test_the_advice_says_absent_keys_are_the_failure(self) -> None:
        """`optional` in the validator means nullable, not omittable."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        self.assertIn("every key of an object must be present", advice)

    def test_a_real_start_prints_the_advice_itself(self) -> None:
        """A constant no hook emits is a comment, not an advertisement."""

        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            # The initial packet is written only after the execution state is
            # captured, and that needs a HEAD to read.
            for command in (
                ["git", "config", "user.email", "probe@example.invalid"],
                ["git", "config", "user.name", "probe"],
                ["git", "add", "AGENTS.md"],
                ["git", "commit", "-q", "-m", "probe", "--no-verify"],
            ):
                subprocess.run(command, cwd=project, check=True)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            evidence.parent.mkdir(parents=True)

            result = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "probe the packet advice",
                    "--read-only", "--evidence", str(evidence),
                ],
                cwd=project, capture_output=True, text=True,
                env={**os.environ, "TAO_STATE_HOME": state},
            )

        self.assertIn("tao-hook checkpoint", result.stdout, result.stdout)
        self.assertIn("--checkpoint-kind", result.stdout, result.stdout)



    def test_every_array_field_is_shown_with_its_cap(self) -> None:
        """`non_goals: text` is what made the second attempt fail.

        Every field but the objective is an array, and each has a maximum
        entry count. Both are read from the validator, so a printed number is
        the enforced number.
        """

        from agent_continuation_packet import WORK_ITEM_LIMITS

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            advice = "\n".join(
                wiring.work_checkpoint_advice(
                    self._args(project, project / ".tao" / "runs" / RUN_ID / "preflight.json")
                )
            )

        self.assertIn("array", advice)
        for field, limit in WORK_ITEM_LIMITS.items():
            with self.subTest(field=field):
                self.assertIn(f"{field}[{limit}]", advice)
        self.assertNotIn("objective[", advice)

    def test_the_printed_cap_is_the_cap_that_refuses(self) -> None:
        """A number in prose is decoration unless it is the enforced one."""

        from agent_continuation_packet import WORK_ITEM_LIMITS, _work

        limit = WORK_ITEM_LIMITS["non_goals"]
        empty = {
            "objective": "o", "non_goals": [], "decisions": [], "changed_scope": [],
            "inspected_scope": [], "verification": [], "remaining_work": [],
            "blockers": [],
        }

        allowed: list = []
        _work({**empty, "non_goals": ["x"] * limit}, allowed)
        refused: list = []
        _work({**empty, "non_goals": ["x"] * (limit + 1)}, refused)

        self.assertEqual([], allowed)
        self.assertTrue(refused)

    def test_the_advertised_command_records_a_checkpoint_as_printed(self) -> None:
        """Run what the hook prints, exactly as it prints it.

        Checking that the text names the fields proved nothing about whether
        it works: the first attempt at following it failed on a missing
        required flag, the second on `non_goals` being an array rather than a
        line. This test takes the command out of a real start's own output,
        substitutes only the paths, and runs it.
        """

        import os
        import subprocess

        def git(project: Path, *arguments: str) -> None:
            subprocess.run(["git", *arguments], cwd=project, check=True,
                           capture_output=True)

        work = {
            "objective": "prove the printed command runs",
            "non_goals": ["changing the packet schema"],
            "decisions": [
                {"id": "follow_the_advice", "status": "accepted",
                 "text": "the advice is the only instruction used here"}
            ],
            "changed_scope": [{"path": "scripts/agent_hook_continuation.py",
                               "role": "modified"}],
            "inspected_scope": [{"path": "scripts/agent_continuation_packet.py",
                                 "role": "inspected"}],
            "verification": [{"id": "e2e", "kind": "unit", "result": "success",
                              "evidence_sha256": None, "completed_at": None}],
            "remaining_work": [{"checkpoint": "review hook", "action": "review"}],
            "blockers": [],
        }

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            git(project, "init", "-q", ".")
            git(project, "config", "user.email", "probe@example.invalid")
            git(project, "config", "user.name", "probe")
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-q", "-m", "first", "--no-verify")
            environment = {**os.environ, "TAO_STATE_HOME": state}

            started = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "run the printed command",
                    "--read-only", "--runtime-session-id", "printed-command-probe",
                ],
                cwd=project, capture_output=True, text=True, env=environment,
            )
            printed = next(
                line for line in started.stdout.splitlines()
                if "tao-hook checkpoint" in line
            )
            evidence = next((project / ".tao" / "runs").glob("*/preflight.json"))

            # Only the paths are substituted; every flag is the hook's own.
            argv: list[str] = []
            for token in printed.split():
                if token in ("-", "tao-hook"):
                    continue
                if token == "<project>":
                    token = str(project)
                elif token == "<rules>":
                    token = str(ROOT)
                elif token == "<this-run>/preflight.json":
                    token = str(evidence)
                elif token in ("<", "work.json"):
                    continue  # the shell redirect; stdin is piped instead
                argv.append(token)

            recorded = subprocess.run(
                [sys.executable, str(SCRIPTS / "agent-hook.py"), *argv],
                cwd=project, input=json.dumps(work), capture_output=True,
                text=True, env=environment,
            )
            packet = json.loads(
                (evidence.parent / "continuation.json").read_text(encoding="utf-8")
            )

        self.assertIn("checkpoint", argv)
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
        self.assertEqual("prove the printed command runs", packet["work"]["objective"])
        self.assertEqual(["changing the packet schema"], packet["work"]["non_goals"])

    def test_a_run_without_a_packet_is_told_nothing(self) -> None:
        """Advice about a packet that cannot exist is noise on every start."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            self.assertEqual(
                [],
                wiring.work_checkpoint_advice(
                    self._args(project, project / ".tao" / "preflight.json")
                ),
            )


if __name__ == "__main__":
    unittest.main()
