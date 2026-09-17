from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


from agent_required_doc_reuse import required_doc_reuse


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

    def test_another_session_or_changed_hash_cannot_reuse_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory), prior_session="another-session")
            self.assertEqual([], required_doc_reuse(current)["reused"])

        with tempfile.TemporaryDirectory() as directory:
            current = self._fixture(Path(directory), prior_hash="d" * 64)
            self.assertEqual([], required_doc_reuse(current)["reused"])


if __name__ == "__main__":
    unittest.main()
