#!/usr/bin/env python3
"""Claude Code PreToolUse gate for Tao Agent OS.

This gate enforces three things a purely advisory bridge cannot, at the only point
that actually stops the model -- the moment it calls a mutating tool:

1. Workflow entry. Nothing otherwise stops a file edit when the agent skipped the
   ``start`` hook, so the workflow is easy to ignore. The gate denies a file-edit
   tool call when an Tao Agent OS project has no fresh preflight evidence, which
   forces ``start`` (route + preflight) before mutating files.
2. Structural proportionality. Skill docs and the post-hoc review gate cannot
   stop a task from ballooning into many new files/layers -- by review time the
   tokens and analysis are already spent. This gate counts new source files a
   session creates and denies the one past the budget, so sprawl has to be
   collapsed or justified per file before more files are written. A recorded
   justification (the ack file) unlocks the rest of the session; the gate never
   hard-bricks and always fails open.
3. Repo-declared worktree isolation. A project can track
   ``.agents/shared/worktree-policy.json`` to require a linked worktree and
   protect integration branches. The same rule applies to discrete edit tools
   and to Bash commands that are not provably read-only or worktree bootstrap
   commands.

Contract (Claude Code PreToolUse hook):
- Reads a JSON payload from stdin with ``tool_name``, ``cwd``, ``session_id``,
  and ``tool_input`` (``file_path`` for Write).
- Prints a ``permissionDecision`` JSON object to allow or deny.
- File-edit tools and potentially mutating Bash calls are gated; everything else
  and every unexpected error fails open (exit 0, no output) so the gate can never
  brick ordinary editing.

Requires a Claude Code that puts ``CLAUDE_CODE_SESSION_ID`` in the Bash
subprocess environment (v2.1.128-v2.1.136, Week 19 2026), because that is what
lets the ``start`` hook stamp the session the gate checks. On an older build the
stamp is always absent and every edit is denied; set ``TAO_CLAUDE_GATE=0``
to turn the gate off there.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:  # The gate must never fail to load; the import is only used for a message.
    from agent_runtime_session import (
        is_run_local_continuation_evidence,
        resolve_runtime_evidence,
    )
    from support.stable_launcher import stable_launcher_path
    from support.global_state import (
        global_state_dir,
        is_host_config_dir,
        is_project_state_dir,
        prefer_git_root,
    )
    from claude_bash_git import git_subcommand, names_unsafe_git_option
    from claude_worktree_gate import (
        BASH_TOOLS,
        MAIN_CHECKOUT_OVERRIDE_ENV,
        REQUIRE_LINKED_WORKTREE_ENV,
        WORKTREE_POLICY_PATH,
        bash_command,
        bash_command_kind,
        bash_invocation,
        copy_source_token_indices,
        git_common_dir,
        has_unresolvable_expansion,
        path_arguments,
        raw_path_arguments,
        worktree_denial,
        worktree_policy,
    )
except ImportError:  # pragma: no cover - exercised only on a broken install
    def stable_launcher_path() -> Path:
        return Path.home() / ".tao" / "bin" / "tao-hook"

    def is_project_state_dir(path: Path) -> bool:
        return path.is_dir() and path.resolve() != (Path.home() / ".tao").resolve()

    def global_state_dir() -> Path:
        import os
        override = os.environ.get("TAO_STATE_HOME", "").strip()
        return Path(override).expanduser() if override else Path.home() / ".tao"

    def is_host_config_dir(path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return resolved.parent == Path.home().resolve() and resolved.name.startswith(".")

    def prefer_git_root(candidates: "list[Path]") -> "Path | None":
        for candidate in candidates:
            if (candidate / ".git").exists():
                return candidate
        return candidates[0] if candidates else None

    def resolve_runtime_evidence(project: Path, session: dict[str, str]) -> Path | None:
        return None

    def is_run_local_continuation_evidence(
        project: Path, evidence: Path | None
    ) -> bool:
        return False

    BASH_TOOLS = {"Bash"}
    MAIN_CHECKOUT_OVERRIDE_ENV = "TAO_ALLOW_MAIN_CHECKOUT_EDIT"
    REQUIRE_LINKED_WORKTREE_ENV = "TAO_REQUIRE_LINKED_WORKTREE"
    WORKTREE_POLICY_PATH = Path(".agents/shared/worktree-policy.json")

    def bash_command(payload: dict) -> str:
        return ""

    def bash_invocation(payload: dict, cwd: Path) -> tuple[Path, list[str], bool]:
        return cwd, [], False

    def raw_path_arguments(command: str) -> "list[Path]":
        return []

    def copy_source_token_indices(tokens: list[str]) -> "frozenset[int]":
        # A broken install claims no operand is read-only, so every path stays
        # a target and the gate keeps its strictest reading.
        return frozenset()

    def has_unresolvable_expansion(command: str) -> bool:
        return False

    def git_common_dir(root: Path) -> "Path | None":
        return None

    def bash_command_kind(tokens: list[str], syntax_is_simple: bool) -> str:
        return "mutating"

    def worktree_policy(root: Path) -> dict | None:
        return None

    def worktree_denial(root: Path) -> str | None:
        return None

    def git_subcommand(tokens: list[str]) -> tuple[str | None, list[str]]:
        # A broken install is not a policy violation, and the stubs around this
        # one all answer "nothing to report" for that reason. Returning "cannot
        # tell" here instead would make every Git command prompt on an install
        # that is already failing, which is the shape of gate the operator
        # switches off.
        return "", []

    def names_unsafe_git_option(argument: str) -> bool:
        return False


def __getattr__(name: str):
    """Load the continuation adapter the first time anything asks for it.

    Importing it at module load cost every gated call the checkpoint, drift
    and worktree-fingerprint chain behind it -- about 15 ms of the 38 ms a
    tool call spends in this process -- although only a file edit ever calls
    it, and a session runs far more Bash calls than edits.

    It stays a module attribute rather than a private accessor because that is
    the surface the gate is tested through: a broken install shows up as this
    attribute being ``None``, and that must remain something a caller can see
    and set. An import failure is still not a policy violation, so it resolves
    to ``None`` here exactly as the module-level fallback did.
    """

    if name != "ClaudeContinuationAdapter":
        raise AttributeError(name)
    try:
        from claude_continuation_hook import ClaudeContinuationAdapter as adapter
    except ImportError:  # pragma: no cover - exercised only on a broken install
        adapter = None
    globals()[name] = adapter
    return adapter


_UNLOADED = object()


def continuation_adapter():
    """Resolve the adapter through this module's own namespace.

    One loading path and one patch point: a caller that replaces the module
    attribute changes what the gate uses, which a direct import inside this
    function would silently bypass. The lookup is by namespace rather than
    through ``sys.modules``, because this gate is also loaded under a
    synthetic name that was never registered there.
    """

    cached = globals().get("ClaudeContinuationAdapter", _UNLOADED)
    if cached is not _UNLOADED:
        return cached
    return __getattr__("ClaudeContinuationAdapter")


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GATED_TOOLS = EDIT_TOOLS | BASH_TOOLS
# Only Write creates a file from nothing; Edit/MultiEdit require an existing
# file, so new-file sprawl flows through Write.
NEW_FILE_TOOLS = {"Write"}
STATE_DIR = ".tao"
SESSION_MARKER_DIR = "claude-pretool-gate"
NEW_FILE_STATE_SUFFIX = ".newfiles"
SPRAWL_ACK_SUFFIX = ".sprawl-ack"
# Shared with claude_stop_gate.py, which blocks a stop when an editing session
# has no passing finish.
EDIT_ACTIVITY_SUFFIX = ".edited"
# User-global, because the Stop gate must find projects outside its own cwd.
SESSION_PROJECT_DIR = "claude-session-projects"
OPT_IN_FILES = ("AGENTS.md", "CLAUDE.md", "CODEX.md")
OPT_IN_TOKEN = "tao"
DEFAULT_MAX_AGE_SECONDS = 8 * 60 * 60
MAX_ROOT_WALK = 40
# New source files past this count in one session must be collapsed or justified.
# Matches the review-time signal in
# agent_review_structure.REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT. Only code source
# files count, so doc/content work (e.g. a writing workspace full of .md drafts)
# is never blocked.
DEFAULT_NEW_FILE_BUDGET = 5
ORDINARY_GIT_SUBCOMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "config",
        "fetch",
        "gc",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reflog",
        "remote",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "submodule",
        "switch",
        "tag",
        "worktree",
    }
)
SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".cjs", ".dart", ".go", ".h", ".hpp",
    ".java", ".js", ".jsx", ".kt", ".kts", ".m", ".mjs", ".mm", ".php", ".py",
    ".rb", ".rs", ".sass", ".scss", ".svelte", ".swift", ".ts", ".tsx", ".vue",
}


GATE_DISABLE_HINT = (
    "Set TAO_CLAUDE_GATE=0 in the runtime environment to turn this gate off "
    "for the session."
)


def gate_enabled() -> bool:
    """Escape hatch for runtimes that cannot supply a session id."""
    return os.environ.get("TAO_CLAUDE_GATE", "").strip() != "0"


def allow() -> int:
    """Defer to Claude's normal permission flow without changing it."""
    return 0


