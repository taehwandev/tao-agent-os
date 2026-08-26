from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_run_registry import register_run, registered_run, transition_run
import agent_transfer_cancel as transfer_cancel
from agent_transfer_cancel import (
    CANCEL_RECEIPT_NAME,
    cancel_transferred_run,
    cancellation_receipt_failure,
)


class CancellationReceiptValidationTests(unittest.TestCase):
    def valid_receipt(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": "cancelled",
            "reason": "transferred_to_completed_linked_worktree",
            "source_run_id": "0123456789abcdef0123456789abcdef",
            "replacement_run_id": "fedcba9876543210fedcba9876543210",
            "request_fingerprint": "1" * 64,
            "created_at": "2026-08-26T00:00:00+00:00",
            "verified_worktree_signature": "2" * 64,
        }

    def test_complete_production_receipt_is_valid(self) -> None:
        receipt = self.valid_receipt()

        self.assertIsNone(
            cancellation_receipt_failure(
                receipt,
                source_run_id=str(receipt["source_run_id"]),
                request_fingerprint=str(receipt["request_fingerprint"]),
            )
        )

    def test_missing_or_malformed_signature_fails_closed(self) -> None:
        for signature in (None, "", "not-a-sha-256", "f" * 63, "g" * 64):
            with self.subTest(signature=signature):
                receipt = self.valid_receipt()
                if signature is None:
                    receipt.pop("verified_worktree_signature")
                else:
                    receipt["verified_worktree_signature"] = signature

                failure = cancellation_receipt_failure(receipt)

                self.assertIsNotNone(failure)
                self.assertIn("verified_worktree_signature", str(failure))

    def test_drift_boundary_rejects_a_missing_signature_without_reading_git(
        self,
    ) -> None:
        receipt = self.valid_receipt()
        receipt.pop("verified_worktree_signature")

        with patch.object(transfer_cancel, "worktree_signature") as signature_read:
            failure = transfer_cancel.cancellation_worktree_drift(Path("project"), receipt)

        signature_read.assert_not_called()
        self.assertIn("verified_worktree_signature", str(failure))

    def test_missing_naive_or_unparseable_created_at_fails_closed(self) -> None:
        for created_at in (None, "", "not-a-time", "2026-08-26T00:00:00"):
            with self.subTest(created_at=created_at):
                receipt = self.valid_receipt()
                if created_at is None:
                    receipt.pop("created_at")
                else:
                    receipt["created_at"] = created_at

                failure = cancellation_receipt_failure(receipt)

                self.assertIsNotNone(failure)
                self.assertIn("created_at", str(failure))

    def test_malformed_request_fingerprint_fails_closed(self) -> None:
        for fingerprint in (None, "", "not-a-sha-256", "f" * 63, "g" * 64):
            with self.subTest(fingerprint=fingerprint):
                receipt = self.valid_receipt()
                if fingerprint is None:
                    receipt.pop("request_fingerprint")
                else:
                    receipt["request_fingerprint"] = fingerprint

                failure = cancellation_receipt_failure(receipt)

                self.assertIsNotNone(failure)
                self.assertIn("request_fingerprint", str(failure))


