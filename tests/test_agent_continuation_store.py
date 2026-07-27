from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_continuation_packet import ContinuationPacketError, canonical_packet_bytes
from agent_continuation_store import (
    boundary_failures,
    continuation_path,
    list_continuation_run_ids,
    read_continuation_packet,
    write_continuation_packet,
)
from test_agent_continuation_packet import packet, work

RUN_ID = "0123456789abcdef" * 2


def rules(failures: list[dict[str, str]]) -> set[str]:
    return {item["rule"] for item in failures}


def git_project(directory: str, *, ignore_state: bool) -> Path:
    project = Path(directory)
    if ignore_state:
        (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    return project


class RoundTripTests(unittest.TestCase):
    def test_written_packet_reads_back_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            payload = packet(run_id=RUN_ID)

            path = write_continuation_packet(project, payload)

            self.assertEqual(continuation_path(project, RUN_ID), path)
            self.assertEqual(canonical_packet_bytes(payload), path.read_bytes())
            self.assertEqual(payload, read_continuation_packet(project, path)["packet"])

    def test_the_packet_and_its_directory_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = write_continuation_packet(project, packet(run_id=RUN_ID))

            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))

    def test_a_rewrite_replaces_the_snapshot_and_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            write_continuation_packet(project, packet(run_id=RUN_ID))
            second = packet(run_id=RUN_ID, generation=1, work=work(objective="the second snapshot"))

            path = write_continuation_packet(project, second)

            self.assertEqual(second, read_continuation_packet(project, path)["packet"])
            self.assertEqual([path.name], sorted(item.name for item in path.parent.iterdir()))

    def test_run_ids_are_listed_without_reading_any_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            write_continuation_packet(project, packet(run_id=RUN_ID))
            (project / ".tao" / "runs" / "not-a-run-id").mkdir(parents=True)

            self.assertEqual([RUN_ID], list_continuation_run_ids(project))


class RejectedWriteTests(unittest.TestCase):
    def test_an_invalid_packet_leaves_the_previous_generation_intact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = packet(run_id=RUN_ID)
            path = write_continuation_packet(project, first)

            with self.assertRaises(ContinuationPacketError) as raised:
                write_continuation_packet(project, packet(run_id=RUN_ID, work=work(objective="x" * 281)))

            self.assertIn("prose_too_long", rules(raised.exception.failures))
            self.assertEqual(canonical_packet_bytes(first), path.read_bytes())

    def test_failed_atomic_replace_leaves_the_previous_generation_intact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = packet(run_id=RUN_ID)
            path = write_continuation_packet(project, first)
            second = packet(run_id=RUN_ID, generation=1, work=work(objective="second"))

            with mock.patch("agent_continuation_store.os.replace", side_effect=OSError("stop")):
                with self.assertRaises(OSError):
                    write_continuation_packet(project, second)

            self.assertEqual(canonical_packet_bytes(first), path.read_bytes())
            self.assertEqual([path.name], sorted(item.name for item in path.parent.iterdir()))


