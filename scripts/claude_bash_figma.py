"""Operand roles for the canonical Figma handoff CLI, never arbitrary Python.

Owner: the Figma CLI's closed argument grammar and read operands.
Allowed imports: standard library. Forbidden: execution, run state, policy.
Caller: claude_bash_readonly. Tests: test_claude_bash_figma.
"""
from __future__ import annotations

from pathlib import Path


_CLI = Path(__file__).resolve().parent / "figma-handoff/figma-handoff.py"
_VALIDATOR = _CLI.with_name("figma_validate.py")
_VALUES = frozenset({
    "--url", "--file-key", "--node-id", "--name", "--out", "--token-env",
    "--format", "--scale", "--max-flow-depth", "--timeout", "--max-assets",
})
_FLAGS = frozenset({
    "--no-images", "--include-image-fills", "--export-assets", "--dry-run",
})


def figma_command_effect(
    tokens: list[str], cwd: Path | None,
) -> tuple[str, frozenset[int]] | None:
    """Classify a canonical ``python3 -B`` invocation and its read positions.

    -B prevents imports from writing bytecode into the tool checkout. Only the
    sibling CLI is trusted, as with the runtime's own lifecycle entrypoints.
    Unknown options retain the caller's conservative verdict. Real extraction
    remains mutating: --out (or the cwd default) still needs its usual checks.
    """
    if len(tokens) < 3 or tokens[:2] not in (["python3", "-B"], ["python", "-B"]):
        return None
    source = Path(tokens[2]).expanduser()
    if not source.is_absolute():
        if cwd is None:
            return None
        source = cwd / source
    try:
        source = source.resolve(strict=True)
        if source == _VALIDATOR.resolve(strict=True):
            return ("read_only", frozenset(range(4))) if len(tokens) == 4 else None
        if source != _CLI.resolve(strict=True):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    outputs: set[int] = set()
    dry_run = False
    index = 3
    while index < len(tokens):
        option, separator, value = tokens[index].partition("=")
        if option in _FLAGS and not separator:
            dry_run = dry_run or option == "--dry-run"
            index += 1
            continue
        if option not in _VALUES:
            return None
        value_index = index
        if not separator:
            index += 1
            if index >= len(tokens):
                return None
            value_index = index
            value = tokens[index]
        if not value or value.startswith("--") or value in {";", "&&", "|", ">", ">>", "<"}:
            return None
        if option == "--out":
            outputs.add(value_index)
        index += 1
    reads = frozenset(range(len(tokens))) - (frozenset() if dry_run else outputs)
    return ("read_only" if dry_run else "mutating", reads)
