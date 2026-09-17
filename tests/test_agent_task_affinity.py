from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_task_affinity_test", "agent-hook.py")

from agent_task_affinity import task_affinity_denial


def _run(*command: str, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def _ticket_worktree(root: Path) -> Path:
    repository = root / "repository"
    worktree = root / "worktree"
    repository.mkdir()
    _run("git", "init", "-b", "main", cwd=repository)
    _run("git", "config", "user.name", "Test", cwd=repository)
    _run("git", "config", "user.email", "test@example.com", cwd=repository)
    policy = repository / ".agents" / "shared" / "worktree-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "require_linked_worktree": True,
                "protected_branches": ["develop", "main"],
                "require_ticketed_product_branch": True,
                "ticket_key_pattern": "(?:CCE|CCQ)-[0-9]+",
                "product_path_prefixes": ["feature"],
                "product_file_names": ["gradle.properties"],
                "product_suffixes": [".gradle.kts"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (repository / "README.md").write_text("baseline\n", encoding="utf-8")
    _run("git", "add", ".", cwd=repository)
    _run("git", "commit", "-m", "baseline", cwd=repository)
    _run(
        "git",
        "worktree",
        "add",
        str(worktree),
        "-b",
        "taehwan/feat/CCE-4700-goat-motion",
        cwd=repository,
    )
    return worktree


def _start_args(project: Path, request: str, continuation_scope: str = "") -> Namespace:
    return Namespace(
        project=project,
        rules=ROOT,
        command="task",
        request=request,
        continuation_scope=continuation_scope,
        request_classified=True,
        classification_evidence="clear-scoped; blockers resolved",
        platform=[],
        concern=[],
        read_only=False,
        evidence=None,
        worker_reservation_token="",
        output=None,
        repair_cycle=0,
    )


class TaskAffinityTests(unittest.TestCase):
    def test_new_session_cannot_claim_an_unrelated_dirty_ticket_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = _ticket_worktree(Path(directory))
            dirty = worktree / "feature" / "goat-motion.kt"
            dirty.parent.mkdir(parents=True)
            dirty.write_text("working copy\n", encoding="utf-8")

            denial = task_affinity_denial(
                worktree,
                {
                    "request": "오늘의 리스펙트를 모두 보냈어요 Alert를 추가해줘",
                    "continuation_scope": "",
                },
                same_runtime_session=False,
            )

            self.assertIsNotNone(denial)
            self.assertIn("CCE-4700", denial or "")
            self.assertIn("separate ticket worktree", denial or "")

    def test_matching_ticket_context_may_resume_the_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = _ticket_worktree(Path(directory))
            (worktree / "working.txt").write_text("dirty\n", encoding="utf-8")

            denial = task_affinity_denial(
                worktree,
                {
                    "request": "계속 진행해줘",
                    "continuation_scope": "CCE-4700 GOAT 모션 작업을 이어간다",
                },
                same_runtime_session=False,
            )

            self.assertIsNone(denial)

    def test_same_runtime_session_may_continue_its_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = _ticket_worktree(Path(directory))
            (worktree / "working.txt").write_text("dirty\n", encoding="utf-8")

            denial = task_affinity_denial(
                worktree,
                {"request": "계속 진행해줘", "continuation_scope": ""},
                same_runtime_session=True,
            )

            self.assertIsNone(denial)

    def test_start_stops_before_preflight_when_task_affinity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _ticket_worktree(Path(directory))
            (project / "working.txt").write_text("dirty\n", encoding="utf-8")
            captured: dict[str, object] = {}

            def record(_hook, success, details, *_rest, **_kwargs):
                captured["success"] = success
                captured["details"] = details
                return 0 if success else 1

            with (
                patch.object(
                    agent_hook,
                    "run_script_main",
                    side_effect=AssertionError("affinity failure reached preflight"),
                ),
                patch.object(agent_hook, "finish_with_result", side_effect=record),
            ):
                agent_hook.start_hook(
                    _start_args(project, "오늘의 리스펙트 소진 Alert를 추가해줘")
                )

            self.assertFalse(captured["success"])
            self.assertTrue(
                any("task-affinity mismatch" in line for line in captured["details"]),
                msg=captured["details"],
            )


if __name__ == "__main__":
    unittest.main()
