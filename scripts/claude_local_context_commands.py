"""Classify trusted user-local context commands, without granting project writes."""

from __future__ import annotations


def local_context_kind(alias: str, arguments: list[str]) -> str | None:
    """Called only after the executable's canonical identity has been checked.

    Storage implementations own input validation. Unknown options and surplus
    operands must not inherit the lifecycle exemption of a known operation.
    """
    if alias == "project-memory":
        operations = {
            "capture": ({"--source", "--review-on", "--scope", "--replaces"}, set(), 0),
            "retire": (set(), set(), 1),
            "approve": ({"--digest"}, set(), 1),
            "recall": ({"--scope"}, set(), 0),
        }
    elif alias == "agent-mailbox":
        operations = {
            "send": ({"--rules", "--evidence", "--to", "--sender", "--kind", "--ttl-seconds"}, {"--json"}, 0),
            "receive": ({"--runtime", "--limit"}, {"--json"}, 0),
            "status": ({"--runtime"}, {"--json"}, 0),
        }
    else:
        return None
    operation, operands, index = "", 0, 0
    while index < len(arguments):
        word = arguments[index]
        flag, equal, value = word.partition("=")
        valued, switches, _ = operations.get(operation, (set(), set(), 0))
        if flag == "--project" or flag in valued:
            if not equal:
                index += 1
                if index >= len(arguments):
                    return None
                value = arguments[index]
            if not value or value.startswith("--"):
                return None
        elif word in switches:
            pass
        elif not operation and word in operations:
            operation = word
        elif operation and not word.startswith("-"):
            operands += 1
        else:
            return None
        index += 1
    if not operation or operands != operations[operation][2]:
        return None
    return "read_only" if operation in {"recall", "status"} else "runtime_control"
