"""Refine the legacy shell classifier without treating uncertainty as a write.

Owner: effect diagnostics at the shared pretool boundary.
Allowed imports: standard library and existing shell/HTTP/Git parsers.
Forbidden: execution, credentials, run state.
Callers/tests: claude_pretool_gate; test_claude_command_effect.
Verification: classification and gate tests; no result grants permissions.
"""

from pathlib import Path

from claude_bash_http import curl_effect
from claude_bash_git import git_subcommand
from claude_bash_syntax import command_segments, shell_keyword_command


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
        return "unknown", "interpreter or script effects are not declared by a supported command contract"
    return "unknown", "command or options have no verified effect contract"


def unknown_recovery(reason: str) -> str:
    return (
        f"Tao command effect: unknown. Boundary: {reason}. "
        "This is not proof it changes data. For a lookup, use a supported read-only form or split the unsupported wrapper "
        "into independently verifiable reads; do not request write authority just to run a lookup. "
        "Do not repeat the unchanged command. For an intended write already authorized by the user, "
        "enter its scoped writable route once and retry; no duplicate user approval is needed. "
        "Worktree and native permission boundaries still apply."
    )
