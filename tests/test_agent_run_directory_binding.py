"""A run directory that cannot hold a packet is refused while it can change.

Split from ``tests/test_agent_hook_continuation.py``: that module had grown
past the review-pressure limit across four changes, and its subjects are
separable. This one is the binding rule -- which evidence paths can carry a
continuation packet at all.
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
from agent_run_registry import claim_run

RUN_ID = "0123456789abcdef0123456789abcdef"


def _load_hook_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "agent-hook.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_hook_script("agent_hook_for_test_agent_run_directory_binding")


class UnbindableRunDirectoryTests(unittest.TestCase):
    """A run directory that cannot hold a packet is refused while it can change.

    45 of 48 local run directories had readable names, so every one of those
    runs recorded no checkpoint and none could be resumed. The lifecycle said
    so on each hook, after the choice could no longer be undone, in a sentence
    that named the wrong cause: the evidence *was* a `.tao/runs/<name>/`
    preflight path -- the name simply was not opaque.
    """

    def _args(self, project: Path, evidence: Path | None) -> Namespace:
        return Namespace(project=project, evidence=evidence)

    def test_a_readable_run_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "persist-timings-20260822" / "preflight.json"

            message = wiring.unbindable_run_directory_error(self._args(project, evidence))

        self.assertIn("32-character hex run id", message)

    def test_the_refusal_names_the_way_out(self) -> None:
        """A refusal an agent cannot act on is the silent skip with extra words."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "readable" / "preflight.json"

            message = wiring.unbindable_run_directory_error(self._args(project, evidence))

        self.assertIn("Omit --evidence", message)
        self.assertIn("resume", message)

    def test_an_opaque_run_directory_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            self.assertEqual(
                "", wiring.unbindable_run_directory_error(self._args(project, evidence))
            )

    def test_evidence_outside_the_runs_root_is_left_alone(self) -> None:
        """The default path and worker paths have no packet by design."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for evidence in (
                project / ".tao" / "preflight.json",
                project / ".tao" / "workers" / "abcd1234" / "preflight.json",
                project / ".tao" / "runs" / RUN_ID / "nested" / "preflight.json",
            ):
                with self.subTest(evidence=evidence.name):
                    self.assertEqual(
                        "",
                        wiring.unbindable_run_directory_error(
                            self._args(project, evidence)
                        ),
                    )

    def test_no_evidence_is_not_a_bad_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                "",
                wiring.unbindable_run_directory_error(
                    self._args(Path(directory), None)
                ),
            )

    def test_start_refuses_and_later_hooks_do_not(self) -> None:
        """An already-started run under a bad name must still review and finish.

        Refusing start is what stops the loss; refusing the rest would strand
        every run that began before this check existed.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "readable" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("{}", encoding="utf-8")

            start = agent_hook._lifecycle_evidence_error(
                Namespace(project=project, evidence=evidence, hook="start")
            )
            review = agent_hook._lifecycle_evidence_error(
                Namespace(project=project, evidence=evidence, hook="review")
            )

        self.assertIn("32-character hex run id", start)
        self.assertEqual("", review)

    def test_the_skip_says_what_was_lost(self) -> None:
        self.assertIn("resume this run", wiring.SKIPPED_DETAIL)


class StartNamesItsOwnRunTests(unittest.TestCase):
    """Start printed neither the run id nor the path later hooks would want.

    Both had to be guessed, and a run directory is named by an opaque id, so
    the guessing was expensive: one session spent eight of thirteen hook calls
    on it. It also never said that naming the path is usually unnecessary --
    a hook with no `--evidence` already resolves the run bound to the session.
    """

    def test_registration_states_the_run_id_the_evidence_and_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            evidence.parent.mkdir(parents=True)
            route = {"command": "bugfix"}
            intake = {"request": "fix the lifecycle overhead", "request_classified": False}
            evidence.write_text(
                json.dumps({"route": route, "request_intake": intake}), encoding="utf-8"
            )
            claim = claim_run(project, evidence, route, intake)
            details: list[str] = []

            registered = agent_hook._register_started_run(
                Namespace(project=project, evidence=evidence, hook="start"),
                details,
                claim["run"],
            )

            self.assertTrue(registered, msg=str(details))
            self.assertIn(f"run id: {RUN_ID}", details)
            self.assertIn(f"evidence: {evidence}", details)
            self.assertTrue(
                any("omit --evidence" not in line and "on their own" in line for line in details),
                msg=str(details),
            )


class SideFileNamedAsEvidenceTests(unittest.TestCase):
    """A run directory holds three JSON files and only one of them is evidence.

    Naming the gate ledger as `--evidence` was accepted: `gate-batch` reported
    SUCCESS and wrote a second ledger beside the first, so the gates landed
    where no finish would read them, and `review` objected several calls later
    about an unbound run id rather than about the file.
    """

    def _args(self, project: Path, evidence: Path) -> Namespace:
        return Namespace(project=project, evidence=evidence, hook="gate-batch")

    def test_the_gate_ledger_is_refused_and_the_preflight_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = project / ".tao" / "runs" / RUN_ID
            run.mkdir(parents=True)
            preflight = run / "preflight.json"
            preflight.write_text(json.dumps({"route": {"command": "bugfix"}}), encoding="utf-8")
            ledger = run / "gate-evidence.json"
            ledger.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "preflight_evidence": str(preflight),
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )

            refusal = agent_hook._lifecycle_evidence_error(self._args(project, ledger))

            self.assertIn("gate ledger", refusal)
            self.assertIn(str(preflight), refusal)
            self.assertIn("omit --evidence", refusal)
            self.assertEqual(
                "", agent_hook._lifecycle_evidence_error(self._args(project, preflight))
            )

    def test_the_continuation_packet_is_refused_too(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = project / ".tao" / "runs" / RUN_ID
            run.mkdir(parents=True)
            packet = run / "continuation.json"
            packet.write_text(
                json.dumps(
                    {
                        "run_id": RUN_ID,
                        "binding": {"filename": "preflight.json"},
                        "work": {"objective": "x"},
                        "drift": {"project": {}},
                    }
                ),
                encoding="utf-8",
            )

            refusal = agent_hook._lifecycle_evidence_error(self._args(project, packet))

            self.assertIn("continuation packet", refusal)
            self.assertIn(str(run / "preflight.json"), refusal)

    def test_evidence_written_before_a_field_existed_is_not_a_side_file(self) -> None:
        """Absence never identifies a side-file; only its own fields do.

        A run that started under older evidence -- an empty object, at the
        limit -- must still be able to reach review and finish.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = project / ".tao" / "runs" / RUN_ID
            run.mkdir(parents=True)
            legacy = run / "preflight.json"
            legacy.write_text("{}", encoding="utf-8")

            self.assertEqual(
                "", agent_hook._lifecycle_evidence_error(self._args(project, legacy))
            )


if __name__ == "__main__":
    unittest.main()
