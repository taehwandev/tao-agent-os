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
    from claude_bash_git import git_subcommand
    import claude_pretool_publication as _publication
    import claude_pretool_finished_admission as _admission
    import claude_pretool_worktree_integration as _integration
    from claude_pretool_git_hazards import shared_repository_hazard
    from claude_pretool_protected_checkout import (
        is_git_deletion as _is_git_deletion,
        protected_checkout_verdict,
    )
    from claude_command_effect import command_effect, unknown_recovery
    from claude_scratch_checkout import throwaway_checkout, writes_only_scratch_files
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
    # Empty on a sound install. On a broken one it holds the failure's type
    # name, and every gated call warns and records it: the stubs below keep
    # work moving, but they also switch worktree policy off, which nobody
    # would otherwise notice.
    _BROKEN_INSTALL = ""
except ImportError as _import_failure:  # pragma: no cover - exercised only on a broken install
    _BROKEN_INSTALL = type(_import_failure).__name__
    # Without the publication reader nothing is held or admitted, which is
    # what the stubs below already answered for every Git command.
    _publication = _admission = _integration = None

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

    def has_unresolvable_expansion(command: str) -> bool:
        return False

    def contains_workflow_start(tokens: list[str]) -> bool:
        # A broken install recognises no hook, so no refusal claims one was
        # chained and the generic remedy stands.
        return False

    def git_common_dir(root: Path) -> "Path | None":
        return None

    def bash_command_kind(tokens: list[str], syntax_is_simple: bool, cwd: Path | None = None) -> str:
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

    # With `git_subcommand` stubbed to read no subcommand, the hazard module
    # answered "nothing to report" for every command; these say the same.
    def _is_git_deletion(tokens: list[str]) -> bool:
        return False

    def protected_checkout_verdict(tokens: list[str], protected: "frozenset[str] | None" = None) -> str:
        return "defer" if tokens and Path(tokens[0]).name != "git" else ""

    def shared_repository_hazard(tokens: list[str], protected: "frozenset[str] | None" = None) -> str:
        return ""

    # A broken install releases no checkout: every governed root stays one.
    def throwaway_checkout(root: Path) -> bool:
        return False

    def writes_only_scratch_files(command: str, root: Path, cwd: Path) -> bool:
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
    """Defer to Claude's normal permission flow without changing it.

    Silent unless an internal error left a warning for this call, which then
    travels alone: a warning never turns the deferral into an approval.
    """
    return _emit(None)


# Warnings this call owes the agent, emitted with whatever verdict it reaches.
_PENDING_WARNINGS: list[str] = []
_EXCEPTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _emit(decision: "dict | None") -> int:
    """Print one hook answer: an optional decision plus any pending warning.

    Every verdict goes through here so that a warning can never become a
    second JSON document on stdout. Claude shows ``systemMessage`` to the user
    and ``additionalContext`` to the model; Codex rejects Claude-only output,
    so there the warning goes to stderr and the verdict keeps its Codex shape.
    """

    warning = " ".join(dict.fromkeys(_PENDING_WARNINGS))
    _PENDING_WARNINGS.clear()
    codex = runtime_name() == "codex"
    if warning and codex:
        print(warning, file=sys.stderr, flush=True)
    output: dict = {}
    if decision is not None:
        output["hookSpecificOutput"] = {"hookEventName": "PreToolUse", **decision}
    if warning and not codex:
        output.setdefault("hookSpecificOutput", {"hookEventName": "PreToolUse"})[
            "additionalContext"
        ] = warning
        output["systemMessage"] = warning
    if output:
        print(json.dumps(output), flush=True)
    return 0


