from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


from agent_required_doc_reuse import project_route_doc_reuse, record_doc_takeaway, required_doc_reuse
import agent_required_doc_reuse as reuse_module


class RequiredDocReuseTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        prior_session: str = "session-one",
        prior_hash: str = "a" * 64,
        takeaway: str = "prior run applied the operating contract",
    ) -> Path:
        tao = root / ".tao"
        prior_id = "a" * 32
        current_id = "b" * 32
        prior = tao / "runs" / prior_id / "preflight.json"
        current = tao / "runs" / current_id / "preflight.json"
        prior.parent.mkdir(parents=True)
        current.parent.mkdir(parents=True)
        prior_document = {
            "path": "common/skills/agent-operating-skill/SKILL.md",
            "sha256": prior_hash,
            "size_bytes": 120,
        }
        current_document = {
            **prior_document,
            "sha256": "a" * 64,
        }
        prior.write_text(
            json.dumps(
                {
                    "agent_run_id": prior_id,
                    "project": str(root),
                    "rules": str(root),
                    "runtime_session": {"runtime": "codex", "session_id": prior_session},
                    "execution_snapshot": {"required_docs": [prior_document]},
                }
            ),
            encoding="utf-8",
        )
        current.write_text(
            json.dumps(
                {
                    "agent_run_id": current_id,
                    "project": str(root),
                    "rules": str(root),
                    "runtime_session": {"runtime": "codex", "session_id": "session-one"},
                    "route": {
                        "command": "commit",
                        "required_docs": [
                            current_document["path"],
                            "workflows/skills/review-and-commit/SKILL.md",
                        ],
                    },
                    "execution_snapshot": {
                        "required_docs": [
                            current_document,
                            {
                                "path": "workflows/skills/review-and-commit/SKILL.md",
                                "sha256": "c" * 64,
                                "size_bytes": 240,
                            },
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        if takeaway:
            record_doc_takeaway(prior, takeaway)
        (tao / "run-registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "runs": [
                        {
                            "run_id": prior_id,
                            "state": "completed",
                            "evidence_name": "preflight.json",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return current

    def test_unchanged_docs_from_a_completed_same_session_run_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory))

            reuse = required_doc_reuse(current)

            self.assertEqual(
                ["common/skills/agent-operating-skill/SKILL.md"],
                reuse["reused"],
            )
            self.assertEqual(
                ["workflows/skills/review-and-commit/SKILL.md"],
                reuse["unread"],
            )

    def test_recent_complete_match_stops_history_reads_even_in_long_goals(self) -> None:
        for count in (8, 101):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                current = self._fixture(root)
                payload = json.loads(current.read_text())
                payload['route']['required_docs'] = payload['route']['required_docs'][:1]
                current.write_text(json.dumps(payload))
                registry = root / '.tao/run-registry.json'
                records = json.loads(registry.read_text())
                recent = records['runs'][0]
                records['runs'] = [
                    {'run_id': f'{index:032x}', 'state': 'completed'}
                    for index in range(count - 1)
                ] + [recent]
                for record in records['runs'][:-1]:
                    historical = root / '.tao/runs' / record['run_id'] / 'preflight.json'
                    historical.parent.mkdir()
                    historical.write_text(json.dumps({**payload, 'agent_run_id': record['run_id']}))
                registry.write_text(json.dumps(records))
                with patch.object(reuse_module, '_read', wraps=reuse_module._read) as reads:
                    result = required_doc_reuse(current)
                self.assertEqual([], result['unread'])
                self.assertEqual(5, reads.call_count, 'current, registry, latest match, its ledger and review takeaway')

    def test_history_scan_remains_bounded_without_a_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root)
            registry = root / '.tao/run-registry.json'
            registry.write_text(json.dumps({'runs': [
                {'run_id': f'{index:032x}', 'state': 'completed'} for index in range(150)
            ]}))
            with patch.object(reuse_module, '_read', wraps=reuse_module._read) as reads:
                result = required_doc_reuse(current)
            self.assertEqual([], result['reused'])
            self.assertEqual(102, reads.call_count)

    def test_another_session_or_changed_hash_cannot_reuse_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory), prior_session="another-session")
            self.assertEqual([], required_doc_reuse(current)["reused"])

        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory), prior_hash="d" * 64)
            self.assertEqual([], required_doc_reuse(current)["reused"])

    def test_readings_are_reused_independently_of_route_words(self) -> None:
        for command in ("release", "ship", "bugfix"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                current = self._fixture(Path(directory))
                payload = json.loads(current.read_text())
                payload["route"]["command"] = command
                payload["request_intake"] = {"request": "같은 번호로 다시 배포해"}
                current.write_text(json.dumps(payload))
                self.assertTrue(required_doc_reuse(current)["reused"])

    def test_reuse_replays_the_prior_runs_recorded_source_docs_takeaway(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root, takeaway="")
            ledger = root / ".tao/runs" / ("a" * 32) / "gate-evidence.json"
            ledger.write_text(json.dumps({"entries": [
                {"gate": "source docs", "status": "SUCCESS",
                 "fields": {"takeaway": "stage before review;\n  one lifecycle per task"}},
            ]}))

            reuse = required_doc_reuse(current)

            self.assertEqual(["stage before review; one lifecycle per task"], reuse["takeaways"])

    def test_a_run_that_recorded_no_takeaway_proves_no_reading(self) -> None:
        """Listing a document proves it was required, not read; after a
        compaction a takeaway-less reuse notice pointed at a lost reading."""

        for entries in ([], [{"gate": "source docs", "status": "FAIL", "fields": {"takeaway": "x"}}]):
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                current = self._fixture(root, takeaway="")
                ledger = root / ".tao/runs" / ("a" * 32) / "gate-evidence.json"
                ledger.write_text(json.dumps({"entries": entries}))
                reuse = required_doc_reuse(current)
                self.assertEqual([], reuse["reused"])
                self.assertIn("common/skills/agent-operating-skill/SKILL.md", reuse["unread"])
                self.assertNotIn("takeaways", reuse)

    def test_a_run_past_the_takeaway_cap_is_not_credited(self) -> None:
        """Four prior runs each supply a different document; only three
        takeaways are shown, so the fourth document must stay unread."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root, takeaway="")
            docs = [{"path": f"docs/{index}.md", "sha256": f"{index}" * 64, "size_bytes": 10 + index}
                    for index in range(4)]
            payload = json.loads(current.read_text())
            payload["route"]["required_docs"] = [doc["path"] for doc in docs]
            payload["execution_snapshot"]["required_docs"] = docs
            current.write_text(json.dumps(payload))
            runs = []
            for index, doc in enumerate(docs):
                run_id = f"{index + 1:032x}"
                prior = root / ".tao/runs" / run_id / "preflight.json"
                prior.parent.mkdir(parents=True)
                prior.write_text(json.dumps({**payload, "agent_run_id": run_id,
                                             "execution_snapshot": {"required_docs": [doc]}}))
                record_doc_takeaway(prior, f"takeaway {index}")
                runs.append({"run_id": run_id, "state": "completed"})
            (root / ".tao/run-registry.json").write_text(json.dumps({"runs": runs}))

            reuse = required_doc_reuse(current)

            self.assertEqual(3, len(reuse["takeaways"]))
            self.assertEqual(3, len(reuse["reused"]))
            self.assertEqual(1, len(reuse["unread"]))
            shown = {text.split()[-1] for text in reuse["takeaways"]}
            self.assertEqual(shown, {path.split("/")[-1].split(".")[0] for path in reuse["reused"]})

    def test_commit_ready_proof_needs_history_not_a_takeaway(self) -> None:
        """Commit-ready re-attests an already reviewed diff and reads no doc."""

        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory), takeaway="")
            reuse = required_doc_reuse(current, require_takeaway=False)
            self.assertEqual(["common/skills/agent-operating-skill/SKILL.md"], reuse["reused"])
            self.assertNotIn("takeaways", reuse)

    def test_project_docs_from_a_takeaway_less_run_stay_unread(self) -> None:
        document = {"path": ".agents/shared/llm-skills/commit-and-push/SKILL.md",
                    "sha256": "e" * 64, "size_bytes": 900}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root, takeaway="")
            prior = root / ".tao/runs" / ("a" * 32) / "preflight.json"
            for path in (prior, current):
                payload = json.loads(path.read_text())
                payload["project_route_docs"] = [document]
                path.write_text(json.dumps(payload))

            reuse = project_route_doc_reuse(current)

            self.assertEqual([], reuse["reused"])
            self.assertEqual([document["path"]], reuse["unread"])

    def test_project_route_docs_reuse_unchanged_records_only(self) -> None:
        document = {"path": ".agents/shared/llm-skills/commit-and-push/SKILL.md",
                    "sha256": "e" * 64, "size_bytes": 900}
        changed = {"path": ".agents/shared/llm-skills/pr/SKILL.md",
                   "sha256": "f" * 64, "size_bytes": 400}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root)
            prior = root / ".tao/runs" / ("a" * 32) / "preflight.json"
            prior_payload = json.loads(prior.read_text())
            prior_payload["project_route_docs"] = [document, {**changed, "sha256": "0" * 64}]
            prior.write_text(json.dumps(prior_payload))
            payload = json.loads(current.read_text())
            payload["project_route_docs"] = [document, changed]
            current.write_text(json.dumps(payload))

            reuse = project_route_doc_reuse(current)

            self.assertEqual([document["path"]], reuse["reused"])
            self.assertEqual([changed["path"]], reuse["unread"])
            self.assertEqual(["prior run applied the operating contract"], reuse["takeaways"])

    def test_review_takeaway_replays_for_routes_without_source_docs(self) -> None:
        """A commit run has no source-docs gate; its review takeaway is the record."""

        document = {"path": ".agents/shared/llm-skills/commit-and-push/SKILL.md",
                    "sha256": "e" * 64, "size_bytes": 900}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self._fixture(root, takeaway="")
            prior = root / ".tao/runs" / ("a" * 32) / "preflight.json"
            for path in (prior, current):
                payload = json.loads(path.read_text())
                payload["project_route_docs"] = [document]
                path.write_text(json.dumps(payload))
            record_doc_takeaway(prior, "fetch twice;\n  rebase alone, no autostash")

            self.assertEqual(
                ["fetch twice; rebase alone, no autostash"],
                project_route_doc_reuse(current)["takeaways"],
            )
            self.assertEqual(
                ["fetch twice; rebase alone, no autostash"],
                required_doc_reuse(current)["takeaways"],
            )

    def test_review_takeaway_is_bounded_and_blank_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "preflight.json"
            record_doc_takeaway(evidence, "   ")
            self.assertFalse((Path(directory) / reuse_module.DOC_TAKEAWAY_FILE).exists())
            record_doc_takeaway(evidence, "x" * 1000)
            stored = json.loads((Path(directory) / reuse_module.DOC_TAKEAWAY_FILE).read_text())
            self.assertEqual(reuse_module.MAX_TAKEAWAY_CHARS, len(stored["takeaway"]))



class ReuseAcrossRunsTests(unittest.TestCase):
    """Readings carried across worktrees and past the takeaway display cap."""

    DOC_A = "common/skills/agent-operating-skill/SKILL.md"
    DOC_B = "workflows/skills/review-and-commit/SKILL.md"

    def _run(self, root: Path, run_id: str, docs: list[str], takeaway: str = "") -> Path:
        path = root / ".tao" / "runs" / run_id / "preflight.json"
        path.parent.mkdir(parents=True)
        records = [{"path": doc, "sha256": "a" * 64, "size_bytes": 10} for doc in docs]
        path.write_text(json.dumps({
            "agent_run_id": run_id, "project": str(root), "rules": str(root),
            "runtime_session": {"runtime": "claude", "session_id": "s"},
            "route": {"required_docs": docs}, "execution_snapshot": {"required_docs": records},
        }), encoding="utf-8")
        if takeaway:
            record_doc_takeaway(path, takeaway)
        return path

    def _registry(self, root: Path, run_ids: list[str]) -> None:
        (root / ".tao" / "run-registry.json").write_text(json.dumps({"runs": [
            {"run_id": run_id, "state": "completed", "evidence_name": "preflight.json"}
            for run_id in run_ids]}), encoding="utf-8")

    def test_a_reading_in_another_worktree_of_the_repository_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory).resolve() / "repo"
            linked = Path(directory).resolve() / "repo-task"
            admin = main / ".git" / "worktrees" / "task"
            admin.mkdir(parents=True)
            linked.mkdir()
            (admin / "commondir").write_text("../..\n", encoding="utf-8")
            (admin / "gitdir").write_text(f"{linked}/.git\n", encoding="utf-8")
            (linked / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
            self._run(main, "a" * 32, [self.DOC_A], "applied the operating contract")
            self._registry(main, ["a" * 32])
            current = self._run(linked, "b" * 32, [self.DOC_A])
            self._registry(linked, ["b" * 32])

            reuse = required_doc_reuse(current)

            self.assertEqual([self.DOC_A], reuse["reused"])
            self.assertEqual(["applied the operating contract"], reuse["takeaways"])

    def test_runs_repeating_covered_docs_do_not_use_up_the_takeaway_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ids = [f"{index}" * 32 for index in range(1, 5)]
            self._run(root, ids[0], [self.DOC_B], "review rules applied")
            for index, run_id in enumerate(ids[1:]):
                self._run(root, run_id, [self.DOC_A], f"operating contract pass {index}")
            current = self._run(root, "f" * 32, [self.DOC_A, self.DOC_B])
            self._registry(root, ids)

            reuse = required_doc_reuse(current)

            self.assertEqual([self.DOC_A, self.DOC_B], reuse["reused"])
            self.assertEqual(["operating contract pass 2", "review rules applied"], reuse["takeaways"])


if __name__ == "__main__":
    unittest.main()
