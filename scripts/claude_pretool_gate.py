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
import re
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from types import ModuleType

try:  # The gate must never fail to load; the import is only used for a message.
    from support.stable_launcher import stable_launcher_path
    from support.global_state import (
        global_state_dir,
        is_host_config_dir,
        is_project_state_dir,
        prefer_git_root,
    )
    from claude_bash_git import git_subcommand, names_unsafe_git_option
    from claude_bash_syntax import past_env_options
    from claude_command_effect import command_effect, unknown_recovery, github_publication
    from claude_worktree_gate import (
        BASH_TOOLS,
        MAIN_CHECKOUT_OVERRIDE_ENV,
        REQUIRE_LINKED_WORKTREE_ENV,
        WORKTREE_POLICY_PATH,
        bash_command,
        bash_command_kind,
        RUNTIME_CONTROL_KIND,
        bash_invocation,
        contains_workflow_start,
        git_common_dir,
        has_unresolvable_expansion,
        path_arguments,
        raw_path_arguments,
        read_only_path_token_indices,
        policy_requires_workflow_entry,
        project_publication_kind,
        ticketed_product_branch_denial,
        worktree_denial,
        worktree_policy,
        CHAINED_START_REMEDY,
        COMPUTED_TEXT,
        NAMED_TARGET,
        AUTHORING_GIT,
        UNREADABLE_SYNTAX,
        WORKFLOW_START_REMEDY,
        WORKFLOW_START_TARGET,
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

    def read_only_path_token_indices(tokens: list[str]) -> "frozenset[int]":
        # A broken install claims no operand is read-only, so every path stays
        # a target and the gate keeps its strictest reading.
        return frozenset()

    def past_env_options(tokens: list[str], index: int, **_kwargs: object) -> "int | None":
        # Without the reader, no `env` form is readable, which keeps the
        # publication hold on and leaves the wrapper judged as it always was.
        return None

    def has_unresolvable_expansion(command: str) -> bool:
        return False

    def contains_workflow_start(tokens: list[str]) -> bool:
        # A broken install recognises no hook, so no refusal claims one was
        # chained and the generic remedy stands.
        return False

    def git_common_dir(root: Path) -> "Path | None":
        return None

    def bash_command_kind(tokens: list[str], syntax_is_simple: bool) -> str:
        return "mutating"

    def command_effect(tokens, simple, kind):
        return kind, ""

    def unknown_recovery(reason, **_kwargs):
        return "Command effect could not be verified."

    RUNTIME_CONTROL_KIND = "runtime_control"

    def worktree_policy(root: Path) -> dict | None:
        return None

    def policy_requires_workflow_entry(root: Path) -> bool:
        # A broken install has read no declaration, so it cannot claim the
        # repository asked for the stricter path.
        return False

    def project_publication_kind(root: Path, tokens: list[str], cwd: Path) -> str:
        return ""

    def ticketed_product_branch_denial(root: Path, target: Path) -> str | None:
        return None

    def worktree_denial(
        root: Path, cause: str = "", named: str = "", *, remedy: str = ""
    ) -> str | None:
        return None

    COMPUTED_TEXT = "computed_text"
    NAMED_TARGET = "named_target"
    AUTHORING_GIT = "authoring_git"
    UNREADABLE_SYNTAX = "unreadable_syntax"
    WORKFLOW_START_TARGET = "workflow_start_target"
    WORKFLOW_START_REMEDY = ""
    CHAINED_START_REMEDY = ""

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


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "ApplyPatch"}
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
# A day, because the window says how long workflow entry and a finished run
# stay good, which does not depend on which runtime is typing. Eight hours left
# Codex stale while Claude ran on the day-long value its own settings file set,
# and the per-runtime variable name meant raising Claude's changed nothing
# there. Either runtime can still narrow or widen it with
# TAO_<RUNTIME>_GATE_MAX_AGE_SECONDS.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
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
# The steps the lifecycle names after finish: "before final report, commit,
# release, or handoff". Deliberately not the ordinary-Git set, which also holds
# `clean`, `reset`, `rm` and unrestricted `rebase`. The separate bounded rebase
# path admits local Git work, then checks resulting inputs before publication.
PUBLICATION_GIT_SUBCOMMANDS = frozenset({"add", "commit", "push", "tag"})
# The only options a fast-forward integration of an attested worktree may
# carry. `--ff-only` is what makes it a reference move rather than a merge;
# the rest only quieten it. Anything else -- `--no-ff`, `-m`, `--squash`, a
# strategy option -- builds a commit nobody reviewed, so it is not this shape.
FAST_FORWARD_MERGE_FLAGS = frozenset({"--ff-only", "-q", "--quiet", "--no-edit"})
# GitHub publication effects share one contract with command classification.
SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".cjs", ".dart", ".go", ".h", ".hpp",
    ".java", ".js", ".jsx", ".kt", ".kts", ".m", ".mjs", ".mm", ".php", ".py",
    ".rb", ".rs", ".sass", ".scss", ".svelte", ".swift", ".ts", ".tsx", ".vue",
}


def runtime_name() -> str:
    runtime = os.environ.get("TAO_PRETOOL_RUNTIME", "claude").strip().lower()
    return runtime if runtime in {"claude", "codex"} else "claude"


def runtime_setting(name: str) -> str:
    return f"TAO_{runtime_name().upper()}_GATE{name}"


def gate_enabled() -> bool:
    """Escape hatch for runtimes that cannot supply a session id."""
    return os.environ.get(runtime_setting(""), "").strip() != "0"


def allow() -> int:
    """Defer to Claude's normal permission flow without changing it."""
    return 0


def _approve(reason: str) -> int:
    """Skip a prompt when the active runtime supports an explicit approval.

    A successful hook with no output is only a deferral. Claude may still ask
    about the Bash command, which turned the worktree policy into an Enter-only
    machine even after the gate itself stopped denying ordinary work. Emit the
    actual ``allow`` decision there only for a simple Git invocation whose
    remaining effects have been classified below; arbitrary Bash keeps its
    normal permission flow.

    Codex 0.154 rejects Claude's ``permissionDecision: allow`` value. A clean
    exit with no output is Codex's successful deferral path, so emitting the
    Claude value there turns an approved command into a hook error and may make
    the agent retry or rediscover the workflow. Denials remain explicit; native
    review requests also defer without Claude-only output in Codex.
    """

    if runtime_name() == "codex":
        return allow()

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


_BLOCK_SESSION: dict[str, str] = {"session_id": ""}


def _learn_block(code: str) -> None:
    """Count this denial as a content-free lesson, after the verdict is final.

    Only the fixed reason code and the session reach the store -- never the
    command, a path or the reason text -- and the recorder rate-limits per
    session and swallows every error, so it cannot change or delay a verdict
    beyond one small file read and at most one write.
    """

    try:
        from agent_block_lessons import record_block

        record_block("pretool_gate", code, session_id=_BLOCK_SESSION["session_id"])
    except Exception:  # noqa: BLE001 - learning never changes the verdict
        pass


def deny(reason: str, code: str = "workflow_entry_missing") -> int:
    """Stop a policy violation without turning it into an operator prompt.

    ``ask`` makes Claude request confirmation for every gated Edit, Write, and
    Bash call.  These failures have deterministic remedies -- enter the
    workflow, move to a permitted worktree, or reduce/justify the edit -- so the
    agent should apply the remedy instead of delegating every decision to the
    operator.

    ``code`` names which denial branch fired, as a fixed slug for the lesson
    store; it never alters the decision printed here.
    """

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        ),
        flush=True,
    )
    _learn_block(code)
    return 0