def _gate_internal_error(error: "BaseException | str", outcome: str) -> None:
    """Record a failure of the gate itself, and owe the agent a warning.

    The gate still fails open -- its own bugs must not stop work -- but no
    longer silently: the warning names the exception type and nothing else,
    and the lesson carries only the fixed reason code, never the message, a
    path or the command. The recorder's per-session window keeps a repeating
    crash to one record.
    """

    name = error if isinstance(error, str) else type(error).__name__
    if not _EXCEPTION_NAME.fullmatch(name):
        name = "Exception"
    _PENDING_WARNINGS.append(
        f"Tao gate hit an internal error ({name}); {outcome}; "
        "this was recorded for repair."
    )
    _learn_block("gate_internal_error")


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
    return _emit({"permissionDecision": "allow", "permissionDecisionReason": reason})


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

    _emit({"permissionDecision": "deny", "permissionDecisionReason": reason})
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
    return _emit({"permissionDecision": "ask", "permissionDecisionReason": reason})


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


# What a command publishes while its run is open, and what a finished run
# admits afterwards, live in claude_pretool_publication,
# claude_pretool_finished_admission and claude_pretool_worktree_integration.
# These keep the gate's names, and hand those modules this one's run-evidence
# lookups, so that a caller
# patching `finished_session_evidence` here still decides the admission.
def _finished_runs() -> "_integration.FinishedRuns":
    return _integration.FinishedRuns(
        evidence=lambda root, session_id: finished_session_evidence(root, session_id),
        is_fresh=lambda evidence: finished_evidence_is_fresh(evidence),
        protected_branches=lambda root: protected_branch_names(root),
    )


def publication_before_finish_reason(root: Path, *, unreadable: bool = False) -> str:
    if _publication is None:
        return f"Tao lifecycle: this session's run in {root} is still open."
    return _publication.publication_before_finish_reason(root, unreadable=unreadable)


def publishes_before_finish(tokens: list[str]) -> str:
    return _publication.publishes_before_finish(tokens) if _publication else ""