def _approve(reason: str) -> int:
    """Skip a prompt for a command the worktree policy explicitly permits.

    A successful hook with no output is only a deferral. Claude may still ask
    about the Bash command, which turned the worktree policy into an Enter-only
    machine even after the gate itself stopped denying ordinary work. Emit the
    actual ``allow`` decision only for a simple Git invocation whose remaining
    effects have been classified below; arbitrary Bash keeps Claude's normal
    permission flow.
    """

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def deny(reason: str) -> int:
    """Stop a policy violation without turning it into an operator prompt.

    ``ask`` makes Claude request confirmation for every gated Edit, Write, and
    Bash call.  These failures have deterministic remedies -- enter the
    workflow, move to a permitted worktree, or reduce/justify the edit -- so the
    agent should apply the remedy instead of delegating every decision to the
    operator.
    """

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"{reason} {GATE_DISABLE_HINT}",
                }
            }
        )
    )
    return 0


def ask(reason: str) -> int:
    """Put one decision to the operator, for the rare kind that is a decision.

    ``deny`` is right wherever the remedy is deterministic: the agent enters the
    workflow, moves to a permitted worktree, or reduces the edit, and no human
    needs to watch it happen. A destructive command that is *sometimes exactly
    what was meant* has no such remedy -- denying it hides a real choice, and
    asking about everything buries that choice among the ordinary calls until
    the prompt stops carrying information.

    So this is reserved for the short hazard list, where Claude's prompt also
    offers "don't ask again": an operator who force-pushes daily answers once.
    """

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def max_age_seconds() -> int:
    raw = os.environ.get("TAO_CLAUDE_GATE_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_AGE_SECONDS
    return value if value >= 0 else DEFAULT_MAX_AGE_SECONDS


def opts_in(path: Path) -> bool:
    """True when this directory marks a project that uses Tao Agent OS.

    The global install lives in a ``.tao`` too, so directory existence alone
    would classify ``$HOME`` as a project -- see support.global_state.
    """
    if is_host_config_dir(path):
        return False
    if is_project_state_dir(path / STATE_DIR):
        return True
    for name in OPT_IN_FILES:
        candidate = path / name
        try:
            head = candidate.read_text(encoding="utf-8", errors="ignore")[:8192]
        except OSError:
            continue
        if OPT_IN_TOKEN in head.lower():
            return True
    return False


def find_project_root(cwd: Path) -> Path | None:
    """The repository that owns cwd, preferring a Git root over a marker.

    Collecting every opt-in ancestor rather than returning the first one lets
    prefer_git_root reject a documentation subdirectory that opts in but is
    not the repository. Must stay identical between the pretool and stop gates.
    """
    candidates: list[Path] = []
    for candidate in (cwd, *cwd.parents):
        if opts_in(candidate):
            candidates.append(candidate)
        if candidate == candidate.parent:
            break
    return prefer_git_root(candidates)


def evidence_mtime(evidence: Path | None) -> float | None:
    if evidence is None:
        return None
    try:
        return evidence.stat().st_mtime
    except OSError:
        return None


def evidence_is_fresh(evidence: Path | None) -> bool:
    mtime = evidence_mtime(evidence)
    if mtime is None:
        return False
    return (time.time() - mtime) <= max_age_seconds()


def safe_session_id(session_id: str) -> str:
    cleaned = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
    return cleaned or "unknown-session"


def stopped_action(tool: str) -> tuple[str, str]:
    """Name what was stopped, and what retrying it means.

    The gate covered edits when this message was written and has covered
    commands since. It kept saying "before editing files" and "retry the edit"
    while stopping `git commit`, `git push` and `git checkout -b`, so a reader
    whose commit was stopped was told about a file they had not touched.

    Each phrase carries "this project" itself rather than leaving it to the
    sentence around it, because a command is stopped for changing the project
    and an edit for touching files in it -- two different places for the same
    words, and a shared suffix produced "this project in this project".
    """

    if tool in BASH_TOOLS:
        return (
            "running a command that changes this project",
            "retry the command",
        )
    return ("editing files in this project", "retry the edit")


def deny_reason(root: Path, session_id: str = "", tool: str = "") -> str:
    """Explain the denial in terms of what is actually wrong with the evidence.

    Reporting "no fresh evidence" when a stamped-but-foreign or unstamped
    preflight is sitting right there sends the reader looking for a missing
    file. Each cause has a different fix, so each gets its own sentence.
    """
    evidence = session_evidence(root, session_id)
    if evidence is None:
        cause = (
            "No exact registered preflight evidence is bound to this runtime session. "
            "Fresh or default-path evidence from another session is not reusable."
        )
    elif not evidence_is_fresh(evidence):
        cause = f"Preflight evidence at {evidence} is older than the freshness window."
    else:
        cause = f"Preflight evidence at {evidence} does not satisfy the workflow entry gate."
    action, retry = stopped_action(tool)
    return (
        f"Tao Agent OS: run the workflow start hook before {action}. {cause} "
        f"Run `{stable_launcher_path()} start --project "
        f"{root} --rules <TAO_ROOT> --command <route> --request \"<user "
        f"request>\"`, read the route required_docs, then {retry}. Set "
        "TAO_CLAUDE_GATE_MAX_AGE_SECONDS to tune the freshness window."
    )


def workflow_entry_allows(root: Path, session_id: str) -> bool:
    """Gate 1: the workflow ``start`` hook must have run this session.

    The gate only reads. ``start`` stamps its own session into the preflight
    evidence, so proof of workflow entry has exactly one writer. Two earlier
    designs failed because the gate wrote that proof itself: first by promoting
    any fresh evidence into a session marker (which let a previous session's
    file unlock this one), then by comparing timestamps (which denied the
    correct ``start`` -> edit order outright, because evidence written before
    the first edit attempt can never be newer than it).

    Freshness stays as a second condition so an abandoned session cannot be
    resumed days later on its original evidence. A stale claim is refused, not
    turned into an operator prompt; the agent must refresh workflow entry.
    """
    if not session_id:
        # Nothing to attribute the evidence to. Falling back to freshness here
        # would reopen the original bypass on any payload missing a session.
        return False
    evidence = session_evidence(root, session_id)
    return evidence is not None and evidence_is_fresh(evidence)


def session_evidence(root: Path, session_id: str) -> Path | None:
    if not session_id:
        return None
    return resolve_runtime_evidence(
        root,
        {"runtime": "claude", "session_id": session_id},
    )


def record_edit_activity(root: Path, session_id: str) -> None:
    """Note that this session actually mutated files.

    This is an activity record, not gate-passing proof -- the distinction that
    matters here. Writing proof is what let an earlier version of this gate
    fabricate its own workflow entry; writing "this session edited something" is
    only what the Stop gate needs to know a missing finish is worth blocking on.
    A read-only session never gets this marker and is never blocked at Stop.
    """
    marker = root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + EDIT_ACTIVITY_SUFFIX)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
    except OSError:
        pass