def ask(reason: str, tokens: list[str] | None = None) -> int:
    """Request native review, without re-asking for deletion authorization.

    A hook cannot observe settled conversational approval. Deletion decisions
    therefore remain with Claude's permission layer, rather than a hook ask
    that overrides that layer on every invocation. Isolation and workflow
    refusals are evaluated separately and remain in force.
    """

    # Codex rejects Claude's `ask` value as well as `allow`. A silent success
    # leaves sandbox/approval decisions with the runtime; it grants no permission.
    if runtime_name() == "codex" or (tokens and _is_git_deletion(tokens)):
        return allow()

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
    raw = os.environ.get(runtime_setting("_MAX_AGE_SECONDS"), "").strip()
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

    The tracked worktree policy counts because it is the one opt-in signal that
    a linked worktree carries. The state directory is written by a run, so a
    fresh worktree has none until it has already complied, and the marker-file
    token depends on the runtime's product name appearing in prose, so an
    ordinary documentation edit can drop it. A repository that declares the
    policy has declared governance in a tracked file, and every worktree of it
    checks that file out.
    """
    if is_host_config_dir(path):
        return False
    if is_project_state_dir(path / STATE_DIR):
        return True
    if (path / WORKTREE_POLICY_PATH).is_file():
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


def finished_evidence_is_fresh(evidence: Path | None) -> bool:
    """Post-finish admission is as fresh as its finish, never its start.

    Preflight mtime is the start time, so a long run finished just now read as
    stale and its commit needed a second lifecycle. The finish time is the
    publication receipt's write, else the registry's completion time.
    """
    if evidence is None:
        return False
    finished = evidence_mtime(evidence.with_name("publication.json"))
    if finished is None:
        finished = _registry_completion_time(evidence)
    return finished is not None and (time.time() - finished) <= max_age_seconds()


def _registry_completion_time(evidence: Path) -> float | None:
    try:
        registry = json.loads((evidence.parents[2] / "run-registry.json").read_text(encoding="utf-8"))
        for run in registry.get("runs") or []:
            if run.get("run_id") == evidence.parent.name and run.get("state") == "completed":
                return datetime.fromisoformat(str(run.get("updated_at"))).timestamp()
    except (OSError, ValueError, AttributeError, TypeError, IndexError):
        return None
    return None


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
            "running a command not verified read-only for this project",
            "retry the command",
        )
    return ("editing files in this project", "retry the edit")


def governed_because(root: Path, cwd_roots: "list[Path] | None") -> str:
    """Say why this project is the one being asked for evidence.

    A command is governed by the project it runs in *and* by every project a
    path in it writes into, and those are usually different projects. Naming
    only the root left the reader to guess which one it was, and the guess that
    costs most is "the environment is blocking me": a reader who believes the
    gate means their own directory concludes the command cannot run at all,
    rather than that a second project needs its own `start`.
    """

    if cwd_roots is None:
        return ""
    if root in cwd_roots:
        return f" `{root}` is where the command runs."
    return (
        f" `{root}` is not where the command runs: a path in this command "
        "writes into it, so that project needs its own workflow entry. Running "
        "the command from somewhere else does not change this; the path does."
    )


def deny_reason(
    root: Path,
    session_id: str = "",
    tool: str = "",
    cwd_roots: "list[Path] | None" = None,
) -> str:
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
    if tool in BASH_TOOLS:
        cause += (
            " The command was not verified read-only; this is not proof of a write. "
            "For HTTP reads use curl -q with GET/HEAD and stdout. For an already "
            "approved write, reuse the user's exact scope in writable workflow entry."
        )
    cause = f"{cause}{governed_because(root, cwd_roots)}"
    return (
        f"Tao Agent OS: run the workflow start hook before {action}. {cause} "
        f"Run `{stable_launcher_path()} start --project "
        f"{root} --rules <TAO_ROOT> --command <route> --request \"<user "
        f"request>\"`, read the route required_docs, then {retry}. Set "
        f"{runtime_setting('_MAX_AGE_SECONDS')} to tune the freshness window."
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


def _run_evidence_reader() -> "ModuleType | None":
    """Import the run-evidence reader on first use, or None on a broken install.

    Reading run evidence pulls in the run registry, the execution capsule and
    the worktree fingerprints: 24.6ms of imports, against 1.0ms of decision, on
    a hook that runs before every Bash, Edit and Write call.  Nothing on the
    allow path asks it a question -- a read-only command is classified from its
    own text -- so it is loaded where it is answered instead of at module load.

    A broken install still has to fail open rather than fail to load, which is
    why the ImportError is answered here with None and not raised.
    """

    try:
        import agent_runtime_session
    except ImportError:  # pragma: no cover - exercised only on a broken install
        return None
    return agent_runtime_session


def session_evidence(root: Path, session_id: str) -> Path | None:
    if not session_id:
        return None
    reader = _run_evidence_reader()
    if reader is None:
        return None
    return reader.resolve_runtime_evidence(
        root,
        {"runtime": runtime_name(), "session_id": session_id},
    )


def finished_session_evidence(root: Path, session_id: str) -> Path | None:
    """Evidence of a run this session finished successfully.

    A run reaches ``completed`` from exactly one place: a ``finish`` that
    passed. So this is not "some old run existed", it is "this session's work
    was attested" -- which is the state the lifecycle puts a session in right
    before it commits.

    A session finishes more than one run in a repository over a day's work, so
    this asks for the latest of them rather than for the only one. Requiring a
    single match let the first publication through and refused every one after
    it, which reads as the gate failing at random. Freshness below still
    decides whether that finish is recent enough to publish on.
    """

    if not session_id:
        return None
    reader = _run_evidence_reader()
    if reader is None:
        return None
    return reader.resolve_runtime_evidence(
        root,
        {"runtime": runtime_name(), "session_id": session_id},
        frozenset({"completed"}),
        latest_of_several=True,
    )


PUBLICATION_LEAVES_THIS_MACHINE = frozenset({"push", "tag"})


def publication_before_finish_reason(root: Path, *, unreadable: bool = False) -> str:
    """Said from both places that can answer a publishing command."""

    if unreadable:
        return (
            f"Tao lifecycle: this session's run in {root} is still open, and "
            "this command hides the program it runs behind a wrapper, so "
            "whether it publishes cannot be read. Next: spell the command "
            "plainly, or record the route's remaining gates, run the review "
            "hook and run finish."
        )
    return (
        f"Tao lifecycle: this session's run in {root} is still open, so no gate "
        "ledger is closed and no review attestation covers what this would "
        "publish. Next: record the route's remaining gates, run the review "
        "hook, then run finish. Publication still requires matching action "
        "authority and unchanged finished inputs."
    )


def publishes_before_finish(tokens: list[str]) -> str:
    """Why this is held while its run is open: `publishes`, `unreadable`, or "".

    Only reached from the active-run branch, so the run has not finished: no
    gate ledger is closed and no review attestation covers what is about to
    leave. A local commit stays out of this set because it can be amended or
    reset, and a task legitimately commits while it works; a push, and the pull
    request opened from it, is what other people start acting on.

    `unreadable` is a wrapper that hides its program. Releasing those meant
    `env -S`, `env -P` and `command` each walked the publication straight out,
    and each was a separate option nobody had enumerated yet.
    """

    return _segment_hold(tokens, 0)


ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# Wrappers that run the command that follows them. `command -v git` is a
# lookup, not a run, and resolves harmlessly: `git` alone has no subcommand.
# A shell given `-c` carries the command inside a string. That string is read
# rather than refused, so the hold stays about publishing: `bash -c "echo ok"`
# publishes nothing and `bash -lc "git push"` does, and only the option
# spelling differed.
SHELL_PROGRAMS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})


def _past_assignments(tokens: list[str], index: int) -> int:
    while index < len(tokens) and ENV_ASSIGNMENT.match(tokens[index]):
        index += 1
    return index


def _past_wrapper_options(tokens: list[str], index: int, name: str) -> "int | None":
    """Step over one wrapper's options, or None for an option it does not model.

    Unknown means unread, not skipped: `time -o out git push` puts a filename
    where the program would be, and guessing past it is how `-P` got missed.
    """

    flags = WRAPPER_FLAGS_BY_NAME.get(name, frozenset())
    values = WRAPPER_VALUES_BY_NAME.get(name, frozenset())
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index].split("=", 1)[0]
        if tokens[index] == "--":
            return index + 1
        if option in values:
            index += 1 if "=" in tokens[index] else 2
            continue
        if option in flags:
            index += 1
            continue
        return None
    return index


def _command_behind_environment(
    tokens: list[str], depth: int = 0
) -> "list[str] | None":
    """The program a prefix or wrapper runs, or None when it cannot be read.

    `strip_env_assignments` refuses a prefix it cannot call inert, which is
    right for the question it answers: `LD_PRELOAD=... cat` must not be
    classified by `cat`, because the assignment changes what `cat` does. This
    asks something narrower -- which program runs -- and there the assignment
    does not matter: the shell executes git either way.

    Stepping over it here therefore changes nothing else. The command
    classifier, `strip_env_assignments` and the main-checkout override, which
    reads the raw prefix, all keep their current meaning, so `add`, `commit`
    and `reset` are judged exactly as before.

    None is the answer for a wrapper whose program is not a token here, and the
    caller holds it rather than releasing it. An earlier version answered `[]`
    for that case, which the caller read as "not a publication" -- the opposite
    of what its own comment claimed -- so `env -S "git push"` went through.
    """

    index = 0
    for _ in range(len(tokens) + 1):
        index = _past_assignments(tokens, index)
        if index >= len(tokens):
            return []
        head = tokens[index]
        name = head if head == "!" else Path(head).name
        if name == "env":
            stepped = past_env_options(tokens, index + 1)
            if stepped is None:
                return None
            index = stepped
            continue
        if name in WRAPPER_FLAGS_BY_NAME:
            stepped = _past_wrapper_options(tokens, index + 1, name)
            if stepped is None:
                return None
            index = stepped
            continue
        if name in OPAQUE_WRAPPERS:
            return None
        return tokens[index:]
    return None


def _shell_payload(tokens: list[str], index: int) -> "tuple[str | None, bool]":
    """The string a shell's `-c` carries, and whether the form was read.

    `-c` is not always its own token: `-lc` says the same thing, and matching
    the exact token let `bash -lc "git push"` past. Anything before the payload
    that is neither an understood option nor the end-of-options marker leaves
    the form unread, because an option taking a value would shift which word
    the payload is.
    """

    saw_option = False
    while index < len(tokens) and tokens[index].startswith("-"):
        token = tokens[index]
        if token == "--":
            return None, True
        saw_option = True
        if not token.startswith("--") and "c" in token[1:]:
            following = index + 1
            return (tokens[following], True) if following < len(tokens) else (None, False)
        index += 1
    # `bash script.sh` runs a script, which is an ordinary program, but an
    # option this did not recognise may have taken the payload's place.
    return None, not saw_option


SHELL_PUNCTUATION_CHARS = ";&|<>"
SUBSTITUTION_MARKERS = ("$(", "`", "<(", ">(")
# Wrappers whose options are modelled, so the command after them is read.
# `!` is the shell's own negation and takes nothing.
WRAPPER_FLAGS_BY_NAME = {
    "!": frozenset(),
    "command": frozenset({"-p", "-v", "-V"}),
    "exec": frozenset({"-c", "-l"}),
    "nohup": frozenset(),
    "setsid": frozenset({"-c", "-f", "-w"}),
    "time": frozenset({"-p", "-a", "-v", "--portability", "--verbose", "--append"}),
}
WRAPPER_VALUES_BY_NAME = {
    "exec": frozenset({"-a"}),
    "time": frozenset({"-o", "-f", "--output", "--format"}),
}
# Wrappers that run another program through arguments this does not model --
# `nice -n 5 cmd`, `timeout 30 cmd`, `xargs cmd` -- so the program behind them
# is held rather than guessed at.
OPAQUE_WRAPPERS = frozenset(
    {
        "chroot", "doas", "ionice", "nice", "script", "stdbuf", "sudo",
        "taskset", "timeout", "unbuffer", "xargs",
    }
)
# Words and brackets that open a construct this does not model. A segment
# starting with one is held rather than read: `(git push)` and
# `if true; then git push; fi` both name git somewhere this was not looking.
SHELL_STRUCTURE_WORDS = frozenset(
    {
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
        "done", "case", "esac", "in", "select", "function", "coproc",
        "{", "}", "(", ")", "[[", "]]",
    }
)


def _substitution_runs(command: str) -> bool:
    """Whether a substitution marker sits where the shell would run it.

    Looking for the marker in the raw text refused `echo '$(git push)'` and
    `echo ok # $(git push)`, neither of which runs anything. Single quotes and
    a comment hide it; double quotes do not, because `"$(git push)"` runs.
    """

    quote = ""
    index = 0
    while index < len(command):
        character = command[index]
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"':
                # Only single quotes hide a substitution; inside double quotes
                # the shell still runs it.
                if character == "\\":
                    index += 1
                elif command.startswith(SUBSTITUTION_MARKERS, index):
                    return True
            index += 1
            continue
        if character in "\'\"":
            quote = character
            index += 1
            continue
        if character == "\\":
            index += 2
            continue
        # `;#` opens a comment as surely as ` #` does.
        if character == "#" and (
            index == 0
            or command[index - 1].isspace()
            or command[index - 1] in SHELL_PUNCTUATION_CHARS
        ):
            return False
        if command.startswith(SUBSTITUTION_MARKERS, index):
            return True
        index += 1
    return False


def _shell_command_parts(command: str, reject_redirections: bool) -> list[str] | None:
    """Split operators before unquoting so literal punctuation stays data."""

    parts: list[str] = []
    current: list[str] = []
    quote = ""
    word_start = True
    index = 0
    while index < len(command):
        char = command[index]
        if not quote and word_start:
            # Only duplicate the standard output streams, never an arbitrary
            # descriptor that may name an already-open file. Keep this within
            # its command so active-run publication detection is unchanged.
            descriptor = re.match(r"[12]?>&[12](?=$|[ \t\n;&|])", command[index:])
            if descriptor:
                index += descriptor.end()
                continue
        if char == "\\" and quote != "'":
            if index + 1 >= len(command):
                return None
            following = command[index + 1]
            if following != "\n":
                current.extend((char, following))
                word_start = False
            index += 2
            continue
        if quote != "'" and command.startswith(SUBSTITUTION_MARKERS, index):
            return None
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
            word_start = False
        elif char == "#" and word_start:
            # A comment ends at the newline; later commands still need checks.
            newline = command.find("\n", index)
            index = len(command) if newline < 0 else newline
            continue
        elif char == "\n" or char in SHELL_PUNCTUATION_CHARS:
            if reject_redirections and char in "<>":
                return None
            if current:
                parts.append("".join(current))
                current = []
            word_start = True
        else:
            current.append(char)
            word_start = char in " \t"
        index += 1
    if quote:
        return None
    if current:
        parts.append("".join(current))
    return parts


def _command_segments(
    command: str, *, reject_redirections: bool = False
) -> "list[list[str]] | None":
    """Return simple commands, rejecting hidden substitutions and bad syntax."""

    parts = _shell_command_parts(command, reject_redirections)
    if parts is None:
        return None
    segments: list[list[str]] = []
    for part in parts:
        if _substitution_runs(part):
            return None
        try:
            tokens = shlex.split(part)
        except ValueError:
            return None
        if tokens:
            segments.append(tokens)
    return segments


def publication_hold(
    command: str,
    depth: int = 0,
    root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """The strongest hold any segment of this command line asks for.

    Running only on a lone simple command let `git push && echo done` past,
    and calling every chain unreadable refused `bash -c "echo hi; echo bye"`.
    Segments answer both: one publishing segment holds the line, and a line
    whose segments all read and none publish is left alone.
    """

    if depth >= 3:
        return "unreadable"
    segments = _command_segments(command)
    if segments is None:
        return "unreadable"
    verdict = ""
    for tokens in segments:
        found = _segment_hold(tokens, depth, root, cwd)
        if found == "publishes":
            return "publishes"
        if found == "unreadable":
            verdict = "unreadable"
    return verdict


def _segment_hold(
    tokens: list[str],
    depth: int,
    root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """One simple command: what it publishes, or that its program is hidden."""

    command = _command_behind_environment(tokens, depth)
    if command is None:
        return "unreadable"
    if not command:
        return ""
    # Checked on what the reader returned, so `! (git push)` is seen as the
    # construct it is rather than as a command called `!`.
    if command[0] in SHELL_STRUCTURE_WORDS or command[0][0] in "({":
        return "unreadable"
    if Path(command[0]).name in SHELL_PROGRAMS:
        payload, readable = _shell_payload(command, 1)
        if not readable:
            return "unreadable"
        # `bash script.sh` runs a script, which is an ordinary program.
        return (
            publication_hold(payload, depth + 1, root, cwd)
            if payload is not None
            else ""
        )
    program = Path(command[0]).name
    if program == "git":
        subcommand, _arguments = git_subcommand(command)
        return "publishes" if subcommand in PUBLICATION_LEAVES_THIS_MACHINE else ""
    if github_publication(command):
        return "publishes"
    if root is not None:
        return project_publication_kind(root, command, cwd or root)
    return ""


def _git_read(root: Path, arguments: list[str]) -> "tuple[int, str] | None":
    """One short read of a repository, or None when it cannot be answered.

    Every caller below treats None and a non-zero status the same way -- the
    integration is not admitted -- so a missing git, a timeout and an
    unreadable administrative directory all fail closed without a branch each.
    """

    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.returncode, result.stdout


def _fast_forward_merge_target(tokens: list[str], base: Path) -> "Path | None":
    """The checkout `git [-C <path>] merge ...` acts on, or None if unreadable.

    Only `-C` is stepped over. `--git-dir`, `--work-tree`, `-c` and
    `--config-env` also choose or reconfigure the repository, and one of them
    can put a program where this admission expects a reference move, so a
    command carrying any of them is not the shape being admitted.
    """

    target = base
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return target if token == "merge" else None
        if token == "-C" and index + 1 < len(tokens):
            raw = Path(tokens[index + 1]).expanduser()
            target = raw if raw.is_absolute() else base / raw
            index += 2
            continue
        return None
    return None


def _names_exact_fast_forward(arguments: list[str]) -> str:
    """The single ref of an exact `--ff-only` merge, or "" for any other shape.

    `--no-ff`, a plain merge, a second positional and an option that runs a
    program all mean the command can bring in bytes no finish attested, so
    each of them leaves the ordinary refusal in place.
    """

    if any(names_unsafe_git_option(argument) for argument in arguments):
        return ""
    flags = [argument for argument in arguments if argument.startswith("-")]
    words = [argument for argument in arguments if not argument.startswith("-")]
    if "--ff-only" not in flags or set(flags) - FAST_FORWARD_MERGE_FLAGS:
        return ""
    if len(words) != 1 or not words[0] or words[0].split() != [words[0]]:
        return ""
    return words[0]


def _registered_worktrees(target: Path) -> list[Path]:
    """The repository's other checkouts, as git itself registers them.

    Asking the target rather than searching the filesystem is what keeps this
    to one repository: a directory that merely looks like a worktree, or one
    belonging to some other project, is never in this list.
    """

    read = _git_read(target, ["worktree", "list", "--porcelain"])
    if read is None or read[0] != 0:
        return []
    paths: list[Path] = []
    for line in read[1].splitlines():
        if not line.startswith("worktree "):
            continue
        try:
            candidate = Path(line[len("worktree ") :]).resolve()
        except OSError:
            continue
        if candidate != target and candidate not in paths:
            paths.append(candidate)
    return paths


def _holds_exactly_the_finished_commit(
    worktree: Path, session_id: str, sha: str
) -> bool:
    """Whether this worktree's finish attested exactly the commit being merged.

    The receipt binds the finished bytes; HEAD and a clean status bind the
    commit to those same bytes. Without both, a worktree edited or advanced
    after its finish would hand that receipt to a commit nobody reviewed.
    """

    evidence = finished_session_evidence(worktree, session_id)
    if not finished_evidence_is_fresh(evidence):
        return False
    from agent_publication_admission import PublicationAdmission

    if not PublicationAdmission.allows(worktree, evidence, "git_write"):
        return False
    head = _git_read(worktree, ["rev-parse", "HEAD"])
    if head is None or head[0] != 0 or head[1].strip() != sha:
        return False
    status = _git_read(
        worktree, ["status", "--porcelain", "--untracked-files=normal"]
    )
    return status is not None and status[0] == 0 and not status[1].strip()


def integrates_finished_worktree(
    root: Path,
    session_id: str,
    tokens: list[str],
    cwd: Path | None = None,
) -> bool:
    """Admit a fast-forward of a finished linked worktree into its repository.

    A goal loop works in `<repo>/.tao/worktrees/<slice>`, runs the whole
    lifecycle there, and then brings the commit home with
    `git -C <repo> merge --ff-only <sha>`. That merge had no admission of its
    own: publication covers `add`, `commit`, `push` and `tag`, and it is
    looked up against the checkout the command names, which never held the
    run. So every iteration opened a second lifecycle in the main checkout to
    fast-forward bytes the first had already tested, reviewed and attested --
    eight tool calls of ceremony for a reference move.

    The admission is the finish that already happened, never a new authority.
    A fast-forward writes no commit and no bytes: the target's HEAD must
    already be an ancestor of the commit, the commit must be exactly some
    registered worktree's HEAD, and that worktree must be clean and unchanged
    since its receipt. Anything else -- a plain `merge`, `--no-ff`, a rebase,
    a second ref, a dirty or advanced worktree, a diverged target, a
    read-route finish -- fails closed and keeps the ordinary refusal.
    """

    if not session_id:
        return False
    subcommand, arguments = git_subcommand(tokens)
    if subcommand != "merge":
        return False
    ref = _names_exact_fast_forward(arguments)
    if not ref:
        return False
    target = _fast_forward_merge_target(tokens, cwd or root)
    if target is None:
        return False
    try:
        target = target.resolve()
    except OSError:
        return False
    resolved = _git_read(target, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if resolved is None or resolved[0] != 0:
        return False
    sha = resolved[1].strip()
    if not sha:
        return False
    # The ancestry is the whole reason this is admissible: a diverged target
    # makes the same command an ordinary merge wearing the flag, which would
    # integrate bytes no finish attested -- and which git refuses anyway.
    ancestry = _git_read(target, ["merge-base", "--is-ancestor", "HEAD", sha])
    if ancestry is None or ancestry[0] != 0:
        return False
    return any(
        _holds_exactly_the_finished_commit(worktree, session_id, sha)
        for worktree in _registered_worktrees(target)
    )


def publishes_finished_work(
    root: Path,
    session_id: str,
    tokens: list[str],
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
    command = _command_behind_environment(tokens, 0)
    if not command:
        return False
    # Integration of a finished worktree is admitted here so that every
    # caller of this function -- the chain reader, the main verdict loop
    # and the reached-into-project check -- inherits one answer.
    if Path(command[0]).name == "git" and git_subcommand(command)[0] == "merge":
        return integrates_finished_worktree(root, session_id, command, cwd)
    if Path(command[0]).name == "git" and git_subcommand(command)[0] == "rebase":
        from agent_rebase_admission import rebase_continuation_shape

        # Only the ordinary invocation: no -c, alternate worktree or git-dir.
        if command != tokens or command[:2] != ["git", "rebase"] or not rebase_continuation_shape(
            root, command[2:], set(protected_branch_names(root) or {"main", "master", "develop"}),
        ):
            return False
        evidence = finished_session_evidence(root, session_id)
        from agent_publication_admission import PublicationAdmission

        return finished_evidence_is_fresh(evidence) and PublicationAdmission.allows(root, evidence, "git_write")
    effect = _publication_effect(root, command, cwd or root)
    if not effect:
        return False
    evidence = finished_session_evidence(root, session_id)
    if not finished_evidence_is_fresh(evidence):
        return False
    from agent_publication_admission import PublicationAdmission

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


def finished_publication_denial(root: Path, session_id: str, command: str, cwd: Path) -> str:
    """Say why a completed run cannot admit this publication, not every reason it might."""

    cause = "the command is not a lone admissible publication; run it without chained writes"
    evidence = finished_session_evidence(root, session_id)
    for segment in _command_segments(command, reject_redirections=True) or []:
        tokens = _command_behind_environment(segment, 0)
        effect = _publication_effect(root, tokens, cwd) if tokens else ""
        if not effect or evidence is None:
            continue
        from agent_publication_admission import PublicationAdmission

        refusal = PublicationAdmission.refusal(root, evidence, effect)
        if refusal.startswith("effect:"):
            granted, needed = refusal.removeprefix("effect:").split("<")
            cause = (
                f"the run was admitted for {granted} and this publication needs {needed}. "
                "When the user's request authorizes push or pull-request creation, start "
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
    segments = _command_segments(command, reject_redirections=True)
    if not segments:
        return False
    # A rebase may change the attested bytes. Never pre-authorize a following
    # push/commit using the receipt captured before that rebase executes.
    if len(segments) != 1 and any(git_subcommand(segment)[0] == "rebase" for segment in segments):
        return False
    published = False
    for segment in segments:
        if publishes_finished_work(root, session_id, segment, cwd):
            published = True
            continue
        legacy_kind = bash_command_kind(segment, True)
        effect, _reason = command_effect(segment, True, legacy_kind)
        if effect != "read_only":
            return False
    return published


def _read_run_mutation_denial(roots: list[Path], session_id: str, kind: str) -> str | None:
    """Honor an active read contract even when isolation waives workflow entry.

    The lifecycle hooks are exempt alongside `start`, because they write run
    evidence rather than the project, and they are how a run records what it
    found, closes, or escalates. Refusing them made this refusal's own remedy
    unreachable: escalating needs `fingerprint` before `start` will accept an
    intent envelope, and ending needs `finish` or `cancel`, so a read-only run
    could neither reach a writable route nor close itself.
    """
    if kind in {"workflow_start", RUNTIME_CONTROL_KIND}:
        return None  # Reaching an authorized route, or ending this one, is the remedy.
    from workflow_effect_policy import route_minimum_effect

    for root in roots:
        evidence = session_evidence(root, session_id)
        if evidence is None:
            continue  # Existing entry policy still decides runs without evidence.
        try:
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            command = str(payload.get("route", {}).get("command") or "")
            explicit = payload.get("execution_mode", {}).get("read_only")
        except (OSError, ValueError, AttributeError, TypeError):
            return "Active run evidence cannot be read; refresh workflow entry before writing."
        if explicit or route_minimum_effect(command) == "read":
            return (
                f"Active route `{command}` is read-only; start an authorized writable "
                "route for an approved write. This call was not verified read-only; "
                "that is not proof it changes data. For HTTP inspection, use explicit "
                "curl -q with GET/HEAD and stdout, without config/output/upload options. "
                "If the user already authorized a write, carry that exact scope into "
                "the writable route rather than asking for the same approval again. "
                "Worktree isolation does not waive the read-only contract."
            )
    return None


def is_run_local_continuation_evidence(project: Path, evidence: Path | None) -> bool:
    reader = _run_evidence_reader()
    if reader is None:
        return False
    return reader.is_run_local_continuation_evidence(project, evidence)


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
    raw = os.environ.get(runtime_setting("_NEW_FILE_BUDGET"), "").strip()
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


def _patch_target_paths(payload: dict, cwd: Path) -> list[Path] | None:
    """Read every patch source and move target; never infer targets from cwd."""
    body = payload.get("tool_input")
    if isinstance(body, dict):
        candidates = [body[key] for key in ("patch", "input") if key in body]
        if len(candidates) != 1:
            return None
        body = candidates[0]
    if not isinstance(body, str):
        return None
    lines = body.strip().splitlines()
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        return None
    targets = []
    prefixes = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")
    for line in lines[1:-1]:
        prefix = next((item for item in prefixes if line.startswith(item)), None)
        if prefix:
            name = line[len(prefix):]
            if not name.strip() or "\x00" in name:
                return None
            target = Path(name)
            targets.append(target if target.is_absolute() else cwd / target)
        elif line.startswith("*** ") and line != "*** End of File":
            return None
    return targets or None


def find_edit_project_root(payload: dict, cwd: Path) -> Path | None:
    """Resolve the project that owns the file being edited, not just the cwd.

    A session's working directory and the file it edits are often different
    projects: this gate let a whole article get rewritten in a writing workspace
    while the cwd sat in another repo, so the writing project's own `start` was
    never required and its edits were recorded against the wrong project. The
    Stop gate then asked the cwd project for a finish, found one, and allowed a
    stop that left the edited project unverified.

    The target path decides. cwd stays as the fallback for tools that report no
    file path -- and only for those. A named target that belongs to no project
    used to fall through to the working directory as well, which judged a file
    by a checkout it is not in: with the shell standing in a protected checkout,
    writing a scratch note under `/tmp` was refused for being *near* that
    repository. Once the last worktree of a session is removed the shell returns
    there, so the session could no longer write anywhere at all.

    An Edit or Write names exactly the one path it changes, so when that path is
    outside every governed project there is nothing here to protect.
    """
    target = write_target_path(payload, cwd)
    if target is not None:
        return find_project_root(target.parent)
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
        f"Tune with {runtime_setting('_NEW_FILE_BUDGET')}."
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


def _ungoverned_project_verdict(cwd: Path, tokens: list[str]) -> int:
    """Answer a call whose target belongs to no governed project.

    Lifted out of `decide` for the block limit. It is its own question:
    everything here is about a command that has left every governed root,
    where the gate keeps only the one thing it alone knows.
    """

    # Not an Tao Agent OS project; never block ordinary editing.
    #
    # `-C <elsewhere>` moves the command's target out of every governed
    # root and landed here, so `git -C /tmp/other branch -D main` from a
    # governed session was silent while the same deletion spelled
    # `--git-dir=/tmp/other/.git` was asked about -- the same act, decided
    # two ways by which flag named the repository. Destroying another
    # repository is not "ordinary editing", so a session working inside a
    # compliant worktree is still asked. Only hazards, and only `ask`: a
    # session that is not in a governed project keeps this gate out of its
    # way entirely.
    session_root = find_project_root(cwd)
    if session_root is not None and worktree_policy_satisfied(session_root):
        hazard = shared_repository_hazard(
            tokens, protected_branch_names(session_root)
        )
        if hazard:
            return ask(
                "This command leaves the worktree to reach another "
                f"repository, and there it {hazard}. Allow it only if that "
                "is what you meant."
            )
    return allow()


def _isolated_checkout_verdict(
    payload: dict,
    tool: str,
    root: Path,
    cwd: Path,
    tokens: list[str] | None = None,
    syntax_is_simple: bool = False,
    governed_roots: "list[Path] | None" = None,
    cwd_roots: "list[Path] | None" = None,
    unknown_reason: str = "",
    effective_cwd: Path | None = None,
) -> int:
    """Answer a call the worktree policy has already cleared.

    Isolation is one question and workflow entry is another: this one asks
    whether the session has entered the workflow, stayed inside its file
    budget, and still holds the evidence its edit will be checkpointed
    against. Lifted out of `decide` for the block limit, and it reads as its
    own question rather than as the tail of the dispatcher.
    """

    session_id = str(payload.get("session_id") or "")
    target = write_target_path(payload, cwd)
    if target is not None:
        for governed in governed_roots or [root]:
            ticket_reason = ticketed_product_branch_denial(governed, target)
            if ticket_reason:
                return deny(ticket_reason, "ticketed_product_branch")
    # Every governed project, for the same reason the mutation and worktree
    # checks already use all of them: a command writing into a second project
    # is governed by that project's workflow entry too, and reading only the
    # first let the project the shell happens to sit in authorize a write
    # anywhere else.
    finish_authorized = False
    for governed in governed_roots or [root]:
        if workflow_entry_allows(governed, session_id):
            # Not behind `syntax_is_simple`: a chain is the shape a
            # publication most often takes, and requiring a lone command let
            # `git push && echo done` through.
            held = (
                publication_hold(
                    bash_command(payload), root=governed, cwd=effective_cwd or cwd
                )
                if tool in BASH_TOOLS
                else ""
            )
            if held:
                return deny(
                    publication_before_finish_reason(
                        governed, unreadable=held == "unreadable"
                    ),
                    "publication_before_finish",
                )
            continue
        if (
            tool in BASH_TOOLS
            and publishes_finished_command(
                governed,
                session_id,
                bash_command(payload),
                effective_cwd or cwd,
            )
        ):
            finish_authorized = True
            continue
        if (
            tool in BASH_TOOLS
            and publication_hold(
                bash_command(payload), root=governed, cwd=effective_cwd or cwd
            )
            and finished_evidence_is_fresh(finished_session_evidence(governed, session_id))
        ):
            return deny(finished_publication_denial(
                governed, session_id, bash_command(payload), effective_cwd or cwd),
                "publication_after_finish_mismatch")
        if unknown_reason:
            after_finish = finished_evidence_is_fresh(finished_session_evidence(governed, session_id))
            return deny(unknown_recovery(unknown_reason, after_finish=after_finish)
                        + governed_because(governed, cwd_roots),
                        "unreadable_command_effect")
        return deny(deny_reason(governed, session_id, tool, cwd_roots))
    if finish_authorized:
        return _approve(
            "This is a publication command that a successful finish "
            "authorized for this session."
        )
    sprawl_reason = sprawl_deny(tool, payload, root, cwd, session_id)
    if sprawl_reason:
        return deny(sprawl_reason, "file_sprawl_budget")
    # A missing adapter module is a broken install, not a policy violation. This
    # gate promises never to fail to load; denying every edit because an import
    # failed breaks that promise and removes the means of repairing the install.
    evidence = session_evidence(root, session_id)
    if evidence is None:
        # The active claim can disappear between the workflow-entry check and
        # the mutation checkpoint. Do not turn that registry race into an
        # uncheckpointed edit.
        return deny(deny_reason(root, session_id, tool))
    if (
        runtime_name() == "claude"
        and tool in EDIT_TOOLS
        and is_run_local_continuation_evidence(root, evidence)
    ):
        adapter = continuation_adapter()
        if adapter is not None:
            continuation_reason = adapter.pre_mutation(
                payload, root=root, cwd=cwd, session_id=session_id
            )
            if continuation_reason:
                return deny(continuation_reason, "continuation_pre_mutation")
    record_edit_activity(root, session_id)
    record_session_project(root, session_id)
    return allow()


def _is_one_of(root: Path, others: "list[Path] | None") -> bool:
    """Whether this is one of those directories, through a symlinked path.

    `/var` and `/private/var` name one directory on this platform, and the
    project root a command resolves to is not always spelled the way the
    governed-root scan spelled it. Comparing the spellings said two names for
    the same checkout were two different projects.
    """

    for other in others or []:
        if root == other:
            return True
        try:
            if root.resolve() == other.resolve():
                return True
        except OSError:
            continue
    return False


def _project_needing_its_own_entry(
    payload: dict,
    tool: str,
    roots: list[Path],
    cwd_roots: "list[Path] | None",
    tokens: list[str] | None,
    *,
    syntax_is_simple: bool,
) -> "Path | None":
    """A project this command writes into that has not had its own ``start``.

    Only projects the command reaches into, never the one it runs in: that one
    is the subject of the verdict being qualified, and re-asking it here would
    answer with the wrong gate.
    """

    session_id = str(payload.get("session_id") or "")
    for candidate in roots:
        if _is_one_of(candidate, cwd_roots):
            continue
        if workflow_entry_allows(candidate, session_id):
            continue
        # A successful finish authorizes the ordinary Git command that
        # publishes it, including into a root the session is not standing in.
        if (
            tool in BASH_TOOLS
            and syntax_is_simple
            and publishes_finished_work(candidate, session_id, tokens or [])
        ):
            continue
        return candidate
    return None


def _worktree_policy_verdict(
    payload: dict,
    tool: str,
    root: Path,
    roots: list[Path],
    tokens: list[str],
    command_cwd: Path,
    worktree_reason: str,
    *,
    syntax_is_simple: bool,
    cwd_roots: "list[Path] | None" = None,
) -> int:
    """Answer a call that a governed root refuses, once one of them does.

    Lifted out of `decide`, which had grown to 199 lines against a 120-line
    limit and was most of one branch. The branch decides one question --
    whether a refusing root leaves the caller anywhere else to work -- and
    reads better as the answer to that question than as the middle of the
    function that dispatches every tool.
    """

    # Reaching a protected checkout from outside it is a different act from
    # standing in one. A session with a worktree that names the protected
    # checkout has somewhere else to be, and the remedy is deterministic --
    # work there -- which is what `deny` is for. A session whose shell is
    # simply in the protected checkout has nowhere else to run, so a refusal
    # leaves no route and the operator is asked instead.
    cwd_root = find_project_root(command_cwd) if tool in BASH_TOOLS else None
    denying = [candidate for candidate in roots if worktree_denial(candidate)]
    # Standing in the protected checkout, and only there. Two other shapes
    # keep their refusal because each has a deterministic remedy, which is
    # what `deny` is for:
    #
    #   - reaching in from somewhere else. A session with a worktree that
    #     names the protected checkout has another place to work, and the
    #     remedy is to work there.
    #   - a linked worktree sitting on a protected branch. The remedy is to
    #     leave the branch, and the checkout is not the problem.
    standing_in_the_protected_checkout = (
        bool(denying)
        and all(candidate == cwd_root for candidate in denying)
        and (cwd_root / ".git").is_dir()
    )
    if standing_in_the_protected_checkout and _requests_main_checkout_override(tokens):
        return ask(
            "The command explicitly requests the documented main-checkout exception. "
            "Defer that exceptional write to the runtime's native permission review.",
            tokens=tokens,
        )
    # Text the shell computes is text this gate cannot read, and a prompt
    # cannot describe what it would do. `eval $(echo rm -rf build)` parses
    # as a simple command line and says nothing about the command that
    # actually runs, so it keeps the refusal rather than becoming a question
    # the operator has no way to answer.
    readable = tool in BASH_TOOLS and not has_unresolvable_expansion(
        bash_command(payload)
    )
    landing = (
        protected_checkout_verdict(tokens, protected_branch_names(root))
        if readable
        and syntax_is_simple
        and standing_in_the_protected_checkout
        else ""
    )
    # A landing that lets the command through speaks for the protected
    # checkout, and only for it. The same command can write into a second
    # governed project, and that project's workflow entry is a separate
    # question this branch skipped entirely: the operator was asked about the
    # checkout the command does not touch, while the project it does touch was
    # never asked. Run from that project's own directory the identical write
    # was denied, so where the shell sat decided the verdict.
    if landing in {"allow", "defer", "ask"}:
        unentered = _project_needing_its_own_entry(
            payload, tool, roots, cwd_roots, tokens, syntax_is_simple=syntax_is_simple
        )
        if unentered is not None:
            return deny(
                deny_reason(
                    unentered,
                    str(payload.get("session_id") or ""),
                    tool,
                    cwd_roots,
                )
            )
    # The routine tier answers for the checkout, and publishing asks a second
    # question it never asked: whether anything has attested the work. Reaching
    # here with an open run means no gate ledger is closed, exactly as in the
    # isolated-checkout branch, which never saw this command because this
    # function returns first.
    held = (
        publication_hold(bash_command(payload), root=root, cwd=command_cwd)
        if landing in {"allow", "defer", "ask"} and tool in BASH_TOOLS
        else ""
    )
    if held:
        session_id = str(payload.get("session_id") or "")
        open_run = next(
            (
                candidate
                for candidate in (roots or [root])
                if workflow_entry_allows(candidate, session_id)
            ),
            None,
        )
        if open_run is not None:
            return deny(
                publication_before_finish_reason(
                    open_run, unreadable=held == "unreadable"
                ),
                "publication_before_finish",
            )
    if landing == "allow":
        return _approve(
            "This authors nothing in the protected checkout: it moves or "
            "removes references that already exist."
        )
    if landing == "defer":
        return allow()
    if landing == "ask":
        return ask(
            "This writes a commit into the protected checkout, discards "
            "uncommitted work there, or reaches shared state. Allow it only "
            "if that is what you meant.",
            tokens=tokens,
        )
    return deny(
        _worktree_reason_naming_its_cause(
            roots,
            worktree_reason,
            is_bash=tool in BASH_TOOLS,
            standing_in_the_protected_checkout=standing_in_the_protected_checkout,
            readable=readable,
            syntax_is_simple=syntax_is_simple,
            payload=payload,
            tokens=tokens,
            command_cwd=command_cwd,
        ),
        "worktree_isolation",
    )


def _requests_main_checkout_override(tokens: list[str]) -> bool:
    """Recognize the exact documented override only in the assignment prefix."""

    expected = f"{MAIN_CHECKOUT_OVERRIDE_ENV}=1"
    for token in tokens:
        if "=" not in token or token.startswith("-"):
            return False
        if token == expected:
            return True
    return False


def _protected_path_named(
    payload: dict, tokens: list[str], cwd: Path, root: Path
) -> str:
    """The path this command names inside `root`, or "" when none can be shown.

    An edit names its target outright. A Bash line names it among its arguments,
    and the one that matters is the one the gate found inside the protected
    checkout -- not necessarily the operand a reader would call the target, since
    a path is read wherever it appears, a `sed` expression included. Reporting
    the path the gate actually acted on is what makes the two distinguishable.

    Only the denial path calls this, so the second pass over the arguments costs
    nothing on any call that is allowed.
    """

    target = write_target_path(payload, cwd)
    if target is not None:
        return str(target)
    source_indices = read_only_path_token_indices(tokens)
    # The command word is dropped. `path_arguments` reads a bare word as a
    # possible relative target, which is right for finding roots -- `sed x note`
    # may create `note` -- but the word in slot zero is the program being run.
    # Keeping it made `python3 scripts/x.py` report `<checkout>/python3`, a file
    # that does not exist, as the path putting the command in the checkout.
    candidates = [
        token
        for index, token in enumerate(tokens)
        if index and index not in source_indices
    ]
    # The first owned candidate, in the order the roots were discovered in. No
    # preference is applied among them: a rule that favoured a spelling with a
    # separator picked the `s/a/b/` out of `sed -i s/a/b/ note.md` over the file
    # being written, which is the confusion this sentence exists to end. What
    # the gate matched first is what put the command here, and the sentence
    # around it already says a path is read wherever it appears.
    for path in path_arguments(candidates):
        absolute = path if path.is_absolute() else cwd / path
        try:
            owner = _owning_project(absolute)
        except UnresolvableTarget:
            continue
        if owner == root:
            return str(absolute)
    return ""


def _worktree_reason_naming_its_cause(
    roots: list[Path],
    fallback: str | None,
    *,
    is_bash: bool,
    standing_in_the_protected_checkout: bool,
    readable: bool,
    syntax_is_simple: bool,
    payload: dict,
    tokens: list[str],
    command_cwd: Path,
) -> str:
    """Rebuild the refusal so it says which of its four conditions fired.

    All four end here and every one of them printed the same sentence, whose
    remedy -- go work in a linked worktree -- only fits the last two. A reader
    already standing in a worktree, refused because their line was a pipeline,
    read that remedy, concluded the gate had blocked something else, and went
    looking for the cause in the wrong place. Twice, in one session, by the
    agent maintaining this file.

    The verdict does not move. Only the sentence that explains it does.
    """

    if is_bash and not syntax_is_simple and "\n" in bash_command(payload) and "<<" in bash_command(payload):
        return (
            f"Tao worktree gate: command syntax unresolved for {', '.join(str(root) for root in roots)}. "
            "Multiline heredoc input is unsupported by the command parser. "
            "This is not evidence of a write into the named repository. "
            "Next: save the literal input with the file-edit tool inside the authorized task scope, "
            "then run the command with `< input-file` from the explicit task directory. "
            "Keep the existing run and authority; changing worktrees or requesting broader permission "
            "does not resolve this syntax limitation."
        )
    if is_bash and not syntax_is_simple:
        cause = UNREADABLE_SYNTAX
    elif is_bash and not readable:
        cause = COMPUTED_TEXT
    elif is_bash and standing_in_the_protected_checkout:
        cause = AUTHORING_GIT
    else:
        # An Edit or a Write, or a Bash command reaching in from outside: in
        # every one of them the target path is what put this here.
        cause = NAMED_TARGET
    # A line that chained a workflow start with something else is refused for
    # the chaining, and the remedy for that is to unchain it. Sending the
    # reader to a worktree instead was advice about a different problem, and
    # the one session that followed it spent three more calls before it found
    # the semicolon.
    remedy = (
        CHAINED_START_REMEDY
        if cause == UNREADABLE_SYNTAX and contains_workflow_start(tokens)
        else ""
    )
    reason = next(
        (
            refusal
            for refusal in (
                worktree_denial(
                    root,
                    cause,
                    _protected_path_named(payload, tokens, command_cwd, root)
                    if cause == NAMED_TARGET
                    else "",
                    remedy=remedy,
                )
                for root in roots
            )
            if refusal
        ),
        None,
    )
    # The policy can only have loosened between the two reads -- an override set
    # mid-command, say -- and a refusal with no reason left to give is still a
    # refusal, so the original stands.
    return reason or (fallback or "")


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


# Writing new content into the working tree is the one thing the protected
# checkout is protected from. These author it; everything else Git does there
# moves or removes what already exists.
AUTHORING_GIT_SUBCOMMANDS = frozenset(
    {"add", "am", "apply", "cherry-pick", "commit", "mv", "rebase", "revert", "rm"}
)


# In the protected checkout these either write a new commit or throw away
# uncommitted work there. Neither is authoring in the sense the refusal covers,
# but both are a decision worth one question. `switch` is absent on purpose:
# git refuses to change branches over uncommitted changes, so it cannot lose
# them, and it is how you move around a checkout at all. Two members of this
# set have a spelling that only unstages; `unstages_only` names it, because
# the question is about losing work and unstaging loses none.
COMMITTING_OR_DISCARDING_SUBCOMMANDS = frozenset(
    {"checkout", "clean", "merge", "pull", "reset", "restore", "stash"}
)
# Reference maintenance: moving or removing things that already exist, without
# touching the working tree. These are what a task's last step is made of, so
# they are approved outright -- and the list is positive, so a subcommand
# nobody has read still asks.
ROUTINE_PROTECTED_SUBCOMMANDS = frozenset(
    {"branch", "config", "fetch", "gc", "push", "remote", "switch", "tag", "worktree"}
)


def unstages_only(subcommand: str, arguments: list[str]) -> bool:
    """True for the two spellings of "take these paths back out of the index".

    Unstaging is the one member of `COMMITTING_OR_DISCARDING_SUBCOMMANDS` that
    cannot lose anything: the files keep their contents on disk, no ref moves,
    and in the protected checkout it cannot even lead anywhere, because `git
    commit` is refused there. Reading it as a discard put a prompt in front of
    tidying a single stray index entry.

    Only the long option spellings are read. `-S` is `--staged`, but a short
    flag that this function does not recognise falls through to the question,
    which is the direction a misreading should fail in.
    """

    flags = {argument.split("=", 1)[0] for argument in arguments}
    if subcommand == "reset":
        # The pathspec is what makes a reset index-only. Given one, Git refuses
        # `--hard` and leaves HEAD where it is whatever commit is named, so the
        # separator -- not the absence of a commit -- is the thing to look for.
        # Requiring it explicitly also keeps a branch name from being read as a
        # path.
        if "--" not in arguments or arguments[-1] == "--":
            return False
        return not flags & {"--hard", "--merge", "--keep"}
    if subcommand == "restore":
        return "--staged" in flags and "--worktree" not in flags
    return False


def _is_git_deletion(tokens: list[str]) -> bool:
    """Recognize deletion forms only; native permissions still decide access."""
    if not tokens or Path(tokens[0]).name != "git":
        return False
    if any(arg.split("=", 1)[0] in {"--git-dir", "--work-tree", "--config-env", "-c"} for arg in tokens[1:]):
        return False  # Repository/configuration overrides need their own review.
    subcommand, arguments = git_subcommand(tokens)
    if any(names_unsafe_git_option(arg) for arg in arguments):
        return False
    flags = {arg.split("=", 1)[0] for arg in arguments if arg.startswith("--")}
    short = {c for arg in arguments if arg.startswith("-") and not arg.startswith("--") for c in arg[1:]}
    words = [arg for arg in arguments if not arg.startswith("-")]
    first = words[0] if words else ""
    if subcommand in {"branch", "tag"}:
        return bool(short & ({"d", "D"} if subcommand == "branch" else {"d"}) or "--delete" in flags)
    if subcommand == "push":
        return "d" in short or "--delete" in flags or any(word.startswith(":") for word in words[1:])
    if subcommand in {"remote", "worktree"}:
        return first in ({"remove", "rm"} if subcommand == "remote" else {"remove", "prune"})
    if subcommand == "stash":
        return first in {"drop", "clear"}
    if subcommand in {"update-ref", "replace"}:
        return "d" in short or "--delete" in flags
    return subcommand in {"clean", "prune"} or (subcommand == "reflog" and first in {"delete", "expire"}) or (subcommand == "gc" and "--prune" in flags)


def protected_checkout_verdict(
    tokens: list[str], protected: frozenset[str] | None = None
) -> str:
    """`allow`, `ask`, or `""` for a Git command aimed at the protected checkout.

    The policy is that new work is authored in a linked worktree and the
    original is left alone, so authoring is what the refusal is for. It was
    written the other way round -- a short list of permitted commands, refusing
    everything else -- and the list was never going to be complete. First it
    missed `merge` and `pull`, so work done in a worktree had no way home. Then
    it missed `branch -D`, so deleting two merged branches meant creating a
    throwaway worktree to delete them from, which is ceremony standing in for a
    decision the operator had already made.

    Naming what is refused instead makes the boundary answer for cases nobody
    listed. Authoring is refused outright, because the remedy is deterministic:
    do it in a worktree.

    Everything else was then put to the operator as a decision, on the belief
    that Claude's prompt carries "don't ask again" so a routine one would cost
    a single answer. It does not: a hook's `ask` offers yes or no, every time.
    So tidying up a merged branch here asked on the last step of every task,
    forever -- which is the machine that only takes Enter, rebuilt one tier
    down.

    The asking tier is therefore the same one a worktree uses: a shared-state
    hazard, plus the commands that create a commit or throw away uncommitted
    work in this checkout. Ordinary reference maintenance -- deleting a merged
    branch, removing a tag, tidying a remote, pruning a worktree -- is approved
    outright, exactly as it is inside a worktree.

    Returns `defer` for what belongs to Claude's own permission flow rather
    than to this gate, `""` for a refusal, and covers anything that is not Git
    at all.
    """

    if not tokens:
        return ""
    if Path(tokens[0]).name == "gh":
        # `gh` talks to GitHub and writes nothing into this working tree, so it
        # is not this gate's business either way -- the same answer it gets
        # inside a worktree.
        return "defer"
    if Path(tokens[0]).name != "git":
        # A test runner, a build, a package manager, the project's own
        # maintenance tooling: a question rather than a refusal.
        #
        # Refusing them read as "authoring", and for a build or a test that is
        # fair -- the remedy is deterministic, do it in a worktree. But the same
        # wall stood in front of commands with no such remedy. `vibeguard
        # update` writes per-checkout state a worktree run cannot refresh here,
        # so there was no route at all, only a hand-run command, and seven
        # ordinary runners sat behind it too.
        #
        # And a question this gate does not answer, because Claude already
        # answers it. A hook's `ask` overrides the permission rules, so asking
        # here re-asked about commands the operator had already allowed once and
        # for all: `vibeguard`, `npm test` and `pytest` all had standing allow
        # rules and started prompting every time. Turning a dead end into a
        # prompt is only an improvement when there was no prompt before.
        #
        # Deferring keeps both halves. A command with a standing rule runs
        # silently again; one without still reaches the operator, through the
        # layer whose answers persist. This gate keeps only what it alone
        # knows -- authoring here, and the shared refs below.
        #
        # The caller keeps two refusals in front of this: a command whose text
        # cannot be read stays denied, because nothing downstream can describe
        # it either, and an Edit or Write naming a path here never reaches this
        # function at all.
        return "defer"
    subcommand, arguments = git_subcommand(tokens)
    if subcommand is None:
        # An option this gate cannot read hides which subcommand runs. That is
        # the dangerous case, and a question is the safe answer to it -- the
        # same fail-closed reading the hazard check uses.
        return "ask"
    if not subcommand or subcommand in AUTHORING_GIT_SUBCOMMANDS:
        return ""
    if any(names_unsafe_git_option(argument) for argument in arguments):
        # A subcommand that only reads still writes when handed `--output`, and
        # runs a program when handed `--ext-diff` or `--textconv`. Naming the
        # refusal by subcommand alone missed that: `git diff --output=<a path
        # in the protected checkout>` authors a file there under a verb that
        # looks like inspection.
        return ""
    flags = {argument.split("=", 1)[0] for argument in arguments}
    if subcommand in {"merge", "pull"} and "--ff-only" in flags:
        return "allow"
    if subcommand == "merge" and not flags & {"--abort", "--quit"}:
        # Integration belongs in this checkout. This hook cannot see the
        # user's merge authorization, so do not override Claude's native
        # permission decision with a new ask on every invocation.
        return "defer"
    if subcommand in COMMITTING_OR_DISCARDING_SUBCOMMANDS:
        return "allow" if unstages_only(subcommand, arguments) else "ask"
    if shared_repository_hazard(tokens, protected):
        return "ask"
    # Approve only what has been read and found routine. Defaulting the other
    # way was the mistake: it handed an outright approval -- which bypasses
    # Claude's permission flow entirely -- to every subcommand nobody had
    # thought about, and several of those rewrite this working tree.
    # `sparse-checkout` removes files from it, `checkout-index` and `read-tree`
    # overwrite them, `bisect` checks out other commits, `symbolic-ref` moves
    # HEAD without moving the index, `replace` changes what a commit resolves
    # to for the whole repository. None of them is authoring, so none was
    # refused, and none was named, so all were approved.
    #
    # Everywhere else in this gate the unknown case asks. This is the same
    # rule, applied where it was skipped.
    return "allow" if subcommand in ROUTINE_PROTECTED_SUBCOMMANDS else "ask"


def _ordinary_git_invocation(tokens: list[str]) -> bool:
    subcommand, _arguments = git_subcommand(tokens)
    return subcommand in ORDINARY_GIT_SUBCOMMANDS


def _declared_project_root() -> Path | None:
    """The project the runtime says this session belongs to."""

    declared = os.environ.get(
        "CLAUDE_PROJECT_DIR" if runtime_name() == "claude" else "CODEX_PROJECT_DIR",
        "",
    ).strip()
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

    The same reader now answers for the other operands a command's own text
    proves it only reads: `gh pr create --body-file <path>` and the Tao
    installer's `--target` under `--dry-run` or `--check`. Both were read as
    writing into the project they named, so writing a PR body inside the
    worktree being published, and checking another project's hooks without
    touching them, were each refused as a write.
    """

    source_indices = read_only_path_token_indices(tokens)
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
        while not _target_is_present(candidate) and candidate != candidate.parent:
            candidate = candidate.parent
    except (OSError, ValueError) as error:
        raise UnresolvableTarget(str(path)[:64]) from error
    return find_project_root(candidate)