def publication_hold(
    command: str,
    depth: int = 0,
    root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    if _publication is None:
        return ""
    return _publication.publication_hold(command, depth, root, cwd)


def integrates_finished_worktree(
    root: Path, session_id: str, tokens: list[str], cwd: Path | None = None
) -> bool:
    if _publication is None:
        return False
    return _integration.integrates_finished_worktree(
        root, session_id, tokens, _finished_runs(), cwd
    )


def publishes_finished_work(
    root: Path, session_id: str, tokens: list[str], cwd: Path | None = None
) -> bool:
    if _publication is None:
        return False
    return _admission.publishes_finished_work(
        root, session_id, tokens, _finished_runs(), cwd
    )


def finished_publication_denial(root: Path, session_id: str, command: str, cwd: Path) -> str:
    if _publication is None:
        return "Tao lifecycle: a completed run exists for this session, but it cannot admit this publication."
    return _admission.finished_publication_denial(
        root, session_id, command, cwd, _finished_runs()
    )


def publishes_finished_command(root: Path, session_id: str, command: str, cwd: Path) -> bool:
    if _publication is None:
        return False
    return _admission.publishes_finished_command(
        root, session_id, command, cwd, _finished_runs()
    )


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
    except Exception as error:  # noqa: BLE001 - the count never blocks on its own bug
        _gate_internal_error(error, "the new-file count was skipped")
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
        publishes = tool in BASH_TOOLS and publication_hold(
            bash_command(payload), root=governed, cwd=effective_cwd or cwd
        ) == "publishes"
        return deny(deny_reason(governed, session_id, tool, cwd_roots) + (
            " This command publishes: when the user's request authorizes it, start "
            "that run with --approved-effect external_write so its finish admits it."
            if publishes else ""
        ))
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
    if not _subagent_call(payload):
        record_edit_activity(root, session_id)
        record_session_project(root, session_id)
    return allow()


def _subagent_call(payload: dict) -> bool:
    """Whether a subagent, not the session's main thread, made this call.

    Claude Code sends a subagent's tool calls with the parent's session id and
    adds ``agent_id``. Indexing them under that session made the parent's Stop
    hook treat each worker's worktree as its own edited project: it marked the
    workers' runs interrupted and demanded a finish for them. A worker closes
    its own run; the parent's index holds only what the parent edited.
    """

    agent_id = payload.get("agent_id")
    return isinstance(agent_id, str) and bool(agent_id.strip())


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


def protected_branch_names(root: Path) -> frozenset[str] | None:
    """The branches this project protects, or `None` when that cannot be read."""

    policy = worktree_policy(root)
    if not policy:
        return None
    names = policy.get("protected_branches")
    if not isinstance(names, list):
        return None
    return frozenset(str(name) for name in names)


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
            roots = _governed_only(list(dict.fromkeys(
                root for target in targets
                if (root := find_project_root(target.parent)) is not None
            )))
            return _CallScope("", [], True, cwd, cwd, roots, list(roots))
    if tool not in BASH_TOOLS:
        # An Edit or a Write names one path and is judged by where that path
        # is: it cannot run somewhere other than the shell's directory, and its
        # shape cannot be unreadable.
        root = find_edit_project_root(payload, cwd)
        found = _governed_only([root] if root is not None else [])
        return _CallScope("", [], True, cwd, cwd, found, list(found))
    effective_cwd, tokens, syntax_is_simple = bash_invocation(payload, cwd)
    command_cwd = _git_effective_cwd(tokens, effective_cwd)
    kind, detail = command_effect(tokens, syntax_is_simple, bash_command_kind(tokens, syntax_is_simple, effective_cwd))
    command = bash_command(payload)
    roots = _governed_only(
        bash_governed_roots(tokens, command_cwd, command=command), command, effective_cwd
    )
    return _CallScope(
        kind,
        tokens,
        syntax_is_simple,
        command_cwd,
        effective_cwd,
        roots,
        _governed_only(
            [
                found
                for found in (find_project_root(command_cwd), find_project_root(cwd))
                if found is not None
            ],
            command,
            effective_cwd,
        ),
        detail if kind == "unknown" else "",
    )


def _governed_only(
    roots: "list[Path]", command: "str | None" = None, cwd: "Path | None" = None
) -> "list[Path]":
    """Drop throwaway temp checkouts the call only writes files in.

    A worktree parked under the OS temp directory for a measurement is
    scratch: editing, deleting or removing it lands in no project anyone
    keeps, and demanding a lifecycle there is friction with nothing to
    protect. A Bash command keeps the checkout governed unless every segment
    only touches files or disposes of that worktree -- a commit, a ref write
    or a publication reaches the repository it shares.
    """

    return [
        root
        for root in roots
        if not (
            throwaway_checkout(root)
            and (
                command is None
                or writes_only_scratch_files(command, root, cwd or root)
            )
        )
    ]


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
    """Answer one tool call; the gate's own failure allows, visibly.

    A bug in the gate is not a policy violation, so it never blocks work. It
    used to allow silently, which hid every crash; now the agent is told, the
    user sees it, and one content-free lesson is recorded for repair.
    """

    _PENDING_WARNINGS.clear()
    try:
        return _decide(payload)
    except Exception as error:  # noqa: BLE001 - the gate fails open, never silently
        _gate_internal_error(error, "the command was allowed")
        return allow()


def _decide(payload: dict) -> int:
    if not gate_enabled():
        return allow()
    _BLOCK_SESSION["session_id"] = str(payload.get("session_id") or "")
    tool = payload.get("tool_name")
    if tool not in GATED_TOOLS:
        return allow()
    if _BROKEN_INSTALL:
        _gate_internal_error(
            _BROKEN_INSTALL, "worktree policy is off until the install is repaired"
        )
    # An unresolvable cwd raises into `decide`, which allows it visibly.
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
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
    except Exception as error:  # noqa: BLE001 - an unreadable payload fails open, visibly
        _gate_internal_error(error, "the command was allowed")
        return allow()
    return decide(payload)


if __name__ == "__main__":
    sys.exit(main())