def session_projects_index(session_id: str) -> Path:
    """Per-session list of every project this session edited.

    The Stop gate runs once, with one cwd, but a session can edit files in
    several projects. Without this index it only ever checks the cwd project and
    lets an edited-but-unverified project stop silently.
    """
    return global_state_dir() / SESSION_PROJECT_DIR / safe_session_id(session_id)


def record_session_project(root: Path, session_id: str) -> None:
    index = session_projects_index(session_id)
    line = str(root)
    try:
        existing = index.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    if line in existing:
        return
    try:
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def new_file_budget() -> int:
    raw = os.environ.get("TAO_CLAUDE_GATE_NEW_FILE_BUDGET", "").strip()
    if not raw:
        return DEFAULT_NEW_FILE_BUDGET
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_NEW_FILE_BUDGET
    return value if value >= 0 else DEFAULT_NEW_FILE_BUDGET


def write_target_path(payload: dict, cwd: Path) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    # NotebookEdit names its target `notebook_path`; every other edit tool uses
    # `file_path`. Reading only the latter made a notebook edit look like a tool
    # with no target, so it was judged by the working directory alone and could
    # rewrite a notebook inside a protected checkout from outside it.
    raw = next(
        (
            tool_input[key]
            for key in ("file_path", "notebook_path")
            if isinstance(tool_input.get(key), str)
        ),
        None,
    )
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        target = Path(raw)
    except ValueError:
        return None
    if not target.is_absolute():
        target = cwd / target
    return target