def _target_is_present(candidate: Path) -> bool:
    """Whether this path is there, refusing to guess when asking is an error.

    `Path.exists` answers False both for "not there" and for "the filesystem
    would not say", and the two mean opposite things here. A component longer
    than the filesystem accepts therefore read as an ordinary absent file, the
    walk above stepped up to its parent, and the refusal this reader exists to
    surface became a confident claim about where the command writes. Which of
    the two it is depended on the interpreter as well: `exists` used to let the
    null-byte and over-long spellings through, and each release that catches
    one more of them silently removes a check here. `os.lstat` reports absence
    and refusal apart, so neither reading is left to the caller's version.
    """

    try:
        os.lstat(candidate)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError) as error:
        raise UnresolvableTarget(str(candidate)[:64]) from error
    return True



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


def names_a_protected_branch(words: list[str], protected: frozenset[str] | None) -> bool:
    """Whether this command's targets include a branch the repository protects.

    Fails closed twice over: an unreadable policy (`None`) and a command that
    names no branch at all are both answered "yes". Deleting without saying
    what, or without knowing what is protected, is exactly when a question is
    worth asking.

    A refspec may arrive as `topic`, `:topic` or `heads/topic`; all three name
    the same branch, and matching only the first spelling would let the other
    two through.
    """

    if protected is None or not words:
        return True
    for word in words:
        candidate = word.split(":")[-1].strip()
        if not candidate:
            continue
        for prefix in ("refs/heads/", "heads/"):
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
        if candidate in protected:
            return True
    return False


