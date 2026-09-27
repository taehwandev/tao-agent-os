"""Argument effects for trusted Tao discovery entrypoints.

Owner: discovery argv validation; caller proves executable identity.
Allowed imports: none. Forbidden: execution, filesystem writes, runtime state.
Callers/tests: claude_bash_readonly; test_claude_discovery_command.
"""

from __future__ import annotations


def discovery_command_kind(alias: str, arguments: list[str]) -> str | None:
    """Admit documented lookup arguments only, never future write options."""
    if alias not in {"project-discover", "agent-entry"}:
        return None
    valued = {"--request", "--cwd", "--registry", "--search-root", "--max-depth", "--format"}
    if alias == "agent-entry":
        valued |= {"--runtime", "--command"}
    switches = {"--help", "-h", "--include-default-search-roots", "--no-default-search-roots"}
    index = 0
    while index < len(arguments):
        name, equals, value = arguments[index].partition("=")
        if name in switches and not equals:
            index += 1
            continue
        if name not in valued:
            return "mutating"
        if not equals:
            index += 1
            if index >= len(arguments) or arguments[index].startswith("-"):
                return "mutating"
            value = arguments[index]
        if not value:
            return "mutating"
        index += 1
    return "read_only"
