"""A worktree is free to work in; a few commands still leave it.

The worktree waiver treats a linked worktree as proof of isolation, and for
files it is: they belong to that checkout alone. Git's refs, remotes, tags,
config, object store and reflog do not -- every worktree shares one Git
directory, so `git push --force` from inside one reaches what it would reach
from the protected checkout.

The first attempt at this excluded Git entirely from the waiver, which denied
`git commit` inside the agent's own worktree: the whole point of having one.
So the boundary is drawn around commands whose actual effect is losing work or
escaping the worktree through an output/execution option, and the verdict there
is `ask`, not `deny` -- each of them is sometimes exactly what was meant, and
Claude's prompt carries "don't ask again" for the operator who means it
routinely.

Both halves are load-bearing. A hazard list that grows to cover ordinary Git
rebuilds the machine that only takes Enter; one that misses a member hands
`branch -D main` a silent allow.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claude_pretool_gate as gate  # noqa: E402


def hazard(command: str) -> str:
    return gate.shared_repository_hazard(command.split())


ORDINARY = [
    # The working half: everything an agent does on its own branch.
    "git add -A",
    "git commit -m 'x'",
    "git checkout -b topic",
    "git switch -c topic",
    "git switch main",
    "git merge topic",
    "git rebase main",
    "git cherry-pick abc123",
    "git revert abc123",
    "git stash",
    "git stash pop",
    "git push origin topic",
    "git fetch origin",
    "git pull",
    "git submodule update --init",
    "git worktree add ../x",
    # Git refuses to remove a worktree holding modified or untracked files, so
    # the plain removal cannot lose work. Asking about it put a prompt on the
    # step that closes every task, on top of a check git was already making.
    "git worktree remove ../other",
    "git worktree prune",
    "git tag v1",
    "git remote add upstream git@example.com:x.git",
    "git config user.email a@b.c",
    "git config --get core.hooksPath",
    "git config --global --get user.email",
    "git config --system --list",
    "git reset --soft HEAD~1",
    "git reset HEAD~1",
    "git restore --staged file.py",
    "git clean -n",
    "git branch -d merged-topic",
    "git branch --list",
    "git gc",
    "git reflog",
]

HAZARDS = [
    "git branch -D main",
    "git branch -vD main",
    "git branch -vvD main",
    "git branch -f main HEAD",
    "git branch -M main",
    "git branch --delete --force main",
    "git push --force origin main",
    "git push -f",
    "git push -nf origin main",
    "git push --force-with-lease origin main",
    "git push --delete origin topic",
    "git push --mirror",
    "git push origin +main",
    "git reset --hard origin/main",
    "git clean -fdx",
    "git restore file.py",
    "git restore --staged --worktree file.py",
    "git checkout -- file.py",
    "git checkout -B main origin/main",
    "git checkout -f main",
    "git switch -C main origin/main",
    "git switch --discard-changes main",
    "git tag -d v1.0.0",
    "git tag --delete v1.0.0",
    "git tag -f v1.0.0 HEAD",
    "git update-ref -d refs/heads/x",
    "git update-ref refs/heads/main deadbeef",
    "git filter-branch --all",
    "git filter-repo --path x",
    "git reflog expire --all",
    "git reflog delete HEAD@{0}",
    "git gc --prune=now",
    "git prune",
    "git replace -d deadbeef",
    "git remote remove origin",
    "git remote rm origin",
    "git remote set-url origin git@evil.example:x.git",
    "git stash clear",
    "git stash drop",
    "git worktree remove --force ../other",
    "git apply --unsafe-paths change.patch",
    "git submodule foreach rm -rf build",
    "git submodule deinit --all",
    "git submodule set-url lib git@evil.example:lib.git",
    "git config --global user.email a@b.c",
    "git config --system core.editor vi",
    "git config --local core.hooksPath /tmp/hooks",
    "git config core.hooksPath /tmp/hooks",
    "git config --file /tmp/config user.email a@b.c",
    "git show --output=/tmp/leak HEAD",
    "git diff --output=/tmp/leak HEAD~1",
    "git log --output=/tmp/leak -1",
    "git show --ext-diff HEAD",
    "git --exec-path=/tmp status",
    "git -c alias.inspect=!evil inspect",
    "git --config-env=alias.inspect=EVIL inspect",
]


class OrdinaryGitStaysSilentTests(unittest.TestCase):
    def test_the_everyday_commands_are_not_hazards(self) -> None:
        for command in ORDINARY:
            with self.subTest(command=command):
                self.assertEqual("", hazard(command))

    def test_a_command_that_is_not_git_is_never_a_hazard(self) -> None:
        for command in ("python3 build.py", "npm test", "rm -rf build", "gitk"):
            with self.subTest(command=command):
                self.assertEqual("", hazard(command))

    def test_an_empty_command_line_is_not_a_hazard(self) -> None:
        # Edit and Write reach the same check with no command line at all.
        self.assertEqual("", gate.shared_repository_hazard([]))

    def test_git_by_an_absolute_path_is_still_git(self) -> None:
        self.assertNotEqual("", hazard("/usr/bin/git branch -D main"))
        self.assertEqual("", hazard("/usr/bin/git commit -m x"))


class HazardsAreNamedTests(unittest.TestCase):
    def test_each_hazard_is_recognised_and_explained(self) -> None:
        for command in HAZARDS:
            with self.subTest(command=command):
                reason = hazard(command)
                self.assertNotEqual("", reason, command)
                self.assertNotIn("\n", reason)

    def test_globals_before_the_subcommand_do_not_hide_it(self) -> None:
        """Being wrong by one token about a global option moves the verb.

        Each of these was a real miss: `--exec-path` was treated as taking a
        value, so `branch` was skipped and `-D main` read as the subcommand;
        `--namespace` does take one and was absent, so its argument `n` read as
        the subcommand. Both returned "no hazard" for a branch deletion.
        """

        for command in (
            "git -C /tmp/repo branch -D main",
            "git -c core.pager=cat push --force",
            "git --git-dir=/x branch -D main",
            "git --git-dir /x branch -D main",
            "git --work-tree /x reset --hard",
            "git --exec-path branch -D main",
            "git --namespace n branch -D main",
            "git --super-prefix p branch -D main",
            "git --config-env=k=E push -f",
        ):
            with self.subTest(command=command):
                self.assertNotEqual("", hazard(command), command)

        for command in (
            "git -C /tmp/repo commit -m x",
            "git --no-pager log",
            "git -p status",
            "git --literal-pathspecs add .",
            "git --exec-path",
        ):
            with self.subTest(command=command):
                self.assertEqual("", hazard(command), command)

    def test_an_unreadable_option_costs_a_question_rather_than_a_pass(self) -> None:
        """The parser fails closed, because failing open has a direction.

        An option outside the known vocabulary makes the subcommand's position
        a guess, and the guess that reads one token too far turns
        `branch -D main` into an unremarkable word. So "cannot tell" is treated
        as the dangerous case -- it costs one prompt, never a silent pass.
        """

        self.assertIsNone(gate.git_subcommand(["git", "--unknown-global", "log"])[0])
        self.assertNotEqual("", hazard("git --unknown-global branch -D main"))
        self.assertNotEqual("", hazard("git --unknown-global log"))

    def test_the_subcommand_is_found_past_global_options(self) -> None:
        verb, arguments = gate.git_subcommand(["git", "-C", "/tmp", "branch", "-D", "x"])
        self.assertEqual("branch", verb)
        self.assertEqual(["-D", "x"], arguments)

    def test_git_with_no_subcommand_is_not_the_unreadable_case(self) -> None:
        # `""` means "nothing to run"; `None` means "cannot tell". Collapsing
        # them would make a bare `git` prompt and an unknown option pass.
        self.assertEqual(("", []), gate.git_subcommand(["git"]))
        self.assertEqual(("", []), gate.git_subcommand(["git", "-C"]))
        self.assertEqual("", hazard("git"))


class TheVerdictIsAskNotDenyTests(unittest.TestCase):
    """A hazard is a decision, so it reaches the operator as one.

    `deny` is for violations with a deterministic remedy the agent applies
    itself. Force-pushing has no remedy -- it is either wanted or not -- and
    only `ask` renders a prompt the operator can answer once and for all.
    """

    def test_ask_emits_the_prompting_decision(self) -> None:
        import contextlib
        import io
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            gate.ask("because")
        emitted = json.loads(buffer.getvalue())["hookSpecificOutput"]
        self.assertEqual("ask", emitted["permissionDecision"])
        self.assertIn("because", emitted["permissionDecisionReason"])

    def test_deny_and_ask_are_different_decisions(self) -> None:
        import contextlib
        import io
        import json

        decisions = []
        for emit in (gate.deny, gate.ask, gate._approve):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                emit("reason")
            decisions.append(
                json.loads(buffer.getvalue())["hookSpecificOutput"]["permissionDecision"]
            )
        self.assertEqual(["deny", "ask", "allow"], decisions)


if __name__ == "__main__":
    unittest.main()
