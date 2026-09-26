"""Which publications a finished run admits, and why it refuses the rest.

Owner: post-finish admission of add, commit, push, tag, pull-request creation,
a bounded rebase and a finished worktree's fast-forward, alone or chained with
read-only observations, plus the refusal that names the failing cause.
Allowed imports: the standard library, claude_bash_git, claude_bash_raw_lines,
claude_bash_syntax, claude_command_effect, claude_worktree_gate,
claude_pretool_worktree_integration, and the publication/rebase admission
modules (lazily).
Forbidden imports: claude_pretool_gate; run evidence arrives as FinishedRuns.
Callers/tests: claude_pretool_gate (which re-exports these names);
tests/test_agent_publication_admission.py, test_agent_rebase_admission.py,
test_finished_worktree_integration.py.
Verification: those modules.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_git import git_subcommand
from claude_bash_raw_lines import raw_command_segments
from claude_bash_syntax import command_behind_wrappers
from claude_command_effect import (
    GH_PR_MERGE_REASON,
    command_effect,
    github_pr_merge,
    github_publication,
)
from claude_pretool_worktree_integration import FinishedRuns, integrates_finished_worktree
from claude_worktree_gate import bash_command_kind, project_publication_kind

# The steps the lifecycle names after finish: "before final report, commit,
# release, or handoff". Deliberately not the ordinary-Git set, which also holds
# `clean`, `reset`, `rm` and unrestricted `rebase`. The separate bounded rebase
# path admits local Git work, then checks resulting inputs before publication.
PUBLICATION_GIT_SUBCOMMANDS = frozenset({"add", "commit", "push", "tag"})
DEFAULT_PROTECTED_BRANCHES = frozenset({"main", "master", "develop"})


def publishes_finished_work(
    root: Path,
    session_id: str,
    tokens: list[str],
    runs: FinishedRuns,
    cwd: Path | None = None,
) -> bool:
    """Admit finished work without granting new publication authority.

    Registry completion and freshness select a candidate only. Its receipt
    must also bind unchanged source/rules content and an admitted effect at
    least as strong as this action. A commit of identical finished bytes does
    not invalidate that receipt; edits do. Repeated attempts are not counted
    as authority and must pass these checks each time. PR merge and arbitrary
    API writes retain their separate admission paths.
    """

    if not tokens:
        return False
    command = command_behind_wrappers(tokens)
    if not command:
        return False
    # Integration of a finished worktree is admitted here so that every
    # caller of this function -- the chain reader, the main verdict loop
    # and the reached-into-project check -- inherits one answer.
    if Path(command[0]).name == "git" and git_subcommand(command)[0] == "merge":
        return integrates_finished_worktree(root, session_id, command, runs, cwd)
    from agent_publication_admission import PublicationAdmission

    if Path(command[0]).name == "git" and git_subcommand(command)[0] == "rebase":
        from agent_rebase_admission import rebase_continuation_shape

        # Only the ordinary invocation: no -c, alternate worktree or git-dir.
        if command != tokens or command[:2] != ["git", "rebase"] or not rebase_continuation_shape(
            root, command[2:], set(runs.protected_branches(root) or DEFAULT_PROTECTED_BRANCHES),
        ):
            return False
        evidence = runs.evidence(root, session_id)
        return runs.is_fresh(evidence) and PublicationAdmission.allows(root, evidence, "git_write")
    effect = _publication_effect(root, command, cwd or root)
    if not effect:
        return False
    evidence = runs.evidence(root, session_id)
    if not runs.is_fresh(evidence):
        return False
    return PublicationAdmission.allows(root, evidence, effect)


def _publication_effect(root: Path, command: list[str], cwd: Path) -> str:
    """The effect a post-finish publication needs, or "" when it is not one.

    One answer for admission and for the denial that explains a refusal, so
    the two can never disagree about what a command requires.
    """

    if Path(command[0]).name == "git":
        subcommand, _arguments = git_subcommand(command)
        if subcommand not in PUBLICATION_GIT_SUBCOMMANDS:
            return ""
        return "external_write" if subcommand == "push" else "git_write"
    if github_publication(command) or project_publication_kind(root, command, cwd) == "publishes":
        return "external_write"
    return ""


_REFUSAL_CAUSES = {
    "missing_receipt": "finish recorded no publication receipt for this run",
    "unreadable_receipt": "this run's publication receipt is unreadable",
    "unverifiable_receipt": "the receipt could not be checked against this run's current evidence and inputs",
    "foreign_receipt": "the receipt belongs to other evidence; the run changed after finish",
    "project_changed": "project files changed after finish; review and finish the changed bytes",
    "rules_changed": "Tao rules changed after finish; rerun review and finish on the current rules",
}


def finished_publication_denial(
    root: Path, session_id: str, command: str, cwd: Path, runs: FinishedRuns
) -> str:
    """Say why a completed run cannot admit this publication, not every reason it might."""

    cause = "the command is not a lone admissible publication; run it without chained writes"
    evidence = runs.evidence(root, session_id)
    for segment in raw_command_segments(command, reject_redirections=True) or []:
        tokens = command_behind_wrappers(segment)
        effect = _publication_effect(root, tokens, cwd) if tokens else ""
        if not effect and tokens and github_pr_merge(tokens) == "unadmitted":
            cause = GH_PR_MERGE_REASON
            break
        if not effect or evidence is None:
            continue
        from agent_publication_admission import PublicationAdmission

        refusal = PublicationAdmission.refusal(root, evidence, effect)
        if refusal.startswith("effect:"):
            granted, needed = refusal.removeprefix("effect:").split("<")
            cause = (
                f"the run was admitted for {granted} and this publication needs {needed}. "
                "When the user's request authorizes push, pull-request creation or merge, start "
                "that run with --approved-effect external_write so its finish admits them"
            )
        elif refusal:
            cause = _REFUSAL_CAUSES.get(refusal, refusal)
        break
    return (
        "Tao lifecycle: a completed run exists for this session, but it cannot "
        f"admit this publication: {cause}. Do not open another run or repeat finish "
        "merely to change command syntax; enter a new scoped workflow only for a new "
        "authorized write."
    )


def publishes_finished_command(
    root: Path,
    session_id: str,
    command: str,
    cwd: Path,
    runs: FinishedRuns,
) -> bool:
    """Allow only finished publications plus harmless observations in a chain.

    A finished run already authorizes add/commit/push and PR creation. Shells
    commonly join those with ``&&``; requiring a lone command recreated a
    second lifecycle for the exact same publication. Every other segment must
    independently classify read-only, so ``git push && touch file`` stays
    blocked and a finish never becomes general shell authority.
    """

    # Redirection operands are file targets, not executable read-only segments.
    # A completed run does not grant new filesystem writes via shell redirects.
    segments = raw_command_segments(command, reject_redirections=True)
    if not segments:
        return False
    # A rebase may change the attested bytes. Never pre-authorize a following
    # push/commit using the receipt captured before that rebase executes.
    if len(segments) != 1 and any(git_subcommand(segment)[0] == "rebase" for segment in segments):
        return False
    published = False
    for segment in segments:
        if publishes_finished_work(root, session_id, segment, runs, cwd):
            published = True
            continue
        legacy_kind = bash_command_kind(segment, True, cwd)
        effect, _reason = command_effect(segment, True, legacy_kind)
        if effect != "read_only":
            return False
    return published