def find_edit_project_root(payload: dict, cwd: Path) -> Path | None:
    """Resolve the project that owns the file being edited, not just the cwd.

    A session's working directory and the file it edits are often different
    projects: this gate let a whole article get rewritten in a writing workspace
    while the cwd sat in another repo, so the writing project's own `start` was
    never required and its edits were recorded against the wrong project. The
    Stop gate then asked the cwd project for a finish, found one, and allowed a
    stop that left the edited project unverified.

    The target path decides. cwd stays as the fallback for tools that report no
    file path.
    """
    target = write_target_path(payload, cwd)
    if target is not None:
        root = find_project_root(target.parent)
        if root is not None:
            return root
    return find_project_root(cwd)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def sprawl_state_file(root: Path, session_id: str) -> Path:
    return root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + NEW_FILE_STATE_SUFFIX)


def sprawl_ack_file(root: Path, session_id: str) -> Path:
    return root / STATE_DIR / SESSION_MARKER_DIR / (safe_session_id(session_id) + SPRAWL_ACK_SUFFIX)


def read_new_files(state: Path) -> list[str]:
    try:
        text = state.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def record_new_file(state: Path, key: str) -> None:
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        with state.open("a", encoding="utf-8") as handle:
            handle.write(key + "\n")
    except OSError:
        pass