def protected_branch_names(root: Path) -> frozenset[str] | None:
    """The branches this project protects, or `None` when that cannot be read."""

    policy = worktree_policy(root)
    if not policy:
        return None
    names = policy.get("protected_branches")
    if not isinstance(names, list):
        return None
    return frozenset(str(name) for name in names)


def _shared_history_hazard(
    subcommand: str,
    arguments: list[str],
    flags: set[str],
    short_flags: set[str],
    words: list[str],
    first: str,
) -> str:
    """Why this command deserves a question about state every worktree shares.

    The other half of the list asks about this working tree -- a branch
    deleted, a push, a hard reset, a checkout over local edits. These reach
    further: refs, reflogs, objects, remotes and config that every worktree
    on the repository reads. Split for the block limit, along the line the
    list already divides on.
    """

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
    if subcommand == "worktree" and flags & {"-f", "--force"}:
        # Only the forced forms. Git refuses to remove a worktree holding
        # modified or untracked files, and refuses to add one over a path it
        # already registers; the plain forms therefore cannot lose anything,
        # and asking about them put a prompt on the step that closes every
        # task, on top of a check git was already making. `--force` is what
        # overrides both refusals.
        return "forces past git's own refusal to overwrite or drop a worktree"
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


def shared_repository_hazard(
    tokens: list[str], protected: frozenset[str] | None = None
) -> str:
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
            # Which branch decides, not which flag. A squash merge leaves the
            # topic branch looking unmerged to `-d`, so `-D` is the ordinary way
            # to clean it up -- and asking about every one of those put a prompt
            # on the last step of every task. What must not go quietly is the
            # branch this repository names as protected.
            if names_a_protected_branch(words, protected):
                return "deletes or overwrites a branch this repository protects"
    if subcommand == "push":
        if "f" in short_flags or flags & {"--force", "--force-with-lease", "--mirror"}:
            return "rewrites or deletes a published branch"
        deleting = "--delete" in flags or "d" in short_flags
        # `git push origin :main` deletes main too: a refspec with an empty
        # source pushes nothing onto the target. It carries no flag, so a check
        # that looked only at `--delete` let the older spelling through.
        colon_deletes = [word for word in words[1:] if word.startswith(":")]
        if deleting or colon_deletes:
            # `git push <remote> --delete <branch>`: the first word is the
            # remote, so the branches are what follow it.
            if names_a_protected_branch(colon_deletes or words[1:], protected):
                return "deletes a published branch this repository protects"
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
    return _shared_history_hazard(
        subcommand, arguments, flags, short_flags, words, first
    )