class TransferredRunCancellationTests(unittest.TestCase):
    def test_completed_same_request_linked_worktree_cancels_clean_source(self) -> None:
        with self.fixture() as fixture:
            code, output = fixture.cancel()

            self.assertEqual(0, code, output)

            source = registered_run(
                fixture.source,
                fixture.source_evidence,
                run_id=fixture.source_run_id,
            )
            replacement = registered_run(
                fixture.replacement,
                fixture.replacement_evidence,
                run_id=fixture.replacement_run_id,
            )
            receipt = json.loads(
                (fixture.source_evidence.parent / CANCEL_RECEIPT_NAME).read_text(
                    encoding="utf-8"
                )
            )

        self.assertIn("SUCCESS cancel", output)
        self.assertEqual("cancelled", source["state"])
        self.assertEqual("completed", replacement["state"])
        self.assertEqual(
            {
                "created_at",
                "reason",
                "replacement_run_id",
                "request_fingerprint",
                "schema_version",
                "source_run_id",
                "status",
                # The checkout state the decision rested on, so a reader can
                # check the pairing instead of trusting the cancellation.
                "verified_worktree_signature",
            },
            set(receipt),
        )

    def test_dirty_source_fails_without_settling_either_run(self) -> None:
        with self.fixture() as fixture:
            (fixture.source / "untracked.txt").write_text("owned work\n", encoding="utf-8")
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)
            replacement = registered_run(
                fixture.replacement, fixture.replacement_evidence
            )

        self.assertEqual(1, code)
        self.assertIn("source checkout has tracked or untracked changes", output)
        self.assertEqual("running", source["state"])
        self.assertEqual("completed", replacement["state"])

    def test_incomplete_replacement_fails_without_cancelling_source(self) -> None:
        with self.fixture(complete_replacement=False) as fixture:
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("replacement run has not completed successfully", output)
        self.assertEqual("running", source["state"])

    def test_different_request_fails_without_cancelling_source(self) -> None:
        with self.fixture(replacement_request="different request") as fixture:
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("source and replacement requests do not match", output)
        self.assertEqual("running", source["state"])

    def test_unrelated_repository_fails_without_cancelling_source(self) -> None:
        with self.fixture() as fixture:
            unrelated = fixture.root / "unrelated"
            unrelated.mkdir()
            fixture.git("init", str(unrelated), cwd=fixture.root)
            (unrelated / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            fixture.git("config", "user.email", "test@example.com", cwd=unrelated)
            fixture.git("config", "user.name", "Test User", cwd=unrelated)
            fixture.git("add", ".gitignore", cwd=unrelated)
            fixture.git("commit", "-m", "base", cwd=unrelated)
            fixture.replacement_project_in_preflight(unrelated)

            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("replacement project must be a linked Git worktree", output)
        self.assertIn("source and replacement must share one Git common directory", output)
        self.assertEqual("running", source["state"])

    def test_a_refused_transition_writes_no_receipt(self) -> None:
        with self.fixture() as fixture:
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            with patch("agent_transfer_cancel.cancel_run", return_value=None):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("before the cancellation transition", output)
        self.assertFalse(receipt_path.exists())
        self.assertEqual("running", source["state"])

    def test_the_registry_carries_the_cancellation_without_the_receipt_file(
        self,
    ) -> None:
        """A lost receipt must not lose the outcome.

        The file used to be the only record, so a crash after the state write
        left a cancelled run with nothing saying why and no way to retry. The
        registry now stores the same record in the transaction that settles the
        run, which makes the file a rebuildable copy.
        """

        with self.fixture() as fixture:
            code, output = fixture.cancel()
            self.assertEqual(0, code, output)
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_path.unlink()

            source = registered_run(
                fixture.source,
                fixture.source_evidence,
                run_id=fixture.source_run_id,
            )

        self.assertEqual("cancelled", source["state"])
        self.assertEqual(receipt, source["cancellation"])

    def test_a_file_appearing_after_validation_stops_the_cancellation(self) -> None:
        """The clean-checkout test is only true at the moment it runs.

        Validation and the settling transition were separated by the receipt
        write and the registry call, so a file created in between left the run
        cancelled while the checkout it vouched for was dirty. The re-read
        happens in the same call that settles the run.
        """

        with self.fixture() as fixture:
            # Dirty the checkout from inside the registry transaction, after the
            # run has been selected and immediately before the state write. Any
            # check made outside that lock, however close to it, still leaves
            # this window open.
            real_cancel_run = transfer_cancel.cancel_run

            def dirty_inside_the_lock(*args, precondition=None, **kwargs):
                def dirty_then_check() -> str | None:
                    (fixture.source / "appeared.txt").write_text("x\n", encoding="utf-8")
                    return precondition() if precondition is not None else None

                return real_cancel_run(
                    *args, precondition=dirty_then_check, **kwargs
                )

            with patch(
                "agent_transfer_cancel.cancel_run", side_effect=dirty_inside_the_lock
            ):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME

        self.assertEqual(1, code)
        self.assertIn("stopped being clean before the cancellation transition", output)
        self.assertEqual("running", source["state"])
        self.assertFalse(receipt_path.exists())

    def test_the_settlement_records_the_checkout_state_it_verified(self) -> None:
        """One write, and the observation it rested on stored beside it.

        Writing `cancelled` and reverting it after a second look closed the
        ordinary race and opened a worse one: an interruption between the two
        writes, or a failed revert, left `cancelled` paired with a checkout
        that was never clean and nothing recording the contradiction. A single
        write cannot tear, and the recorded signature is what lets a reader
        check the pairing rather than trust it.
        """

        with self.fixture() as fixture:
            code, output = fixture.cancel()
            self.assertEqual(0, code, output)
            source = registered_run(
                fixture.source,
                fixture.source_evidence,
                run_id=fixture.source_run_id,
            )
            receipt = json.loads(
                (fixture.source_evidence.parent / CANCEL_RECEIPT_NAME).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual("cancelled", source["state"])
        clean = hashlib.sha256(b"").hexdigest()
        self.assertEqual(clean, receipt["verified_worktree_signature"])
        self.assertEqual(clean, source["cancellation"]["verified_worktree_signature"])

    def test_a_dirty_checkout_inside_the_lock_settles_nothing(self) -> None:
        """The precondition runs in the transaction, so a refusal writes nothing."""

        with self.fixture() as fixture:
            real_cancel_run = transfer_cancel.cancel_run

            def dirty_inside_the_lock(*args, precondition=None, **kwargs):
                def dirty_then_check() -> str | None:
                    (fixture.source / "appeared.txt").write_text("x\n", encoding="utf-8")
                    return precondition() if precondition is not None else None

                return real_cancel_run(*args, precondition=dirty_then_check, **kwargs)

            with patch(
                "agent_transfer_cancel.cancel_run", side_effect=dirty_inside_the_lock
            ):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME

        self.assertEqual(1, code)
        self.assertEqual("running", source["state"])
        self.assertNotIn("cancellation", source)
        self.assertFalse(receipt_path.exists())

    def test_a_file_appearing_before_the_settlement_leaves_the_run_running(
        self,
    ) -> None:
        """The gap between the reading and the write is not closable, so the
        write that lands in it must not be the terminal one.

        Injecting a file just before the registry write used to produce a
        cancelled run vouching for a dirty checkout. The settlement now rests
        on a second reading, and a refusal there restores the run.
        """

        with self.fixture() as fixture:
            readings: list[int] = []
            real_cancel_run = transfer_cancel.cancel_run

            def dirty_before_the_settlement(*args, precondition=None, **kwargs):
                def read_then_maybe_dirty() -> str | None:
                    readings.append(1)
                    if len(readings) > 1:
                        (fixture.source / "appeared.txt").write_text(
                            "x\n", encoding="utf-8"
                        )
                    return precondition() if precondition is not None else None

                return real_cancel_run(
                    *args, precondition=read_then_maybe_dirty, **kwargs
                )

            with patch(
                "agent_transfer_cancel.cancel_run",
                side_effect=dirty_before_the_settlement,
            ):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME

        self.assertEqual(1, code)
        self.assertEqual(2, len(readings))
        self.assertEqual("running", source["state"])
        self.assertNotIn("cancellation", source)
        self.assertFalse(receipt_path.exists())

    def test_an_interrupted_cancellation_is_never_left_terminal(self) -> None:
        """A crash mid-cancellation must not record a settlement that never
        happened.

        The staged state says the run needs reconciling, which is true whatever
        follows; `cancelled` would have been a claim about a checkout nobody
        re-read.
        """

        class Interrupted(Exception):
            pass

        with self.fixture() as fixture:
            readings: list[int] = []
            real_cancel_run = transfer_cancel.cancel_run

            def interrupt_after_staging(*args, precondition=None, **kwargs):
                def read_then_interrupt() -> str | None:
                    readings.append(1)
                    if len(readings) > 1:
                        raise Interrupted
                    return precondition() if precondition is not None else None

                return real_cancel_run(
                    *args, precondition=read_then_interrupt, **kwargs
                )

            with patch(
                "agent_transfer_cancel.cancel_run",
                side_effect=interrupt_after_staging,
            ):
                with self.assertRaises(Interrupted):
                    fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual("reconcile_required", source["state"])
        self.assertNotIn(source["state"], {"cancelled", "completed"})
        self.assertTrue(source["cancellation"]["pending"])

    def test_a_rerun_reports_a_checkout_that_drifted_from_the_record(self) -> None:
        """The recorded signature exists to be read, and now something reads it.

        A cancellation vouches for the checkout it saw, and the residual race
        it cannot rule out is exactly a checkout that changed straight after.
        Writing the signature without ever comparing it was a claim of
        detectability with no detector.
        """

        with self.fixture() as fixture:
            code, output = fixture.cancel()
            self.assertEqual(0, code, output)

            (fixture.source / "drifted.txt").write_text("x\n", encoding="utf-8")
            code, output = fixture.cancel()

        self.assertEqual(1, code)
        self.assertIn("no longer matches the state the cancellation verified", output)

    def test_a_receipt_write_failure_reports_a_result_rather_than_raising(self) -> None:
        """The cancellation succeeded; only its copy did not."""

        with self.fixture() as fixture:
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            with patch(
                "agent_transfer_cancel.atomic_write_json",
                side_effect=OSError("disk full"),
            ):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("registry holds its record", output)
        self.assertIn("rerun the cancellation to restore the receipt", output)
        self.assertEqual("cancelled", source["state"])
        self.assertFalse(receipt_path.exists())

    def test_a_receipt_write_failure_is_recovered_by_rerunning(self) -> None:
        """A settled run with no receipt must not be a dead end.

        The file used to be written after the state and stored nowhere else, so
        a failure there left a cancelled run, no explanation, and a rerun that
        validation refused because the run was already terminal.
        """

        with self.fixture() as fixture:
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            with patch(
                "agent_transfer_cancel.atomic_write_json",
                side_effect=OSError("disk full"),
            ):
                fixture.cancel()

            self.assertFalse(receipt_path.exists())
            source = registered_run(fixture.source, fixture.source_evidence)
            self.assertEqual("cancelled", source["state"])

            code, output = fixture.cancel()
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code, output)
        self.assertIn("receipt restored from the registry record", output)
        self.assertEqual(source["cancellation"], receipt)

    def test_the_receipt_is_written_only_after_the_run_is_settled(self) -> None:
        """A receipt written first survives an interruption the registry never saw."""

        with self.fixture() as fixture:
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            observed: list[bool] = []
            real_cancel_run = transfer_cancel.cancel_run

            def record_then_cancel(*args, **kwargs):
                observed.append(receipt_path.exists())
                return real_cancel_run(*args, **kwargs)

            with patch(
                "agent_transfer_cancel.cancel_run", side_effect=record_then_cancel
            ):
                code, output = fixture.cancel()

            self.assertEqual(0, code, output)
            self.assertEqual([False], observed)
            self.assertTrue(receipt_path.exists())

    @staticmethod
    def fixture(
        *,
        complete_replacement: bool = True,
        replacement_request: str = "same request",
    ) -> "TransferFixture":
        return TransferFixture(complete_replacement, replacement_request)


class TransferFixture:
    def __init__(self, complete_replacement: bool, replacement_request: str):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "source"
        self.replacement = self.root / "replacement"
        self.rules = self.root / "rules"
        self.source.mkdir()
        self.rules.mkdir()
        self.git("init", str(self.source), cwd=self.root)
        self.git("config", "user.email", "test@example.com", cwd=self.source)
        self.git("config", "user.name", "Test User", cwd=self.source)
        (self.source / "tracked.txt").write_text("base\n", encoding="utf-8")
        (self.source / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        self.git("add", "tracked.txt", ".gitignore", cwd=self.source)
        self.git("commit", "-m", "base", cwd=self.source)
        self.git(
            "worktree",
            "add",
            "-b",
            "transfer-test",
            str(self.replacement),
            "HEAD",
            cwd=self.source,
        )

        session = {"runtime": "codex", "session_id": "runtime-session-01"}
        route = {"command": "bugfix", "gates": []}
        source_intake = {"request": "same request", "request_classified": False}
        replacement_intake = {
            "request": replacement_request,
            "request_classified": False,
        }
        self.source_evidence = self.evidence(self.source)
        self.replacement_evidence = self.evidence(self.replacement)
        source_run = register_run(
            self.source, self.source_evidence, route, source_intake
        )
        replacement_run = register_run(
            self.replacement,
            self.replacement_evidence,
            route,
            replacement_intake,
        )
        self.source_run_id = str(source_run["run_id"])
        self.replacement_run_id = str(replacement_run["run_id"])
        self.write_preflight(
            self.source_evidence,
            self.source,
            source_intake,
            session,
            self.source_run_id,
        )
        self.write_preflight(
            self.replacement_evidence,
            self.replacement,
            replacement_intake,
            session,
            self.replacement_run_id,
        )
        if complete_replacement:
            transition_run(
                self.replacement,
                self.replacement_evidence,
                "completed",
                run_id=self.replacement_run_id,
            )

    def __enter__(self) -> "TransferFixture":
        return self

    def __exit__(self, *_args: object) -> None:
        self._temporary.cleanup()

    def cancel(self) -> tuple[int, str]:
        args = Namespace(
            project=self.source,
            rules=self.rules,
            evidence=self.source_evidence,
            replacement_evidence=self.replacement_evidence,
            output=None,
            repair_cycle=0,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            code = cancel_transferred_run(args)
        return code, output.getvalue()

    @staticmethod
    def evidence(project: Path) -> Path:
        path = project / ".tao" / "runs" / ("a" * 32) / "preflight.json"
        path.parent.mkdir(parents=True)
        return path

    def write_preflight(
        self,
        path: Path,
        project: Path,
        intake: dict,
        session: dict,
        run_id: str,
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "agent_run_id": run_id,
                    "project": str(project),
                    "rules": str(self.rules),
                    "request_intake": intake,
                    "runtime_session": session,
                    "route": {"command": "bugfix", "gates": []},
                }
            ),
            encoding="utf-8",
        )

    def replacement_project_in_preflight(self, project: Path) -> None:
        payload = json.loads(self.replacement_evidence.read_text(encoding="utf-8"))
        payload["project"] = str(project)
        self.replacement_evidence.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def git(*arguments: str, cwd: Path) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