def sprawl_deny_reason(count: int, budget: int, ack: Path, target: Path, root: Path) -> str:
    return (
        f"Tao Agent OS proportionality gate: this task has already created {count} new "
        f"source file(s) in {root.name} (budget {budget}); creating {target.name} would exceed "
        "it. Turning a task into many files, layers, or abstractions burns tokens and review "
        "time. Collapse the change into fewer files, or -- if each new file protects a concrete "
        f"present risk -- record the per-file justification by writing it to {ack}, then retry. "
        "Tune with TAO_CLAUDE_GATE_NEW_FILE_BUDGET."
    )


def sprawl_deny(tool: str, payload: dict, root: Path, cwd: Path, session_id: str) -> str | None:
    """Gate 2: deny the new source file that pushes a task past its budget."""
    if tool not in NEW_FILE_TOOLS:
        return None
    budget = new_file_budget()
    if budget <= 0:
        return None
    try:
        target = write_target_path(payload, cwd)
        if target is None or target.exists():
            # No path, or editing/overwriting an existing file -- not new-file sprawl.
            return None
        if STATE_DIR in target.parts:
            return None  # agent state (including the ack file itself) never counts
        if not is_relative_to(target, root):
            return None  # outside the project
        if target.suffix.lower() not in SOURCE_SUFFIXES:
            return None  # docs/config/content are not code sprawl

        state = sprawl_state_file(root, session_id)
        recorded = read_new_files(state)
        key = str(target)
        if sprawl_ack_file(root, session_id).exists():
            if key not in recorded:
                record_new_file(state, key)
            return None
        if key in recorded:
            return None  # idempotent retry of an already-counted file
        if len(recorded) + 1 > budget:
            return sprawl_deny_reason(len(recorded), budget, sprawl_ack_file(root, session_id), target, root)
        record_new_file(state, key)
        return None
    except Exception:
        return None


def workflow_start_target_root(tokens: list[str], effective_cwd: Path) -> Path | None:
    """The project a start hook will claim, whose policy judges that start.

    Only argv-shaped values are visible; the caller has already required the
    whole command to classify as ``workflow_start``, so a write smuggled next
    to the start keeps its own ``mutating`` verdict and never reaches here.
    """

    target = effective_cwd
    for index, token in enumerate(tokens):
        if token == "--project" and index + 1 < len(tokens):
            raw = Path(tokens[index + 1]).expanduser()
            target = raw if raw.is_absolute() else effective_cwd / raw
            break
    try:
        resolved = target.resolve()
    except OSError:
        return None
    return find_project_root(resolved)


def bash_governed_roots(
    tokens: list[str], *cwds: Path, command: str = ""
) -> list[Path]:
    """Every protected project this command runs in or writes into.

    Taking the first root and stopping let a session inside a linked worktree
    write into the protected main checkout by naming it: the worktree is a
    project, it answers the worktree policy, and the named target was never
    reached. A command is governed by all of them, so each is returned and the
    caller denies if any one denies.

    Callers supply the directory where the command actually executes. A
    recognised `cd <worktree> && ...` prefix must not keep the launch checkout
    as a fictitious write target; explicit paths back into that checkout are
    still discovered below and remain denied.
    """

    roots: list[Path] = []
    for cwd in cwds:
        root = find_project_root(cwd)
        if root is not None and root not in roots:
            roots.append(root)
    for cwd in cwds:
        for root in bash_target_project_roots(tokens, cwd):
            if root not in roots:
                roots.append(root)
    # A command that could not be tokenised leaves no arguments to inspect, so
    # its raw text is read for absolute paths instead. Without this a heredoc
    # or a substitution carried its `cd <protected>` prefix past the gate.
    if not tokens and command:
        for path in raw_path_arguments(command):
            try:
                root = _owning_project(path)
            except UnresolvableTarget:
                for unclaimable in _unclaimable_command_roots():
                    if unclaimable not in roots:
                        roots.append(unclaimable)
                continue
            if root is not None and root not in roots:
                roots.append(root)
    # When the shell will compute text this module cannot reproduce, no reading
    # of that text locates the command. Enumerating spellings has no last move
    # -- a quoted space, an escaped space, `${VAR%/}`, `$(echo ...)` each
    # arrived after the previous was closed -- so the question becomes whether
    # the targets can be claimed at all. They cannot, and the session's own
    # declared project is the checkout such a command is most able to reach.
    if command and has_unresolvable_expansion(command):
        for root in _unclaimable_command_roots():
            if root not in roots:
                roots.append(root)
    return roots