class ContainmentTests(unittest.TestCase):
    """The only accepted location is the canonical run directory under .tao."""

    def test_a_packet_outside_the_state_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            outside = project / "runs" / RUN_ID / "continuation.json"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(canonical_packet_bytes(packet(run_id=RUN_ID)))

            result = read_continuation_packet(project, outside)

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("path_not_canonical", rules(result["failures"]))
            self.assertIsNone(result["packet"])

    def test_a_sibling_state_directory_of_another_project_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            other = Path(directory) / "other"
            (other / ".tao" / "runs" / RUN_ID).mkdir(parents=True)
            project.mkdir()
            foreign = other / ".tao" / "runs" / RUN_ID / "continuation.json"
            foreign.write_bytes(canonical_packet_bytes(packet(run_id=RUN_ID)))

            result = read_continuation_packet(project, foreign)

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("path_not_canonical", rules(result["failures"]))

    def test_a_symlinked_run_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            elsewhere = project / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "continuation.json").write_bytes(
                canonical_packet_bytes(packet(run_id=RUN_ID))
            )
            runs = project / ".tao" / "runs"
            runs.mkdir(parents=True)
            (runs / RUN_ID).symlink_to(elsewhere)

            result = read_continuation_packet(project, continuation_path(project, RUN_ID))

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("symlinked_path", rules(result["failures"]))

    def test_a_symlinked_run_directory_write_does_not_chmod_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            external = Path(directory) / "external"
            project.mkdir()
            external.mkdir(mode=0o755)
            runs = project / ".tao" / "runs"
            runs.mkdir(parents=True)
            (runs / RUN_ID).symlink_to(external)
            before_mode = stat.S_IMODE(external.stat().st_mode)

            with self.assertRaises(ContinuationPacketError) as raised:
                write_continuation_packet(project, packet(run_id=RUN_ID))

            self.assertIn("symlinked_path", rules(raised.exception.failures))
            self.assertEqual(before_mode, stat.S_IMODE(external.stat().st_mode))
            self.assertFalse((external / "continuation.json").exists())

    def test_a_symlinked_runs_directory_write_creates_nothing_outside(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            external = Path(directory) / "external"
            project.mkdir()
            external.mkdir()
            state = project / ".tao"
            state.mkdir()
            (state / "runs").symlink_to(external)

            with self.assertRaises(ContinuationPacketError) as raised:
                write_continuation_packet(project, packet(run_id=RUN_ID))

            self.assertIn("symlinked_path", rules(raised.exception.failures))
            self.assertFalse((external / RUN_ID).exists())

    def test_listing_refuses_a_symlinked_runs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            external = Path(directory) / "external"
            project.mkdir()
            packet_dir = external / RUN_ID
            packet_dir.mkdir(parents=True)
            (packet_dir / "continuation.json").write_text("{}", encoding="utf-8")
            state = project / ".tao"
            state.mkdir()
            (state / "runs").symlink_to(external)

            self.assertEqual([], list_continuation_run_ids(project))

    def test_an_alternate_filename_in_the_run_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = write_continuation_packet(project, packet(run_id=RUN_ID))
            alternate = path.parent / "continuation.backup.json"
            alternate.write_bytes(path.read_bytes())

            self.assertIn("path_not_canonical", rules(boundary_failures(project, alternate)))


class GitLocalBoundaryTests(unittest.TestCase):
    def test_a_packet_git_would_track_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(directory, ignore_state=False)

            with self.assertRaises(ContinuationPacketError) as raised:
                write_continuation_packet(project, packet(run_id=RUN_ID))

            self.assertIn("not_git_ignored", rules(raised.exception.failures))
            self.assertFalse(continuation_path(project, RUN_ID).exists())

    def test_negative_control_an_ignored_packet_is_accepted(self) -> None:
        """The control: the Git check must reject publication, not all writes.

        Without this the ignored case could be failing for an unrelated reason
        and the refusal above would prove nothing about Git.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = git_project(directory, ignore_state=True)

            path = write_continuation_packet(project, packet(run_id=RUN_ID))

            self.assertEqual("ok", read_continuation_packet(project, path)["status"])


class GuardedReadTests(unittest.TestCase):
    def _written(self, project: Path) -> Path:
        return write_continuation_packet(project, packet(run_id=RUN_ID))

    def test_an_unexpected_link_count_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = self._written(project)
            os.link(path, path.parent / "hard-link.json")

            result = read_continuation_packet(project, path)

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("unexpected_link_count", rules(result["failures"]))

    def test_an_insecure_mode_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = self._written(project)
            os.chmod(path, 0o644)

            result = read_continuation_packet(project, path)

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("insecure_mode", rules(result["failures"]))

    def test_an_oversized_file_is_refused_before_it_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = self._written(project)
            path.write_bytes(b"x" * (24 * 1024 + 1))

            result = read_continuation_packet(project, path)

            self.assertEqual("local_boundary_failed", result["status"])
            self.assertIn("packet_too_large", rules(result["failures"]))

    def test_unparsable_and_unknown_field_packets_are_invalid_not_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = self._written(project)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual("invalid_packet", read_continuation_packet(project, path)["status"])

            payload = packet(run_id=RUN_ID)
            payload["notes"] = "a transcript"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = read_continuation_packet(project, path)
            self.assertEqual("invalid_packet", result["status"])
            self.assertIsNone(result["packet"])

    def test_a_packet_bound_to_another_run_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = self._written(project)
            path.write_text(json.dumps(packet(run_id="f" * 32)), encoding="utf-8")

            result = read_continuation_packet(project, path)

            self.assertEqual("invalid_packet", result["status"])
            self.assertIn("run_binding_mismatch", rules(result["failures"]))

    def test_a_missing_packet_is_reported_as_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = read_continuation_packet(project, continuation_path(project, RUN_ID))
            self.assertEqual("not_found", result["status"])


if __name__ == "__main__":
    unittest.main()
