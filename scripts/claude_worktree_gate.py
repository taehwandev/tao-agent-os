"""Repo-declared worktree isolation for Claude PreToolUse events."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Command classification is a separate owner; the gate keeps only the policy.
# These re-exports are the module's public surface for the pretool gate.
from claude_bash_readonly import (  # noqa: F401
    bash_command,
    bash_command_kind,
    bash_invocation,
    copy_source_token_indices,
    has_unresolvable_expansion,
    path_arguments,
    raw_path_arguments,
)
from support.stable_launcher import stable_launcher_path  # noqa: F401


BASH_TOOLS = {"Bash"}
WORKTREE_POLICY_PATH = Path(".agents/shared/worktree-policy.json")
WORKTREE_POLICY_SCHEMA_VERSION = 1
REQUIRE_LINKED_WORKTREE_ENV = "TAO_REQUIRE_LINKED_WORKTREE"
MAIN_CHECKOUT_OVERRIDE_ENV = "TAO_ALLOW_MAIN_CHECKOUT_EDIT"


def default_worktree_policy() -> dict:
    return {
        "schema_version": WORKTREE_POLICY_SCHEMA_VERSION,
        "require_linked_worktree": True,
        "protected_branches": ["develop", "main"],
    }


def git_common_dir(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = Path(result.stdout.strip())
    return (root / common).resolve() if not common.is_absolute() else common.resolve()


def same_git_repository(left: Path, right: Path) -> bool:
    try:
        if left.resolve() == right.resolve():
            return True
    except OSError:
        pass
    left_common = git_common_dir(left)
    right_common = git_common_dir(right)
    return left_common is not None and left_common == right_common


def local_worktree_policy_applies(root: Path) -> bool:
    if os.environ.get(REQUIRE_LINKED_WORKTREE_ENV, "").strip() != "1":
        return False
    declared_root = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if not declared_root:
        return True
    try:
        origin = Path(declared_root).expanduser().resolve()
    except OSError:
        return False
    return same_git_repository(root, origin)


def worktree_policy(root: Path) -> dict | None:
    policy_path = root / WORKTREE_POLICY_PATH
    try:
        parsed = json.loads(policy_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_worktree_policy() if local_worktree_policy_applies(root) else None
    except (OSError, ValueError):
        return default_worktree_policy()
    if not isinstance(parsed, dict):
        return default_worktree_policy()
    if set(parsed) != {"schema_version", "require_linked_worktree", "protected_branches"}:
        return default_worktree_policy()
    branches = parsed.get("protected_branches")
    valid = (
        parsed.get("schema_version") == WORKTREE_POLICY_SCHEMA_VERSION
        and parsed.get("require_linked_worktree") is True
        and isinstance(branches, list)
        and bool(branches)
        and all(isinstance(branch, str) and branch.strip() for branch in branches)
    )
    return parsed if valid else default_worktree_policy()


def current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# Four different conditions end at this one refusal, and for a long time it
# described only the last of them. A reader who hit any of the other three read
# a remedy that did not apply -- "go work in a linked worktree" when they were
# already in one -- and looked for a cause in the wrong place. Naming the
# condition costs one sentence and is the difference between a refusal a reader
# can act on and one they have to guess at.
UNREADABLE_SYNTAX = "unreadable_syntax"
COMPUTED_TEXT = "computed_text"
NAMED_TARGET = "named_target"
AUTHORING_GIT = "authoring_git"

DENIAL_CAUSES = {
    UNREADABLE_SYNTAX: (
        "The reason is this line's shape, not what it would do: it is a chain, a "
        "pipeline, or spans more than one line, so the gate cannot read which "
        "command runs here. A single command on one line is read on its own terms. "
    ),
    COMPUTED_TEXT: (
        "The reason is that the shell computes part of this line -- a substitution, "
        "a backquote, or a variable -- so its text does not say what will run, and "
        "no reading of it can. Spell the value out. "
    ),
    NAMED_TARGET: (
        "The reason is a path this line names, not where it runs: the target is "
        "inside the protected checkout, so running from a worktree does not move "
        "the write out of it. "
    ),
    AUTHORING_GIT: (
        "The reason is what this Git command does here: it writes new content "
        "into this working tree, or reaches a path in it through an option, "
        "which is the one thing the protected checkout is protected from. "
    ),
}


def worktree_deny_reason(root: Path, branch: str, cause: str = "") -> str:
    location = "main checkout" if (root / ".git").is_dir() else f"protected branch `{branch}`"
    return (
        f"Tao Agent OS worktree gate: {location} cannot run a mutating tool in {root}. "
        f"{DENIAL_CAUSES.get(cause, '')}"
        "Create or select the task's dedicated linked worktree, make that path the project root, "
        "run the workflow start hook again there, and retry. The hook does not create a worktree "
        "because branch, base, ticket, and local-file copy decisions belong to the repository workflow. "
        "Creating one needs no exception and no operator: a lone `git worktree add <path> -b <branch> "
        "<base>` is a bootstrap command this gate allows from here, and it makes the missing parent "
        "directories itself. It has to stand alone on one readable line -- a `mkdir` ahead of it, a "
        "substitution inside it, or a line continuation makes the whole line a mutation here and earns "
        "this same denial, which is what sends a reader looking for an operator to run it. Everything "
        "after it belongs in the new worktree, as `cd <worktree> && <command>`. "
        f"Set {MAIN_CHECKOUT_OVERRIDE_ENV}=1 only for a user-approved exception."
    )


def worktree_denial(root: Path, cause: str = "") -> str | None:
    policy = worktree_policy(root)
    if policy is None or os.environ.get(MAIN_CHECKOUT_OVERRIDE_ENV, "").strip() == "1":
        return None
    branch = current_branch(root)
    if (root / ".git").is_dir() or branch in set(policy["protected_branches"]):
        return worktree_deny_reason(root, branch, cause)
    return None
