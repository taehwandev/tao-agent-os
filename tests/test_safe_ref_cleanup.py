"""Self-protecting local ref cleanup needs no workflow lifecycle.

`git branch -d`, a plain `git worktree remove`, `git worktree prune`, and the
remote-tracking prunes are refused by git itself whenever they could lose work.
A session with no run in a governed project was nevertheless told to run the
workflow start hook first, while the same command was admitted in the Tao
main checkout. The forcing spellings keep their existing treatment.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_claude_pretool_gate import (  # also puts scripts/ on sys.path
    _decide,
    _opt_in_project,
    _require_linked_worktree,
    _write_preflight,
    gate,
)
from support.global_state import STATE_HOME_ENV
from claude_bash_git import git_command_kind

_STATE_HOME: "tempfile.TemporaryDirectory | None" = None
_OUTER_STATE_HOME: "str | None" = None


def setUpModule() -> None:
    global _STATE_HOME, _OUTER_STATE_HOME
    _OUTER_STATE_HOME = os.environ.get(STATE_HOME_ENV)
    _STATE_HOME = tempfile.TemporaryDirectory()
    os.environ[STATE_HOME_ENV] = _STATE_HOME.name


def tearDownModule() -> None:
    if _OUTER_STATE_HOME is None:
        os.environ.pop(STATE_HOME_ENV, None)
    else:
        os.environ[STATE_HOME_ENV] = _OUTER_STATE_HOME
    if _STATE_HOME is not None:
        _STATE_HOME.cleanup()


ADMITTED = (
    "git branch -d merged-topic",
    "git branch --delete merged-a merged-b",
    "git -C {project} branch -d merged-topic",
    "git worktree prune",
    "git worktree prune -v",
    "git worktree prune --dry-run",
    "git -C {project} worktree prune --verbose",
    "git worktree remove ../old",
    "git -C {project} worktree remove ../old",
)

STILL_GOVERNED = (
    "git branch -D merged-topic",
    "git branch -d --force merged-topic",
    "git branch --delete --force merged-topic",
    "git branch -df merged-topic",
    "git branch -M renamed",
    "git worktree remove --force ../old",
    "git worktree remove -f ../old",
    "git stash drop",
    "git stash clear",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git push origin --delete merged-topic",
    "git branch -d x && touch y",
    "git branch -d x > out.txt",
)


def _scenario(base: Path, name: str, run_session: str = "") -> Path:
    project = _opt_in_project(base)
    if run_session:
        _write_preflight(project, run_session)  # before the fake .git marker
    if name == "plain":
        return project
    _require_linked_worktree(project, linked=name != "protected_main")
    if name == "linked_entry_required":
        policy = project / gate.WORKTREE_POLICY_PATH
        declared = json.loads(policy.read_text(encoding="utf-8"))
        declared["require_workflow_entry"] = True
        policy.write_text(json.dumps(declared), encoding="utf-8")
    return project


def _decision(project: Path, command: str, session: str = "no-run") -> str:
    code, out = _decide(
        {
            "tool_name": "Bash",
            "cwd": str(project),
            "session_id": session,
            "tool_input": {"command": command.format(project=project)},
        }
    )
    assert code == 0
    if not out:
        return "silent"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


SCENARIOS = ("plain", "protected_main", "linked", "linked_entry_required")


class SafeRefCleanupNeedsNoLifecycleTests(unittest.TestCase):
    def test_self_protecting_ref_cleanup_is_admitted_without_a_run(self) -> None:
        for scenario in SCENARIOS:
            for command in ADMITTED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    self.assertNotEqual("deny", _decision(project, command))

    def test_ref_cleanup_is_admitted_beside_a_writable_run(self) -> None:
        for scenario in ("plain", "linked_entry_required"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                project = _scenario(Path(tmp), scenario, "writable-run")
                self.assertNotEqual(
                    "deny",
                    _decision(project, "git branch -d merged-topic", "writable-run"),
                )

    def test_forcing_or_discarding_forms_still_need_their_route(self) -> None:
        for scenario in ("plain", "linked_entry_required"):
            for command in STILL_GOVERNED:
                with self.subTest(scenario=scenario, command=command), \
                        tempfile.TemporaryDirectory() as tmp:
                    project = _scenario(Path(tmp), scenario)
                    # Unchanged: refused without a run, or put to the operator
                    # where a worktree hazard already asks about it.
                    self.assertIn(_decision(project, command), {"deny", "ask"})

    def test_protected_checkout_keeps_approving_merged_branch_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _scenario(Path(tmp), "protected_main")
            self.assertEqual("allow", _decision(project, "git branch -d merged-topic"))


class RemotePruneConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = _opt_in_project(self.base)
        self.upstream = self.base / "upstream.git"
        self.git("init", "--bare", str(self.upstream))
        self.git("init", str(self.project))
        self.git("-C", str(self.project), "config", "user.name", "Fixture")
        self.git("-C", str(self.project), "config", "user.email", "fixture@example.test")
        self.git("-C", str(self.project), "commit", "--allow-empty", "-m", "base")
        self.git("-C", str(self.project), "remote", "add", "origin", str(self.upstream))
        self.git("-C", str(self.project), "push", "origin", "HEAD:refs/heads/main")
        self.git("-C", str(self.project), "tag", "local-only")

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.base, text=True,
                                capture_output=True, check=True)
        return result.stdout

    def config(self, *args: str) -> None:
        self.git("-C", str(self.project), "config", *args)

    def test_ordinary_prune_is_admitted_and_preserves_local_tag(self) -> None:
        self.assertEqual("bootstrap", git_command_kind(["git", "remote", "prune", "origin"], self.project))
        self.assertNotIn(_decision(self.project, "git remote prune origin"), {"deny", "ask"})
        self.git("-C", str(self.project), "remote", "prune", "origin")
        self.assertEqual("local-only\n", self.git("-C", str(self.project), "tag", "--list"))

    def test_fetch_prune_checks_flags_config_and_explicit_refspecs(self) -> None:
        safe = ["git", "fetch", "--prune", "origin"]
        self.assertEqual("bootstrap", git_command_kind(safe, self.project))
        self.assertNotIn(_decision(self.project, shlex.join(safe)), {"deny", "ask"})
        for args in (["--prune", "--prune-tags", "origin"],
                     ["--prune", "origin", "+refs/tags/*:refs/tags/*"],
                     ["--prune", "origin", "+refs/heads/*:refs/heads/*"],
                     ["--force", "--tags", "origin"],
                     ["origin", "+refs/tags/*:refs/tags/*"]):
            with self.subTest(args=args):
                self.assertEqual("mutating", git_command_kind(["git", "fetch", *args], self.project))
                self.assertIn(_decision(self.project, shlex.join(["git", "fetch", *args])), {"deny", "ask"})
        self.config("--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*")
        self.assertEqual("mutating", git_command_kind(safe, self.project))
        self.config("remote.origin.prune", "true")
        self.assertEqual("mutating", git_command_kind(["git", "fetch", "origin"], self.project))
        self.assertIn(_decision(self.project, "git fetch origin"), {"deny", "ask"})
        self.git("-C", str(self.project), "fetch", "origin")
        self.assertEqual("", self.git("-C", str(self.project), "tag", "--list"))

    def test_tag_refspec_is_governed_and_really_deletes_local_tag(self) -> None:
        self.config("--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*")
        self.assertEqual("mutating", git_command_kind(["git", "remote", "prune", "origin"], self.project))
        self.assertIn(_decision(self.project, "git remote prune origin"), {"deny", "ask"})
        self.git("-C", str(self.project), "remote", "prune", "origin")
        self.assertEqual("", self.git("-C", str(self.project), "tag", "--list"))

    def test_fetch_cannot_hide_forced_configured_mapping_behind_a_source(self) -> None:
        base = self.git("-C", str(self.project), "rev-parse", "HEAD").strip()
        self.git("-C", str(self.project), "push", "origin", f"{base}:refs/heads/topic")
        self.git("-C", str(self.project), "commit", "--allow-empty", "-m", "local child")
        child = self.git("-C", str(self.project), "rev-parse", "HEAD").strip()
        cases = (
            ("refs/heads/*:refs/heads/*", ["--force", "origin", "topic"]),
            ("+refs/heads/*:refs/heads/*", ["origin", "topic"]),
            ("refs/heads/*:refs/heads/*", ["--force", "origin", "refs/heads/topic:refs/remotes/origin/topic"]),
            ("+refs/heads/*:refs/heads/*", ["origin", "topic:refs/remotes/origin/topic"]),
        )
        for refmap, args in cases:
            with self.subTest(refmap=refmap, args=args):
                self.config("remote.origin.fetch", refmap)
                self.git("-C", str(self.project), "update-ref", "refs/heads/topic", child)
                tokens = ["git", "fetch", *args]
                # Execute only against disposable repositories to prove Git's
                # configured mapping still writes beyond the explicit operand.
                self.git("-C", str(self.project), "fetch", *args)
                self.assertEqual(base, self.git("-C", str(self.project), "rev-parse", "topic").strip())
                self.assertEqual("mutating", git_command_kind(tokens, self.project))
                self.assertIn(_decision(self.project, shlex.join(tokens)), {"deny", "ask"})

    def test_configured_tag_fetch_cannot_hide_forced_tag_overwrite(self) -> None:
        base = self.git("-C", str(self.project), "rev-parse", "HEAD").strip()
        self.git("-C", str(self.project), "push", "origin", "refs/tags/local-only")
        self.git("-C", str(self.project), "commit", "--allow-empty", "-m", "local child")
        child = self.git("-C", str(self.project), "rev-parse", "HEAD").strip()
        self.config("remote.origin.tagOpt", "--tags")
        for options, overwritten in (([], True), (["--no-tags"], False),
                                     (["--no-tags", "--tags"], True),
                                     (["--tags", "--no-tags"], False)):
            with self.subTest(options=options):
                self.git("-C", str(self.project), "tag", "-f", "local-only", child)
                args = ["fetch", "--force", *options, "origin"]
                self.git("-C", str(self.project), *args)
                self.assertEqual(base if overwritten else child,
                                 self.git("-C", str(self.project), "rev-parse", "local-only").strip())
                self.assertEqual("mutating" if overwritten else "bootstrap",
                                 git_command_kind(["git", *args], self.project))
                decision = _decision(self.project, shlex.join(["git", *args]))
                if overwritten:
                    self.assertIn(decision, {"deny", "ask"})
                else:
                    self.assertNotIn(decision, {"deny", "ask"})

    def test_configured_all_fetch_checks_every_remote(self) -> None:
        self.git("-C", str(self.project), "remote", "add", "other", str(self.upstream))
        self.config("--add", "remote.other.fetch", "+refs/tags/*:refs/tags/*")
        self.config("remote.other.prune", "true")
        self.config("fetch.all", "true")
        self.git("-C", str(self.project), "fetch", "origin")
        self.assertEqual("local-only\n", self.git("-C", str(self.project), "tag", "--list"))
        self.assertEqual("bootstrap", git_command_kind(["git", "fetch", "origin"], self.project))
        self.git("-C", str(self.project), "fetch")
        self.assertEqual("", self.git("-C", str(self.project), "tag", "--list"))
        self.assertEqual("mutating", git_command_kind(["git", "fetch"], self.project))
        self.assertIn(_decision(self.project, "git fetch"), {"deny", "ask"})

    def test_recursive_fetch_requires_child_repository_checks(self) -> None:
        child = self.project / "nested"
        self.git("init", str(child))
        self.git("-C", str(child), "config", "user.name", "Fixture")
        self.git("-C", str(child), "config", "user.email", "fixture@example.test")
        self.git("-C", str(child), "commit", "--allow-empty", "-m", "child")
        sha = self.git("-C", str(child), "rev-parse", "HEAD").strip()
        self.git("-C", str(self.project), "update-index", "--add", "--cacheinfo", f"160000,{sha},nested")
        command = ["git", "fetch", "origin"]
        self.assertEqual("mutating", git_command_kind(command, self.project))
        self.assertIn(_decision(self.project, shlex.join(command)), {"deny", "ask"})
        self.assertEqual("bootstrap", git_command_kind(command + ["--no-recurse-submodules"], self.project))
        self.config("fetch.recurseSubmodules", "false")
        self.assertEqual("bootstrap", git_command_kind(command, self.project))
        self.assertEqual("mutating", git_command_kind(command + ["--recurse-submodules"], self.project))
        self.config("submodule.nested.fetchRecurseSubmodules", "true")
        self.assertEqual("mutating", git_command_kind(command, self.project))
        self.assertEqual("bootstrap", git_command_kind(command + ["--no-recurse-submodules"], self.project))

    def test_selected_repository_config_and_includes_are_used(self) -> None:
        included = self.base / "prune.config"
        included.write_text('[remote "origin"]\nfetch = +refs/tags/*:refs/tags/*\n')
        self.config("include.path", str(included))
        for selectors in (["-C", str(self.project)], ["--git-dir", str(self.project / ".git")],
                          ["-C", str(self.base), "-C", self.project.name]):
            tokens = ["git", *selectors, "remote", "prune", "origin"]
            with self.subTest(selectors=selectors):
                self.assertEqual("mutating", git_command_kind(tokens, self.base))
                self.assertIn(_decision(self.project, shlex.join(tokens)), {"deny", "ask"})

    def test_relative_git_directory_and_compound_cwd_cannot_select_safe_config(self) -> None:
        safe = _opt_in_project(self.base / "safe")
        self.git("init", str(safe))
        self.git("-C", str(safe), "remote", "add", "origin", str(self.upstream))
        self.config("--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*")
        relative = os.path.relpath(self.project, safe)
        for command in (f"git -C {shlex.quote(relative)} remote prune origin",
                        f"git --git-dir={shlex.quote(relative)}/.git remote prune origin",
                        f"cd {shlex.quote(relative)} && git remote prune origin",
                        f"git status && cd {shlex.quote(relative)} && git remote prune origin"):
            with self.subTest(command=command):
                self.assertIn(_decision(safe, command), {"deny", "ask"})

    def test_prune_tags_and_multiple_remotes_are_checked(self) -> None:
        self.git("-C", str(self.project), "remote", "add", "other", str(self.upstream))
        tokens = ["git", "remote", "prune", "origin", "other"]
        self.assertEqual("bootstrap", git_command_kind(tokens, self.project))
        self.config("remote.other.fetch", "+refs/heads/*:refs/heads/*")
        self.assertEqual("mutating", git_command_kind(tokens, self.project))
        self.config("fetch.pruneTags", "true")
        self.assertEqual("mutating", git_command_kind(tokens[:-1], self.project))
        self.config("remote.origin.pruneTags", "false")
        self.assertEqual("bootstrap", git_command_kind(tokens[:-1], self.project))

    def test_dry_run_is_read_only_even_for_tag_deletion(self) -> None:
        self.config("--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*")
        for option in ("--dry-run", "-n"):
            tokens = ["git", "remote", "prune", option, "origin"]
            self.assertEqual("read_only", git_command_kind(tokens, self.project))
            self.assertNotIn(_decision(self.project, shlex.join(tokens)), {"deny", "ask"})

    def test_unavailable_config_does_not_grant_cleanup(self) -> None:
        self.assertEqual("mutating", git_command_kind(["git", "remote", "prune", "origin"], self.base))
        self.config("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        (self.project / ".git" / "config").write_text("[broken\n")
        self.assertEqual("mutating", git_command_kind(["git", "remote", "prune", "origin"], self.project))


if __name__ == "__main__":
    unittest.main()