class _CallScope(NamedTuple):
    """What this call is, and which projects it touches.

    `bash_kind` is empty for an Edit or a Write, which have no command line.
    `roots` is every governed project the call reaches, `cwd_roots` only the
    ones it runs in; keeping them apart is what lets a verdict say whether a
    project is in it because the shell is there or because a path put it there.
    """

    bash_kind: str
    tokens: list[str]
    syntax_is_simple: bool
    command_cwd: Path
    effective_cwd: Path
    roots: "list[Path]"
    cwd_roots: "list[Path]"
    unknown_reason: str = ""

    @property
    def root(self) -> "Path | None":
        return self.roots[0] if self.roots else None


def _call_scope(payload: dict, tool: str, cwd: Path) -> _CallScope:
    """Read the call once, so every verdict below reads the same answer."""

    if tool == "ApplyPatch":
        targets = _patch_target_paths(payload, cwd)
        if targets is not None:
            roots = list(dict.fromkeys(
                root for target in targets
                if (root := find_project_root(target.parent)) is not None
            ))
            return _CallScope("", [], True, cwd, cwd, roots, list(roots))
    if tool not in BASH_TOOLS:
        # An Edit or a Write names one path and is judged by where that path
        # is: it cannot run somewhere other than the shell's directory, and its
        # shape cannot be unreadable.
        root = find_edit_project_root(payload, cwd)
        found = [root] if root is not None else []
        return _CallScope("", [], True, cwd, cwd, found, list(found))
    effective_cwd, tokens, syntax_is_simple = bash_invocation(payload, cwd)
    command_cwd = _git_effective_cwd(tokens, effective_cwd)
    kind, detail = command_effect(tokens, syntax_is_simple, bash_command_kind(tokens, syntax_is_simple))
    roots = bash_governed_roots(tokens, command_cwd, command=bash_command(payload))
    return _CallScope(
        kind,
        tokens,
        syntax_is_simple,
        command_cwd,
        effective_cwd,
        roots,
        [
            found
            for found in (find_project_root(command_cwd), find_project_root(cwd))
            if found is not None
        ],
        detail if kind == "unknown" else "",
    )


