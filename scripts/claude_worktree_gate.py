"""Repo-declared worktree isolation for Claude PreToolUse events."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

# Command classification is a separate owner; the gate keeps only the policy.
# These re-exports are the module's public surface for the pretool gate.
from claude_bash_readonly import (  # noqa: F401
    RUNTIME_CONTROL_KIND,
    bash_command,
    bash_command_kind,
    bash_invocation,
    copy_source_token_indices,
    has_unresolvable_expansion,
    path_arguments,
    raw_path_arguments,
    read_only_path_token_indices,
)
from support.stable_launcher import stable_launcher_path  # noqa: F401


BASH_TOOLS = {"Bash"}
WORKTREE_POLICY_PATH = Path(".agents/shared/worktree-policy.json")
WORKTREE_POLICY_SCHEMA_VERSION = 1
# The contract stays closed so an unknown key is a malformed declaration rather
# than a silently ignored one, but the closed set is now two sets: a policy
# written before the optional key existed must keep validating unchanged.
WORKTREE_POLICY_REQUIRED_KEYS = frozenset(
    {"schema_version", "require_linked_worktree", "protected_branches"}
)
WORKTREE_POLICY_OPTIONAL_KEYS = frozenset(
    {
        "require_workflow_entry",
        "require_ticketed_product_branch",
        "ticket_key_pattern",
        "product_path_prefixes",
        "product_file_names",
        "product_suffixes",
    }
)
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
        # An inherited flag without an owning repository is not a global policy.
        # Tracked target policy remains authoritative even without this bridge.
        return False
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
    keys = set(parsed)
    if not WORKTREE_POLICY_REQUIRED_KEYS <= keys:
        return default_worktree_policy()
    if not keys <= (WORKTREE_POLICY_REQUIRED_KEYS | WORKTREE_POLICY_OPTIONAL_KEYS):
        return default_worktree_policy()
    branches = parsed.get("protected_branches")
    valid = (
        parsed.get("schema_version") == WORKTREE_POLICY_SCHEMA_VERSION
        and isinstance(parsed.get("require_linked_worktree"), bool)
        and isinstance(branches, list)
        and (bool(branches) or parsed["require_linked_worktree"] is False)
        and all(isinstance(branch, str) and branch.strip() for branch in branches)
        and all(
            isinstance(parsed[name], bool)
            for name in ("require_workflow_entry", "require_ticketed_product_branch")
            if name in parsed
        )
        and _ticket_policy_is_valid(parsed)
    )
    return parsed if valid else default_worktree_policy()


def _ticket_policy_is_valid(policy: dict) -> bool:
    if policy.get("require_ticketed_product_branch") is not True:
        return not any(
            key in policy
            for key in (
                "ticket_key_pattern",
                "product_path_prefixes",
                "product_file_names",
                "product_suffixes",
            )
        )
    pattern = policy.get("ticket_key_pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    for key in ("product_path_prefixes", "product_file_names", "product_suffixes"):
        values = policy.get(key)
        if not isinstance(values, list) or not values:
            return False
        if not all(isinstance(value, str) and value.strip() for value in values):
            return False
    return True


def policy_requires_workflow_entry(root: Path) -> bool:
    """Whether this repository refuses the compliant-worktree preflight waiver.

    Isolation and workflow entry are separate protections, and satisfying the
    linked-worktree policy waives the second one so a compliant checkout stays
    writable without a run. That waiver is why a repository can declare
    isolation and still see no ``start`` for a whole task.

    A repository opts back into the run requirement by declaring it, so the
    default stays the waiver and no existing checkout changes behaviour when
    this lands. The absent key reads as False for the same reason the waiver
    exists: turning the requirement on everywhere at once is what makes an
    operator switch the gate off instead.
    """

    policy = worktree_policy(root)
    return bool(policy and policy.get("require_workflow_entry") is True)


def ticketed_product_branch_denial(root: Path, target: Path) -> str | None:
    """Return a denial when a declared product path has no ticketed branch."""

    policy = worktree_policy(root)
    if not policy or policy.get("require_ticketed_product_branch") is not True:
        return None
    try:
        relative = target.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    path = relative.as_posix()
    product_path = any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in policy["product_path_prefixes"]
    )
    product_path = product_path or relative.name in policy["product_file_names"]
    product_path = product_path or any(
        path.endswith(suffix) for suffix in policy["product_suffixes"]
    )
    if not product_path:
        return None
    branch = current_branch(root)
    if re.search(policy["ticket_key_pattern"], branch):
        return None
    return (
        "Tao Agent OS ticket gate: product code cannot be edited on the "
        f"ticketless branch `{branch or '<detached>'}` ({path}). Create or reuse "
        "the task ticket, then use its key in the dedicated worktree branch. "
        "Documentation, agent rules, and local runtime files remain exempt."
    )


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
        "Cause: use one literal command; chains, pipes, and multiline input are "
        "not accepted. "
    ),
    COMPUTED_TEXT: (
        "Cause: expand substitutions, backquotes, and variables before running "
        "the command. "
    ),
    NAMED_TARGET: "Cause: the command names a protected-checkout path. ",
    AUTHORING_GIT: "Cause: this Git command writes to the protected checkout. ",
}

# A path is read wherever it is written, including inside a larger token, because
# `sh -c 'touch <protected>/x'` names its target as a substring and would
# otherwise pass. The cost is that a path can be found in a token that is not a
# path operand at all -- a `sed` expression mentioning the checkout, an argument
# handed to a script -- and the refusal then reads as if the file being written
# were the problem. Saying which path was found is the difference: three times in
# one session the wrong operand was blamed, twice by the agent maintaining this
# file, because the sentence above names no path at all.
NAMED_TARGET_PATH = "Cause: protected path named: `{named}`. "


def named_target_cause(named: str = "") -> str:
    """The named-target sentence, carrying the path when one is known."""

    if not named:
        return DENIAL_CAUSES[NAMED_TARGET]
    return NAMED_TARGET_PATH.format(named=named)


def worktree_deny_reason(
    root: Path, branch: str, cause: str = "", named: str = "", *,
    require_linked_worktree: bool = True,
) -> str:
    location = (
        "main checkout"
        if require_linked_worktree and (root / ".git").is_dir()
        else f"protected branch `{branch}`"
    )
    explanation = (
        named_target_cause(named)
        if cause == NAMED_TARGET
        else DENIAL_CAUSES.get(cause, "")
    )
    remedy = (
        "Next: use the task worktree and restart the workflow. If needed, run "
        "alone: `git worktree add <path> -b <branch> <base>`."
        if require_linked_worktree
        else "Next: use a task branch outside this project's protected branches."
    )
    if require_linked_worktree and os.environ.get("TAO_PRETOOL_RUNTIME") == "codex":
        remedy = (
            "Next: target the existing task worktree explicitly with "
            '`git -C "<worktree>" <args>` or `cd "<worktree>" && <command>`. '
            "Codex may omit exec workdir from the hook payload, leaving the session cwd. "
            "Reuse the bound task; create/start one only if none exists. "
            "Explicit targeting does not grant sandbox permission or allow writes to main."
        )
    return f"Tao worktree gate: write blocked in {location}: {root}. {explanation}{remedy}"


def worktree_denial(root: Path, cause: str = "", named: str = "") -> str | None:
    policy = worktree_policy(root)
    if policy is None or os.environ.get(MAIN_CHECKOUT_OVERRIDE_ENV, "").strip() == "1":
        return None
    branch = current_branch(root)
    requires_linked = policy["require_linked_worktree"]
    if (requires_linked and (root / ".git").is_dir()) or branch in set(policy["protected_branches"]):
        return worktree_deny_reason(
            root, branch, cause, named, require_linked_worktree=requires_linked
        )
    return None