def _git_effective_cwd(tokens: list[str], cwd: Path) -> Path:
    """Resolve Git's global ``-C`` options without running Git.

    Claude commonly stays launched in the protected checkout and runs
    ``git -C <linked-worktree> ...``. Judging that command by the launch cwd
    denies the isolated work it names. Multiple ``-C`` options are relative to
    the result of the previous one, matching Git's own command-line contract.
    Unknown global syntax stays at the conservative cwd and is already turned
    into a hazard by ``git_subcommand``.
    """

    if not tokens or Path(tokens[0]).name != "git":
        return cwd
    subcommand, arguments = git_subcommand(tokens)
    if subcommand is None:
        return cwd
    subcommand_index = len(tokens) - len(arguments) - 1
    resolved = cwd
    index = 1
    while index < subcommand_index:
        token = tokens[index]
        raw = ""
        if token == "-C" and index + 1 < subcommand_index:
            raw = tokens[index + 1]
            index += 2
        elif token.startswith("-C="):
            raw = token.split("=", 1)[1]
            index += 1
        else:
            index += 1
            continue
        if not raw:
            continue
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = resolved / target
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target
    return resolved


def _ordinary_git_invocation(tokens: list[str]) -> bool:
    subcommand, _arguments = git_subcommand(tokens)
    return subcommand in ORDINARY_GIT_SUBCOMMANDS


def _declared_project_root() -> Path | None:
    """The project the runtime says this session belongs to."""

    declared = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if not declared:
        return None
    try:
        return find_project_root(Path(declared).expanduser().resolve())
    except OSError:
        return None


def _unclaimable_command_roots() -> list[Path]:
    """Every protected checkout an unlocatable command could reach.

    Naming only the declared project answered for a session working inside a
    linked worktree, which its own policy permits, and stopped there -- so a
    command whose target could not be read was cleared by the one checkout that
    was never at risk. A linked worktree and the main checkout it branched from
    are the same repository, and the main checkout is the protected one, so an
    unlocatable command is judged against both.
    """

    roots: list[Path] = []
    declared = _declared_project_root()
    if declared is not None:
        roots.append(declared)
    for root in list(roots):
        main = _main_checkout_for(root)
        if main is not None and main not in roots:
            roots.append(main)
    return roots


def _main_checkout_for(root: Path) -> Path | None:
    """The repository's main checkout, given any of its worktrees.

    `git rev-parse` answers this when it can run, but it cannot when the
    worktree's admin directory is missing -- and a worktree that git refuses to
    describe is precisely the one whose main checkout still needs protecting.
    The `.git` file states the link in text, so it is read directly when the
    command gives no answer.
    """

    common = git_common_dir(root)
    if common is not None:
        try:
            return find_project_root(common.parent.resolve())
        except OSError:
            return None
    marker = root / ".git"
    try:
        link = marker.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    if not link.startswith("gitdir:"):
        return None
    gitdir = link.split(":", 1)[1].strip()
    separator = "/.git/worktrees/"
    if separator not in gitdir:
        return None
    candidate = Path(gitdir.split(separator, 1)[0])
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    try:
        return find_project_root(candidate.resolve())
    except OSError:
        return None


def bash_target_project_roots(tokens: list[str], cwd: Path) -> list[Path]:
    """Protected projects named by the command's own path arguments.

    A trusted plain `cp` only reads from every operand but its last, so those
    exact token positions name no target. Dropping them is what lets a linked
    worktree be seeded with the gitignored local files the main checkout alone
    holds -- the move this gate's own denial message asks for, and one no other
    source can supply, since an ignored file is not in the object store. The
    destination and any identical spelling in a later segment are still judged.
    """

    source_indices = copy_source_token_indices(tokens)
    targets = [
        token for index, token in enumerate(tokens) if index not in source_indices
    ]
    roots: list[Path] = []
    for path in path_arguments(targets):
        try:
            root = _owning_project(path if path.is_absolute() else cwd / path)
        except UnresolvableTarget:
            # Cannot answer where this writes, so it is judged like text the
            # shell computes rather than skipped into an allow.
            for unclaimable in _unclaimable_command_roots():
                if unclaimable not in roots:
                    roots.append(unclaimable)
            continue
        if root is not None and root not in roots:
            roots.append(root)
    return roots


class UnresolvableTarget(Exception):
    """A named target the filesystem refused to answer questions about."""


def _owning_project(path: Path) -> Path | None:
    """The project owning a named path, or a refusal to say.

    A path too long for the filesystem, or one carrying a null byte, made
    `resolve` and `exists` raise. Those errors escaped to `main`, whose whole
    job is to fail open, so a crafted target turned a crash into an allow --
    the one direction this gate must never move in. Raising a distinct error
    lets the caller treat "cannot answer" as "cannot claim the target", which
    is the same reading it already gives to text the shell computes.
    """

    try:
        candidate = path.resolve()
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
    except (OSError, ValueError) as error:
        raise UnresolvableTarget(str(path)[:64]) from error
    return find_project_root(candidate)



