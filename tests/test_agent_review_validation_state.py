from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_finish_final_checks import (
    record_successful_review_workflow_validation,
    reusable_review_workflow_validation,
    review_validation_path,
)


def initialize_repository(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=project,
        check=True,
    )


class AgentReviewValidationStateTests(unittest.TestCase):

    def test_review_validation_uses_ignored_tao_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            initialize_repository(project)
            (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "ignore state"], cwd=project, check=True)
            evidence_path = project / ".tao" / "runs" / "review" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(json.dumps({"route": {"command": "refactor"}}), encoding="utf-8")

            record_successful_review_workflow_validation(
                project=project,
                rules=project,
                evidence_path=evidence_path,
                validate={"returncode": 0},
                diff_check={"returncode": 0},
                review_scope="pathspec: scripts/agent_finish_final_checks.py",
            )

            validation_path = review_validation_path(project)
            self.assertTrue(validation_path.is_file())
            self.assertEqual(project.resolve() / ".tao", validation_path.parent)
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("", status.stdout)
            self.assertTrue(reusable_review_workflow_validation(project, project)["reused"])


if __name__ == "__main__":
    unittest.main()