def _start_option_values(tokens: list[str], option: str) -> list[str]:
    values = []
    for index, token in enumerate(tokens):
        if token == option:
            values.append(tokens[index + 1] if index + 1 < len(tokens) else "")
        elif token.startswith(option + "="):
            values.append(token.partition("=")[2])
    return values


def _administrative_workflow_start(tokens: list[str]) -> bool:
    """Admit lifecycle metadata for Git administration, never a source edit.

    The caller already classified the complete command as a workflow start.
    Ambiguous/duplicate route options do not receive this narrow exception.
    """
    routes = _start_option_values(tokens, "--command")
    return len(routes) == 1 and routes[0] in {
        "cleanup", "commit", "git_commit", "pr", "pull-request"
    }


def _read_only_workflow_start(tokens: list[str]) -> bool:
    """Admit a whole-run read-only claim: it writes only its own run evidence.

    A read-floor route or an explicit `--read-only` claim, with no declared or
    approved effect above `read`. The run's own read contract then refuses any
    project write, so the protected checkout gains no writer.
    """
    from workflow_effect_policy import route_minimum_effect

    routes = _start_option_values(tokens, "--command")
    if len(routes) != 1:
        return False
    for option in ("--requested-effect", "--approved-effect"):
        if any(value != "read" for value in _start_option_values(tokens, option)):
            return False
    return "--read-only" in tokens or route_minimum_effect(routes[0]) == "read"


