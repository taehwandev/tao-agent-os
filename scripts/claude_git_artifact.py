"""Exact Git artifact and index-patch shapes; no execution or admission."""

from pathlib import Path

from claude_bash_git import git_command_kind, git_subcommand


def git_diff_artifact_output(tokens: list[str]) -> frozenset[int] | None:
    """Return output-token positions only for an otherwise read-only Git diff.

    The remaining operands name inputs. External differs, configuration overrides
    and ambiguous output forms retain the conservative unknown contract.
    """
    if not tokens or Path(tokens[0]).name != "git":
        return None
    subcommand, arguments = git_subcommand(tokens)
    if subcommand != "diff":
        return None
    start = len(tokens) - len(arguments)
    remaining = list(tokens[:start])
    outputs: set[int] = set()
    index = start
    while index < len(tokens):
        word = tokens[index]
        if word == "--":
            remaining.extend(tokens[index:])
            break
        if word == "--output":
            if index + 1 >= len(tokens) or not tokens[index + 1] or tokens[index + 1].startswith("-"):
                return None
            outputs.add(index + 1)
            index += 2
            continue
        if word.startswith("--output="):
            if not word.partition("=")[2]:
                return None
            outputs.add(index)
        else:
            remaining.append(word)
        index += 1
    if len(outputs) != 1 or git_command_kind(remaining) != "read_only":
        return None
    return frozenset(outputs)


def git_index_patch(tokens: list[str]) -> bool:
    """Recognize only one literal cached three-way patch, never a worktree edit."""
    if not tokens or Path(tokens[0]).name != "git":
        return False
    subcommand, arguments = git_subcommand(tokens)
    return (subcommand == "apply" and arguments[:2] == ["--cached", "--3way"]
            and len(arguments) == 3 and bool(arguments[2])
            and not arguments[2].startswith("-"))
