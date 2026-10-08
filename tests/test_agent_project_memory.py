"""Captured project memory is recalled at once, and corrected by replace, retire and expiry."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_project_memory import (  # noqa: E402
    _capture as capture,
    _digest,
    _main as main,
    _recall as recall,
    _retire as retire,
    recall_lines,
)
import agent_project_memory  # noqa: E402


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        state_home = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(self.project / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.review_on = (date.today() + timedelta(days=30)).isoformat()

    def candidate(self, body: str = "Use the checked contract before changing the adapter.",
                  scope: str = "task", **extra: str) -> dict:
        return capture(self.project, body=body, source="design note",
                       scope=scope, review_on=self.review_on, **extra)

    def _path(self, record: dict) -> Path:
        return next((self.project / "state-home/project-memory").glob(f'*/{record["id"]}.json'))

    def test_capture_is_recalled_without_approval(self) -> None:
        record = self.candidate()
        self.assertEqual("active", record["status"])
        self.assertEqual([record["id"]], [item["id"] for item in recall(self.project, "task")])
        self.assertEqual([], recall(self.project, "review"))
        header = recall_lines(self.project, "task")[0]
        self.assertIn("agent-written reference", header)
        self.assertIn("current request, repo rules and source evidence prevail", header)

    def test_expired_and_retired_records_are_not_recalled(self) -> None:
        record = self.candidate()
        self.assertEqual([], recall(self.project, "task", today=date.fromisoformat(self.review_on)))
        retire(self.project, record["id"])
        self.assertEqual([], recall(self.project, "task"))

    def test_replace_retires_the_old_record(self) -> None:
        old = self.candidate("Old advice")
        new = self.candidate("Corrected advice", replaces=old["id"])
        self.assertEqual(old["id"], new["replaces"])
        self.assertEqual([new["id"]], [item["id"] for item in recall(self.project, "task")])
        stored = json.loads(self._path(old).read_text(encoding="utf-8"))
        self.assertEqual(("retired", new["id"]), (stored["status"], stored["replaced_by"]))

    def test_recall_shows_what_a_replacement_superseded(self) -> None:
        old = self.candidate("Use React for the settings page" + " x" * 100)
        new = self.candidate("Use Vue for the settings page", replaces=old["id"])
        plain = self.candidate("Unrelated advice")
        shown = {item["id"]: item for item in
                 (json.loads(line[2:]) for line in recall_lines(self.project, "task")[1:])}
        self.assertTrue(shown[new["id"]]["previously"].startswith("Use React"))
        self.assertLessEqual(len(shown[new["id"]]["previously"]), 160)
        self.assertNotIn("previously", shown[plain["id"]])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--project", str(self.project), "recall", "--scope", "task"])
        cli = {item["id"]: item for item in json.loads(buffer.getvalue())}
        self.assertTrue(cli[new["id"]]["previously"].startswith("Use React"))

    def test_history_lists_the_whole_chain_from_any_member_without_writing(self) -> None:
        first = self.candidate("First advice")
        second = self.candidate("Second advice", replaces=first["id"])
        third = self.candidate("Third advice", replaces=second["id"])
        store = self._path(first).parent
        before = {path.name: path.read_bytes() for path in store.iterdir()}
        for member in (first, second, third):
            with self.subTest(member=member["body"]):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    self.assertEqual(0, main(["--project", str(self.project), "history", member["id"]]))
                chain = json.loads(buffer.getvalue())
                self.assertEqual([third["id"], second["id"], first["id"]], [r["id"] for r in chain])
                self.assertEqual(["active", "retired", "retired"], [r["status"] for r in chain])
        self.assertEqual(before, {path.name: path.read_bytes() for path in store.iterdir()})
        with self.assertRaisesRegex(ValueError, "missing or invalid"):
            agent_project_memory._history(self.project, "0123456789abcdef")

    def test_history_survives_a_broken_or_cyclic_chain(self) -> None:
        first = self.candidate("First advice")
        second = self.candidate("Second advice", replaces=first["id"])
        self._path(first).unlink()
        self.assertEqual([second["id"]],
                         [r["id"] for r in agent_project_memory._history(self.project, second["id"])])
        loop = {"id": "a" * 16, "status": "retired", "body": "a", "source": "s",
                "created_at": "t", "replaces": "b" * 16, "replaced_by": "b" * 16}
        other = {**loop, "id": "b" * 16, "replaces": "a" * 16, "replaced_by": "a" * 16}
        with mock.patch("agent_project_memory._existing"), \
                mock.patch("agent_project_memory.scan_records", return_value=([loop, other], 0)):
            self.assertEqual(2, len(agent_project_memory._history(self.project, "a" * 16)))

    def test_replacement_hides_the_old_record_even_before_its_retire_lands(self) -> None:
        old = self.candidate("Old advice")
        with mock.patch("agent_project_memory._retire"):
            new = self.candidate("Corrected advice", replaces=old["id"])
        self.assertEqual([new["id"]], [item["id"] for item in recall(self.project, "task")])

    def test_replacing_an_unknown_record_writes_nothing(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing or invalid"):
            self.candidate(replaces="0123456789abcdef")
        self.assertEqual([], recall(self.project, "task"))

    def test_records_from_the_former_review_step_stay_recallable(self) -> None:
        record = self.candidate()
        path = self._path(record)
        for status in ("pending", "approved"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["status"] = status
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(status=status):
                self.assertEqual([record["id"]], [item["id"] for item in recall(self.project, "task")])

    def test_approve_is_a_no_op_alias(self) -> None:
        record = self.candidate()
        before = self._path(record).read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["--project", str(self.project), "approve", record["id"],
                                      "--digest", record["digest"]]))
        self.assertEqual(before, self._path(record).read_bytes())

    def test_consolidate_is_read_only(self) -> None:
        old = self.candidate("Old advice")
        with mock.patch("agent_project_memory._retire"):
            self.candidate("Old advice", replaces=old["id"])
        store = self._path(old).parent
        (store / "0123456789abcdef.json").write_text("{broken", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in store.iterdir()}
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["--project", str(self.project), "consolidate"]))
        self.assertEqual(before, {path.name: path.read_bytes() for path in store.iterdir()})
        report = json.loads(output.getvalue())
        self.assertEqual([old["id"]], [item["id"] for item in report["unfinished_replacements"]])
        self.assertEqual(1, len(report["duplicate_groups"]))
        self.assertEqual(1, report["unreadable"])

    def test_consolidate_refuses_a_negative_window(self) -> None:
        with self.assertRaises(SystemExit) as raised, mock.patch("sys.stderr", io.StringIO()):
            main(["--project", str(self.project), "consolidate", "--within-days", "-1"])
        self.assertEqual(2, raised.exception.code)

    def test_changed_content_fails_closed(self) -> None:
        record = self.candidate()
        path = self._path(record)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["body"] = "Changed on disk"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual([], recall(self.project, "task"))
        payload["digest"] = _digest(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(1, len(recall(self.project, "task")))

    def test_recall_is_bounded_and_project_local(self) -> None:
        for number in range(5):
            self.candidate(f"Guidance {number}", scope="all")
        lines = recall_lines(self.project, "task")
        self.assertEqual(4, len(lines))
        self.assertTrue(all("Guidance" in line for line in lines[1:]))
        self.assertEqual([], recall(self.project / "another-project", "task"))

    def test_route_records_come_first_and_an_oversized_record_is_skipped(self) -> None:
        def record(body: str, scope: str, days: int) -> dict:
            review_on = (date.today() + timedelta(days=days)).isoformat()
            return capture(self.project, body=body, source="note", scope=scope, review_on=review_on)

        general = record("G" * 450, "all", 10)
        task = record("T" * 450, "task", 40)
        oversized = record("O" * 450, "all", 11)
        short = record("Short guidance.", "all", 12)
        lines = recall_lines(self.project, "task")[1:]
        self.assertEqual([task["id"], general["id"], short["id"]],
                         [json.loads(line[2:])["id"] for line in lines])
        self.assertNotIn(oversized["id"], "".join(lines))

    def test_relevant_general_memory_precedes_unrelated_route_memory(self) -> None:
        for number in range(4):
            self.candidate(f"Billing policy {number}")
        useful = self.candidate("Check retry_queue before changing its dispatcher.", scope="all")
        records = recall(self.project, "task", request="Fix retry_queue dispatcher")
        self.assertEqual(useful["id"], records[0]["id"])
        lines = recall_lines(self.project, "task", request="Fix retry_queue dispatcher")
        self.assertEqual(useful["id"], json.loads(lines[1][2:])["id"])
        self.assertEqual(4, len(lines))

    def test_each_query_input_affects_ranking(self) -> None:
        self.candidate("Unrelated guidance", scope="task")
        useful = self.candidate("Check src/dispatch/retry_queue.py before editing.", scope="all")
        for context in ({"request": "RETRY_QUEUE"},
                        {"target_summary": "dispatch"},
                        {"target_paths": ("src/dispatch/retry_queue.py",)},
                        {"target_paths": (str(self.project / "src/dispatch/retry_queue.py"),)}):
            with self.subTest(context=context):
                self.assertEqual(useful["id"], recall(self.project, "task", **context)[0]["id"])

    def test_exact_path_and_module_matches_outweigh_generic_words(self) -> None:
        generic = self.candidate("Fix dispatcher worker errors failed slow", scope="task")
        useful = self.candidate("Check src/dispatch/retry_queue.py.", scope="all")
        for request in ("Fix dispatcher worker errors failed slow src/dispatch/retry_queue.py",
                        "Fix dispatcher worker errors failed slow retry_queue"):
            with self.subTest(request=request):
                self.assertEqual([useful["id"], generic["id"]],
                                 [r["id"] for r in recall(self.project, "task", request=request)])

    def test_a_shared_path_prefix_does_not_outrank_the_matching_record(self) -> None:
        # Every Android source path starts with the same seven directories; that
        # prefix used to score 55 against 20 for the record about the work.
        base = "app/src/main/java/com/example/shop"
        for name in ("data/dto/FeedData.kt", "data/api/FeedApi.kt"):
            self.candidate(f"Keep {base}/{name} fields nullable", scope="task")
        useful = self.candidate("Profile screen crash comes from a null nickname; guard ProfileScreen",
                                scope="all")
        request = f"Fix crash in profile screen {base}/ui/profile/ProfileScreen.kt"
        self.assertEqual(useful["id"], recall(self.project, "task", request=request)[0]["id"])
        self.assertEqual(useful["id"], recall(
            self.project, "task", target_paths=(f"{base}/ui/profile/ProfileScreen.kt",))[0]["id"])

    def test_shared_nearest_directories_do_not_outrank_the_matching_record(self) -> None:
        # Files directly under `src/main/kotlin` share both nearest directories;
        # giving those the module weight scored 18 against 12 for the right one.
        self.candidate("Keep src/main/kotlin/FeedData.kt fields nullable", scope="task")
        useful = self.candidate("Profile screen crash comes from a null nickname; guard ProfileScreen",
                                scope="all")
        request = "Fix crash in profile screen src/main/kotlin/ProfileScreen.kt"
        self.assertEqual(useful["id"], recall(self.project, "task", request=request)[0]["id"])

    def test_korean_particles_still_match_the_stem(self) -> None:
        self.candidate("피드 목록 페이지 캐시 유지", scope="task")
        useful = self.candidate("프로필 화면에서 닉네임 null 크래시", scope="all")
        for request in ("프로필은 왜 죽나", "프로필을 고쳐줘", "화면 크래시"):
            with self.subTest(request=request):
                self.assertEqual(useful["id"], recall(self.project, "task", request=request)[0]["id"])
        # The stem keeps two syllables, so a two-syllable word is never cut to one.
        self.assertIn("아이", agent_project_memory._terms("아이")[0])
        self.assertNotIn("아", agent_project_memory._terms("아이")[0])

    def test_one_recall_hashes_each_source_file_once(self) -> None:
        files = tuple(f"src/f{number}.py" for number in range(4))
        for path in files:
            self.tracked_source(path)
        for number in range(5):
            self.candidate("long " * 95 + str(number), scope="all", source_paths=files)
        self.candidate("short", scope="all", source_paths=files)
        with mock.patch("agent_project_memory._source_blob",
                        wraps=agent_project_memory._source_blob) as hashed:
            lines = recall_lines(self.project, "task")
        self.assertEqual(len(files), hashed.call_count)
        self.assertGreaterEqual(len(lines), 2)
        with mock.patch("agent_project_memory._source_blob",
                        wraps=agent_project_memory._source_blob) as hashed, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["--project", str(self.project), "recall", "--scope", "task"]))
        self.assertEqual(len(files), hashed.call_count)

    def test_relevance_never_revives_ineligible_memories(self) -> None:
        foreign = self.candidate("retry_queue", scope="review")
        retired = self.candidate("retry_queue")
        retire(self.project, retired["id"])
        old = self.candidate("retry_queue")
        replacement = self.candidate("Use the current contract", replaces=old["id"])
        expired = capture(self.project, body="retry_queue", source="note", scope="all",
                          review_on=(date.today() + timedelta(days=1)).isoformat())
        result = recall(self.project, "task", today=date.today() + timedelta(days=1), request="retry_queue")
        self.assertEqual([replacement["id"]], [r["id"] for r in result])
        self.assertTrue({foreign["id"], retired["id"], old["id"], expired["id"]}.isdisjoint(
            {r["id"] for r in result}))

    def test_no_overlap_and_ties_keep_legacy_order(self) -> None:
        general = self.candidate("Same advice", scope="all")
        task = self.candidate("Same advice", scope="task")
        before = [task["id"], general["id"]]
        for request in ("", "unrelated", "same advice", "same " * 10):
            self.assertEqual(before, [r["id"] for r in recall(self.project, "task", request=request)])

    def tracked_source(self, path: str = "src/queue.py") -> Path:
        subprocess.run(["git", "init", "-q", "--object-format=sha1", str(self.project)], check=True)
        file = self.project / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "--", path], check=True)
        return file

    def test_source_blob_tracks_uncommitted_changes_and_is_read_only(self) -> None:
        source = self.tracked_source()
        source.write_text("capture dirty bytes\n", encoding="utf-8")
        record = self.candidate(source_paths=("src/queue.py",))
        expected = subprocess.run(["git", "-C", str(self.project), "hash-object", "--no-filters",
                                   "src/queue.py"], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual([{"path": "src/queue.py", "blob": expected}], record["source_files"])
        store_before = self._path(record).read_bytes()
        index_before = (self.project / ".git/index").read_bytes()
        self.assertEqual("unchanged", json.loads(recall_lines(self.project, "task")[1][2:])["source_status"])
        source.write_text("changed again\n", encoding="utf-8")
        payload = json.loads(recall_lines(self.project, "task")[1][2:])
        self.assertEqual("changed", payload["source_status"])
        self.assertEqual(["src/queue.py"], payload["unverified_sources"])
        self.assertIn("verify before use", payload["warning"])
        self.assertEqual(record["id"], payload["id"])
        self.assertEqual(store_before, self._path(record).read_bytes())
        self.assertEqual(index_before, (self.project / ".git/index").read_bytes())
        source.write_text("capture dirty bytes\n", encoding="utf-8")
        self.assertNotIn("warning", json.loads(recall_lines(self.project, "task")[1][2:]))

    def test_unavailable_sources_are_marked_instead_of_silently_trusted(self) -> None:
        source = self.tracked_source()
        self.candidate(source_paths=("src/queue.py",))
        source.unlink()
        payload = json.loads(recall_lines(self.project, "task")[1][2:])
        self.assertEqual("unavailable", payload["source_status"])
        self.assertIn("verify before use", payload["warning"])
        source.symlink_to(self.project / "state-home")
        self.assertEqual("unavailable", json.loads(recall_lines(self.project, "task")[1][2:])["source_status"])

    def test_git_filters_do_not_hide_worktree_byte_changes(self) -> None:
        source = self.tracked_source()
        (self.project / ".gitattributes").write_text("*.py text\n", encoding="utf-8")
        source.write_bytes(b"line\r\n")
        record = self.candidate(source_paths=("src/queue.py",))
        raw = b"line\r\n"
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.assertEqual(expected, record["source_files"][0]["blob"])
        source.write_bytes(b"line\n")
        self.assertEqual("changed", json.loads(recall_lines(self.project, "task")[1][2:])["source_status"])

    def test_git_failure_is_unavailable_and_legacy_records_keep_their_shape(self) -> None:
        self.tracked_source()
        record = self.candidate(source_paths=("src/queue.py",))
        with mock.patch("agent_project_memory.subprocess.run", side_effect=OSError("Git unavailable")):
            payload = json.loads(recall_lines(self.project, "task", records=[record])[1][2:])
        self.assertEqual("unavailable", payload["source_status"])
        legacy = self.candidate()
        payload = json.loads(recall_lines(self.project, "task", records=[legacy])[1][2:])
        self.assertEqual({"id", "body", "source", "review_on"}, set(payload))

    def test_evidence_paths_participate_in_relevance(self) -> None:
        self.tracked_source()
        self.candidate("Other advice")
        useful = self.candidate("File-specific guidance", scope="all", source_paths=("src/queue.py",))
        self.assertEqual(useful["id"], recall(self.project, "task", target_paths=("src/queue.py",))[0]["id"])

    def test_source_metadata_is_validated_and_digest_protected(self) -> None:
        self.tracked_source()
        record = self.candidate(source_paths=("src/queue.py",))
        path = self._path(record)
        original = json.loads(path.read_text(encoding="utf-8"))
        for files in ([{"path": "src/queue.py", "blob": "0" * 40}], [],
                      [{"path": "../queue.py", "blob": "0" * 40}],
                      [{"path": "src/queue.py", "blob": "invalid"}], "invalid"):
            payload = {**original, "source_files": files}
            if files != [{"path": "src/queue.py", "blob": "0" * 40}]:
                payload["digest"] = _digest(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(files=files):
                self.assertEqual([], recall(self.project, "task"))

    def test_capture_rejects_unsafe_or_untracked_sources_without_store_writes(self) -> None:
        self.tracked_source()
        (self.project / "untracked.py").write_text("private\n", encoding="utf-8")
        (self.project / "link.py").symlink_to(self.project / "src/queue.py")
        (self.project / "link-dir").symlink_to(self.project / "src", target_is_directory=True)
        for paths in (("../outside.py",), (str(self.project / "src/queue.py"),),
                      ("untracked.py",), ("missing.py",), ("link.py",),
                      ("link-dir/queue.py",), (".git/config",), ("src/queue.py",) * 5):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.candidate(source_paths=paths)
        self.assertEqual([], recall(self.project, "task"))

    def test_multiple_sources_and_payload_budget_include_warnings(self) -> None:
        first = self.tracked_source()
        second = self.tracked_source("src/worker.py")
        record = self.candidate(source_paths=("src/queue.py", "src/worker.py", "src/queue.py"))
        self.assertEqual(2, len(record["source_files"]))
        first.write_text("new\n", encoding="utf-8")
        second.unlink()
        for number in range(5):
            self.candidate("Other advice " + str(number), scope="all")
        lines = recall_lines(self.project, "task", target_paths=("src/queue.py",))[1:]
        self.assertLessEqual(len(lines), 3)
        self.assertLessEqual(sum(len(line[2:]) for line in lines), 1200)
        payload = json.loads(lines[0][2:])
        self.assertEqual("changed", payload["source_status"])
        self.assertEqual(["src/queue.py", "src/worker.py"], payload["unverified_sources"])

    def test_cli_capture_and_recall_pass_context_and_source_options(self) -> None:
        self.tracked_source()
        self.candidate("Unrelated advice")
        output = io.StringIO()
        with redirect_stdout(output), mock.patch("sys.stdin", io.StringIO("Queue guidance")):
            self.assertEqual(0, main(["--project", str(self.project), "capture", "--source", "note",
                                      "--scope", "all", "--review-on", self.review_on,
                                      "--source-path", "src/queue.py"]))
        captured = json.loads(output.getvalue())
        for args in (["--request", "queue"], ["--target-summary", "queue"],
                     ["--target-path", "src/queue.py"]):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--project", str(self.project), "recall", "--scope", "task", *args]))
            self.assertEqual(captured["id"], json.loads(output.getvalue())[0]["id"])
            self.assertEqual("unchanged", json.loads(output.getvalue())[0]["source_status"])

    def test_symlink_store_is_refused(self) -> None:
        outside = self.project / "outside"
        outside.mkdir()
        state = self.project / "state-home"
        state.mkdir()
        (state / "project-memory").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.candidate()

    def test_linked_worktrees_recall_the_same_record(self) -> None:
        repo = self.project / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
        sibling = self.project / "sibling"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "sibling",
                        str(sibling)], check=True)
        record = capture(repo, body="Shared across worktrees", source="note",
                         scope="task", review_on=self.review_on, source_paths=("README.md",))
        self.assertEqual([record["id"]], [item["id"] for item in recall(sibling, "task")])
        self.assertEqual("unchanged", json.loads(recall_lines(sibling, "task")[1][2:])["source_status"])
        (sibling / "README.md").write_text("other worktree bytes\n", encoding="utf-8")
        self.assertEqual("changed", json.loads(recall_lines(sibling, "task")[1][2:])["source_status"])
        self.assertEqual("unchanged", json.loads(recall_lines(repo, "task")[1][2:])["source_status"])


if __name__ == "__main__":
    unittest.main()