def _workflow_start_verdict(
    tokens: list[str],
    effective_cwd: Path,
    worktree_reason: str | None,
) -> int:
    """Answer a workflow start by the policy of the project it would claim.

    The start hook claims only the project it names, and the denial that sends
    a session here instructs it to run start in the linked worktree. Judging
    that start by every governed root kept the protected launch checkout in the
    verdict, so the gate denied its own remedy. The named target's policy is
    the whole question.

    Its refusal carries a start-shaped remedy rather than the location advice
    the other verdicts use: what binds a run is `--project`, and no amount of
    moving the shell changes that.
    """

    target_root = workflow_start_target_root(tokens, effective_cwd)
    if target_root is None:
        return deny(worktree_reason, "workflow_start_worktree") if worktree_reason else allow()
    if _administrative_workflow_start(tokens) or _read_only_workflow_start(tokens):
        # Cleanup/publication needs a run in the checkout it administers. The
        # route still validates user authority, and later commands still pass
        # ordinary isolation, effect, and publication-before-finish checks.
        return allow()
    reason = worktree_denial(
        target_root,
        WORKFLOW_START_TARGET,
        remedy=WORKFLOW_START_REMEDY,
    )
    if reason and _requests_main_checkout_override(tokens):
        return ask(
            "The workflow start explicitly requests the documented "
            "main-checkout exception. Defer it to the runtime's native "
            "permission review.",
            tokens=tokens,
        )
    return deny(reason, "workflow_start_worktree") if reason else allow()