def worktree_policy_satisfied(root: Path) -> bool:
    """Whether this checkout has already proved its isolation.

    A repository declares that every task runs in its own linked worktree so
    two tasks cannot collide in one checkout. Where that policy is declared and
    this root is a compliant worktree, the isolation the gate exists to protect
    is already in place, and the run-evidence check below has nothing left to
    add.

    Requiring both made the policy unusable: a compliant worktree still could
    not be written to until preflight evidence existed, so the cheapest way to
    get work done was to turn the whole gate off -- taking the protection with
    it. The waiver is earned by the declared policy, never by its absence: a
    repository that declares nothing has proved nothing, and still needs the
    run.
    """

    return worktree_policy(root) is not None and worktree_denial(root) is None


def shared_repository_hazard(tokens: list[str]) -> str:
    """Why this Git command deserves one question, or "" for the ordinary kind.

    A linked worktree isolates the working tree and nothing else. Refs,
    remotes, tags, config, the object store and the reflog live in the common
    Git directory every worktree shares, so a handful of commands reach exactly
    what they would reach from the protected checkout.

    That is a reason to name those commands, not to distrust Git. Committing,
    branching, merging, stashing and pushing inside your own worktree is the
    work, and stopping it stops everything for the sake of the rare case. So
    this returns a reason only for the short list below, where losing
    work or escaping through an output/execution option is the command's actual
    effect -- and the answer there is `ask`, not `deny`, because each of these
    is sometimes precisely what was meant.
    """

    if not tokens or Path(tokens[0]).name != "git":
        return ""
    subcommand, arguments = git_subcommand(tokens)
    if subcommand is None:
        return "uses a Git option this gate cannot read, so what it does is unknown"
    if subcommand:
        subcommand_index = len(tokens) - len(arguments) - 1
        global_names = {
            token.split("=", 1)[0] for token in tokens[1:subcommand_index]
        }
        if global_names & {"-c", "--config-env", "--exec-path"}:
            return "changes configuration or executable lookup for this Git invocation"
    if any(names_unsafe_git_option(argument) for argument in arguments):
        return "names an option that can write output or execute another program"
    flags = {argument.split("=", 1)[0] for argument in arguments}
    words = [argument for argument in arguments if not argument.startswith("-")]
    first = words[0] if words else ""
    short_flags = {
        letter
        for argument in arguments
        if argument.startswith("-") and not argument.startswith("--")
        for letter in argument[1:]
    }

    if subcommand == "branch":
        # `-d` refuses to drop unmerged work; `-D`, `-M`, and `-f` do not.
        # Git accepts bundled short flags, so `-vD` must be read as containing
        # `-D`, not mistaken for an unrelated listing option.
        forced_long = "--force" in flags and flags & {"--delete", "--move"}
        if short_flags & {"D", "M", "f"} or forced_long:
            return "deletes or overwrites a branch every worktree shares"
    if subcommand == "push":
        force_flags = {"--delete", "--force", "--force-with-lease", "--mirror"}
        if "f" in short_flags or flags & force_flags:
            return "rewrites or deletes a published branch"
        if any(word.startswith("+") for word in words):
            return "force-pushes: a leading + in a refspec rewrites the remote"
    if subcommand == "reset" and "--hard" in flags:
        return "discards committed work reachable only from here"
    dry_run = short_flags & {"n"} or "--dry-run" in flags
    if subcommand == "clean" and not dry_run:
        return "deletes untracked work from this worktree"
    if subcommand == "restore":
        staged_only = "--staged" in flags and "--worktree" not in flags
        if not staged_only:
            return "discards uncommitted work from this worktree"
    if subcommand == "checkout":
        if short_flags & {"B", "f"} or flags & {"--force"} or "--" in arguments:
            return "discards work or overwrites a branch"
    if subcommand == "switch":
        force_flags = {"--discard-changes", "--force", "--force-create"}
        if short_flags & {"C", "f"} or flags & force_flags:
            return "discards work or overwrites a branch"
    if subcommand == "tag" and (
        short_flags & {"d", "f"} or flags & {"--delete", "--force"}
    ):
        return "deletes or overwrites a tag every worktree shares"
    update_ref_help = flags in ({"-h"}, {"--help"})
    if subcommand == "update-ref" and arguments and not update_ref_help:
        return "writes a shared ref directly, past the commands that check it"
    if subcommand in {"filter-branch", "filter-repo"}:
        return "rewrites the entire shared history"
    if subcommand == "reflog" and first in {"expire", "delete"}:
        return "removes the reflog, which is how the rest of this list is undone"
    if subcommand == "gc" and "--prune" in flags:
        return "prunes objects the reflog would otherwise recover"
    if subcommand == "prune":
        return "deletes unreachable objects from the shared object store"
    if subcommand == "replace" and flags & {"-d", "--delete"}:
        return "deletes a replacement ref every worktree shares"
    if subcommand == "remote" and first in {"remove", "rm", "set-url"}:
        return "changes a remote every worktree shares"
    if subcommand == "stash" and first in {"drop", "clear"}:
        return "drops stashed work every worktree shares"
    if subcommand == "worktree" and first in {"remove", "prune"}:
        return "removes another worktree, which may hold unfinished work"
    if subcommand == "submodule" and first in {"deinit", "foreach", "set-url"}:
        return "removes files, changes shared config, or executes a nested command"
    if subcommand == "config":
        getters = {"--get", "--get-all", "--get-regexp", "--list"}
        if flags & getters:
            return ""
        if flags & {"-f", "--file", "--global", "--system"}:
            return "changes Git configuration outside this repository"
        if "core.hooksPath" in words:
            return "changes the executable hooks path every worktree shares"
    return ""


