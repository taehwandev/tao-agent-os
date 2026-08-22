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


if __name__ == "__main__":
    unittest.main()
