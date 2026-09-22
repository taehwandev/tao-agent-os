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


from agent_required_doc_reuse import required_doc_reuse
import agent_required_doc_reuse as reuse_module


class RequiredDocReuseTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        prior_session: str = "session-one",
        prior_hash: str = "a" * 64,
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
                self.assertEqual(3, reads.call_count, 'current, registry, latest match only')

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



if __name__ == "__main__":
    unittest.main()