def decide(payload: dict) -> int:
    if not gate_enabled():
        return allow()
    tool = payload.get("tool_name")
    if tool not in GATED_TOOLS:
        return allow()
    cwd_raw = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(cwd_raw).resolve()
    except OSError:
        return allow()
    bash_kind = ""
    # An Edit or Write has no command line, and the hazard check below runs for
    # every tool. Leaving this unbound made that check raise for exactly the
    # calls the waiver exists to allow.
    tokens: list[str] = []
    if tool in BASH_TOOLS:
        effective_cwd, tokens, syntax_is_simple = bash_invocation(payload, cwd)
        bash_kind = bash_command_kind(tokens, syntax_is_simple)
        command_cwd = _git_effective_cwd(tokens, effective_cwd)
        roots = bash_governed_roots(
            tokens, command_cwd, command=bash_command(payload)
        )
        root = roots[0] if roots else None
    else:
        root = find_edit_project_root(payload, cwd)
        roots = [root] if root is not None else []
    if root is None:
        # Not an Tao Agent OS project; never block ordinary editing.
        return allow()
    if tool in BASH_TOOLS and bash_kind == "read_only":
        return allow()
    if tool in BASH_TOOLS and bash_kind == "bootstrap":
        if (
            syntax_is_simple
            and tokens
            and Path(tokens[0]).name == "git"
            and worktree_policy_satisfied(root)
            and _ordinary_git_invocation(tokens)
        ):
            return _approve(
                "This is an ordinary Git command inside the isolated linked worktree."
            )
        return allow()
    # Every governed project, not just the first: a session inside a linked
    # worktree satisfies its own policy while naming the protected checkout it
    # was branched from, and taking the first answer let that through.
    worktree_reason = next(
        (reason for reason in map(worktree_denial, roots) if reason), None
    )
    if tool in BASH_TOOLS and bash_kind == "workflow_start":
        # The start hook claims only the project it names, and the denial that
        # sends a session here instructs it to run start in the linked
        # worktree. Judging that start by every governed root kept the
        # protected launch checkout in the verdict, so the gate denied its own
        # remedy. The named target's policy is the whole question.
        target_root = workflow_start_target_root(tokens, effective_cwd)
        if target_root is not None:
            reason = worktree_denial(target_root)
            return deny(reason) if reason else allow()
        return deny(worktree_reason) if worktree_reason else allow()
    if worktree_reason:
        return deny(worktree_reason)
    if worktree_policy_satisfied(root):
        hazard = shared_repository_hazard(tokens)
        if hazard:
            return ask(
                "This worktree isolates ordinary file edits, but this Git command "
                f"{hazard}. Allow it only if that is what you meant."
            )
        if (
            tool in BASH_TOOLS
            and syntax_is_simple
            and tokens
            and Path(tokens[0]).name == "git"
            and _ordinary_git_invocation(tokens)
        ):
            return _approve(
                "This is an ordinary Git command inside the isolated linked worktree."
            )
        return allow()
    session_id = str(payload.get("session_id") or "")
    if not workflow_entry_allows(root, session_id):
        return deny(deny_reason(root, session_id, tool))
    sprawl_reason = sprawl_deny(tool, payload, root, cwd, session_id)
    if sprawl_reason:
        return deny(sprawl_reason)
    # A missing adapter module is a broken install, not a policy violation. This
    # gate promises never to fail to load; denying every edit because an import
    # failed breaks that promise and removes the means of repairing the install.
    evidence = session_evidence(root, session_id)
    if evidence is None:
        # The active claim can disappear between the workflow-entry check and
        # the mutation checkpoint. Do not turn that registry race into an
        # uncheckpointed edit.
        return deny(deny_reason(root, session_id, tool))
    if tool in EDIT_TOOLS and is_run_local_continuation_evidence(root, evidence):
        adapter = continuation_adapter()
        if adapter is not None:
            continuation_reason = adapter.pre_mutation(
                payload, root=root, cwd=cwd, session_id=session_id
            )
            if continuation_reason:
                return deny(continuation_reason)
    record_edit_activity(root, session_id)
    record_session_project(root, session_id)
    return allow()


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return allow()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return allow()
        return decide(payload)
    except Exception:
        # Any unexpected failure must fail open.
        return allow()


if __name__ == "__main__":
    sys.exit(main())
