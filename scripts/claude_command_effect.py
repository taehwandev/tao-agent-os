"""Refine the legacy shell classifier without treating uncertainty as a write.

Owner: effect diagnostics at the shared pretool boundary.
Allowed imports: standard library and existing shell/HTTP/Git parsers.
Forbidden: execution, credentials, run state.
Callers/tests: claude_pretool_gate; test_claude_command_effect.
Verification: classification and gate tests; no result grants permissions.
"""

from pathlib import Path
import re

from claude_bash_http import curl_effect
from claude_bash_git import git_subcommand
from claude_bash_syntax import command_segments, shell_keyword_command

INTERPRETER_REASON = "interpreter or script effects are not declared by a supported command contract"


def github_publication(tokens: list[str]) -> bool:
    """One action contract for pre-finish holds and post-finish admission.

    This describes effects, never user intent or approval. Unknown API targets,
    deletion, merging and credential operations are not publication continuations.
    """
    if not tokens or Path(tokens[0]).name != "gh":
        return False
    if tuple(tokens[1:3]) in {("pr", "create"), ("release", "create"),
                              ("release", "upload")}:
        return True
    if tokens[1:2] != ["api"]:
        return False
    endpoint = None
    method = None
    body = False
    valued = {"-X", "--method", "-f", "--raw-field", "-F", "--field",
              "--input", "--jq", "-q", "--template", "-t"}
    switches = {"--silent", "--include", "-i", "--verbose"}
    index = 2
    while index < len(tokens):
        word = tokens[index]
        flag, equal, value = word.partition("=")
        if flag in valued:
            if not equal:
                index += 1
                if index >= len(tokens):
                    return False
                value = tokens[index]
            if not value:
                return False
            if flag in {"-X", "--method"}:
                if method is not None:
                    return False
                method = value
            elif flag in {"-f", "--raw-field", "-F", "--field", "--input"}:
                body = True
        elif word in switches:
            pass
        elif word.startswith("-") or endpoint is not None:
            return False
        else:
            endpoint = word
        index += 1
    if (method or ("POST" if body else "GET")) != "POST":
        return False
    return bool(re.fullmatch(
        r"/?repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/"
        r"(?:releases|actions/runs/[0-9]+/(?:pending_deployments|rerun|rerun-failed-jobs))",
        endpoint or "",
    ))


def command_effect(tokens: list[str], simple: bool, legacy_kind: str) -> tuple[str, str]:
    """Return an effect and content-free explanation; keep control kinds intact.

    The legacy API remains conservative for integrations that only understand
    read_only/mutating. Only the gate consumes this explicit unknown state.
    Never echo operands: headers, URLs and shell arguments can contain secrets.
    """
    if legacy_kind != "mutating":
        return legacy_kind, ""
    if any(token in {">", ">>", ">|", "&>", "&>>"} for token in tokens):
        return "mutating", "shell output redirection"
    if not simple and tokens:
        from claude_bash_readonly import simple_command_kind

        segments = command_segments(tokens)
        if segments:
            effects = [command_effect(part, True, simple_command_kind(part))
                       for segment in segments if (part := shell_keyword_command(segment))]
            for kind in ("mutating", "unknown"):
                for effect in effects:
                    if effect[0] == kind:
                        return effect
    if not simple or not tokens:
        return "unknown", "shell composition or executable substitution could not be verified"
    executable = Path(tokens[0]).name
    if github_publication(tokens):
        return "mutating", "GitHub publication command"
    if executable in {"rm", "mv", "cp", "touch", "mkdir", "rmdir", "tee", "install", "chmod", "chown"}:
        return "mutating", "filesystem-changing command"
    if executable == "curl":
        return curl_effect(tokens[1:])
    if executable == "git":
        subcommand, _ = git_subcommand(tokens)
        # Listing forms already returned above. Recognizing a mutation only
        # selects the existing authority checks; it does not approve execution.
        if subcommand in {"add", "commit", "push", "merge", "rebase", "reset", "restore", "cherry-pick", "revert", "rm", "mv", "clean", "switch", "checkout", "branch"}:
            return "mutating", "Git state-changing command"
    if executable in {"python", "python3", "python3.14", "node", "bash", "sh", "zsh"}:
        return "unknown", INTERPRETER_REASON
    return "unknown", "command or options have no verified effect contract"


def unknown_recovery(reason: str) -> str:
    # A project script that publishes (a pull-request helper, say) is exactly
    # this case, and its fix is a declaration, not another workflow run.
    declaration = (
        " If this is a project script that publishes, such as one that creates a pull "
        "request, the project can declare its argv prefix under publication_commands in "
        ".agents/shared/worktree-policy.json so a finished run admits it."
        if reason == INTERPRETER_REASON else ""
    )
    return (
        f"Tao command effect: unknown. Boundary: {reason}. "
        "This is not proof it changes data. For a lookup, use a supported read-only form or split the unsupported wrapper "
        "into independently verifiable reads; do not request write authority just to run a lookup. "
        "Do not repeat the unchanged command. If this session already finished the same "
        "authorized publication, correct the declared command form and continue without "
        "another workflow start. Otherwise enter its scoped writable route once; no "
        "duplicate user approval is needed. "
        "Worktree and native permission boundaries still apply." + declaration
    )