def decide(payload: dict) -> int:
    if not gate_enabled():
        return allow()
    _BLOCK_SESSION["session_id"] = str(payload.get("session_id") or "")
    tool = payload.get("tool_name")
    if tool not in GATED_TOOLS:
        return allow()
    cwd_raw = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(cwd_raw).resolve()
    except OSError:
        return allow()
    scope = _call_scope(payload, tool, cwd)
    bash_kind = scope.bash_kind
    tokens = scope.tokens
    syntax_is_simple = scope.syntax_is_simple
    command_cwd = scope.command_cwd
    effective_cwd = scope.effective_cwd
    roots = scope.roots
    cwd_roots = scope.cwd_roots
    root = scope.root
    if root is None:
        return _ungoverned_project_verdict(cwd, tokens)
    if tool in BASH_TOOLS and bash_kind == "read_only":
        return allow()
    read_denial = _read_run_mutation_denial(
        roots, str(payload.get("session_id") or ""), bash_kind
    )
    if read_denial:
        return deny(
            unknown_recovery(scope.unknown_reason) if scope.unknown_reason else read_denial,
            "unreadable_command_effect" if scope.unknown_reason else "read_only_run_mutation",
        )
    if tool in BASH_TOOLS and bash_kind in {"bootstrap", RUNTIME_CONTROL_KIND}:
        # The hazard list is consulted here too. Nothing Git classifies as
        # bootstrap is destructive today -- `fetch` and `worktree add` are the
        # whole set -- so this changes no verdict now. It is the ordering that
        # matters: approving first and checking second means the day one more
        # subcommand becomes bootstrap, it is approved without ever being read.
        if (
            syntax_is_simple
            and tokens
            and Path(tokens[0]).name == "git"
            and worktree_policy_satisfied(root)
            and _ordinary_git_invocation(tokens)
            and not shared_repository_hazard(tokens, protected_branch_names(root))
        ):
            return _approve(
                "This is an ordinary Git command inside the isolated linked worktree."
            )
        if (
            syntax_is_simple
            and tokens
            and git_subcommand(tokens)[0] in {"branch", "remote"}
            and any(worktree_denial(found) for found in roots)
            and protected_checkout_verdict(tokens, protected_branch_names(root)) == "allow"
        ):
            # Self-protecting ref cleanup: keep the protected checkout's
            # existing outright approval rather than demoting it to a prompt.
            return _approve("This is routine reference maintenance in the protected checkout.")
        return allow()
    # Every governed project, not just the first: a session inside a linked
    # worktree satisfies its own policy while naming the protected checkout it
    # was branched from, and taking the first answer let that through.
    worktree_reason = next(
        (reason for reason in map(worktree_denial, roots) if reason), None
    )
    if tool in BASH_TOOLS and bash_kind == "workflow_start":
        return _workflow_start_verdict(tokens, effective_cwd, worktree_reason)
    if worktree_reason:
        if scope.unknown_reason:
            worktree_reason = f"{unknown_recovery(scope.unknown_reason)} {worktree_reason}"
        return _worktree_policy_verdict(
            payload,
            tool,
            root,
            roots,
            tokens,
            command_cwd,
            worktree_reason,
            syntax_is_simple=syntax_is_simple,
            cwd_roots=cwd_roots,
        )
    if worktree_policy_satisfied(root) and not policy_requires_workflow_entry(root):
        hazard = shared_repository_hazard(tokens, protected_branch_names(root))
        if hazard:
            return ask(
                "This worktree isolates ordinary file edits, but this Git command "
                f"{hazard}. Allow it only if that is what you meant.",
                tokens=tokens,
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
    # Deletion deferral must still reach required workflow validation below.
    # Other shared-state hazards retain their existing permission request.
    if worktree_policy_satisfied(root):
        hazard = shared_repository_hazard(tokens, protected_branch_names(root))
        if hazard and not _is_git_deletion(tokens):
            return ask(
                "This worktree isolates ordinary file edits, but this Git command "
                f"{hazard}. Allow it only if that is what you meant."
            )
    return _isolated_checkout_verdict(
        payload, tool, root, cwd, tokens, syntax_is_simple, roots, cwd_roots,
        scope.unknown_reason, effective_cwd,
    )


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
