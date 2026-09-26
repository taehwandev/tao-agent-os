"""Whether a `python -m py_compile|compileall` line writes only where it runs.

Both modules write `__pycache__/*.pyc` next to every source they compile, so
calling them read-only let a session in one checkout write bytecode into
another project with no workflow run. Syntax-checking the project the command
runs in stays read-only; this module decides only whether every path the
command visibly names stays inside that project or the OS temp directory.

Owner: the path contract of the two compile-check CLIs. It denies nothing: a
line it cannot prove local is `mutating`, and the target project's ordinary
rules decide from there.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_syntax import (
    PROJECT_MARKERS,
    UNRESOLVED_PATH_CHARS,
    resolve_target,
    scratch_write_target,
)

COMPILE_CHECK_MODULES = frozenset({"py_compile", "compileall"})

# compileall's switches, and the options that take a value. Values that name a
# directory are checked like operands even when compileall only records them
# (`-d`, `-s`, `-p`) or limits by them (`-e`): a path the line shows is judged.
_COMPILEALL_SWITCHES = frozenset("lfqb")
_COMPILEALL_PATH_VALUES = frozenset({"-d", "-s", "-p", "-e"})
_COMPILEALL_OTHER_VALUES = frozenset({"-r", "-x", "-j", "-o", "--workers", "--invalidation-mode"})
_COMPILEALL_LONG_SWITCHES = frozenset({"--hardlink-dupes", "--help"})
_PY_COMPILE_SWITCHES = frozenset({"-q", "--quiet", "--help", "-h"})


def compile_check_kind(module: str, arguments: list[str], cwd: "Path | None") -> str:
    """`read_only` when every named path stays in cwd's project or temp."""

    paths = _named_paths(module, arguments)
    if paths is None:
        return "mutating"
    # No operand: compileall compiles `sys.path` (the interpreter's own
    # directories, skipping the current one) and py_compile compiles nothing.
    # Neither names a project, so this keeps the verdict it always had.
    return "read_only" if all(_local(path, cwd) for path in paths) else "mutating"


def _named_paths(module: str, arguments: list[str]) -> "list[str] | None":
    """Every path the command names, or None when one cannot be seen."""

    paths: list[str] = []
    index = 0
    operands_only = False
    while index < len(arguments):
        word = arguments[index]
        index += 1
        if operands_only or not word.startswith("-"):
            paths.append(word)
            continue
        if word == "--":
            operands_only = True
            continue
        if word == "-":
            # The file names come from stdin, which the line does not show.
            return None
        if module == "py_compile":
            if word not in _PY_COMPILE_SWITCHES:
                return None
            continue
        name, equal, value = word.partition("=")
        if name.startswith("--"):
            if name in _COMPILEALL_LONG_SWITCHES and not equal:
                continue
            if name not in _COMPILEALL_OTHER_VALUES:
                return None
            if not equal:
                if index >= len(arguments):
                    return None
                index += 1
            continue
        flag, attached = word[:2], word[2:]
        if flag in _COMPILEALL_PATH_VALUES | _COMPILEALL_OTHER_VALUES:
            if not attached:
                if index >= len(arguments):
                    return None
                attached = arguments[index]
                index += 1
            if flag in _COMPILEALL_PATH_VALUES:
                paths.append(attached)
            continue
        # `-i <list>` takes the sources from a file or stdin, which the line
        # does not show; any other unknown option fails closed the same way.
        if not set(word[1:]) <= _COMPILEALL_SWITCHES:
            return None
    return paths


def _local(raw: str, cwd: "Path | None") -> bool:
    if scratch_write_target(raw, cwd):
        return True
    if cwd is None or not raw or set(raw) & UNRESOLVED_PATH_CHARS:
        return False
    try:
        target = resolve_target(cwd / raw)
        here = resolve_target(cwd)
    except (OSError, RuntimeError):
        return False
    if target is None or here is None:
        return False
    home = _project_of(here)
    return home is not None and _project_of(target) == home


def _project_of(path: Path) -> "Path | None":
    """The repository holding `path`: its Git root, else its marked root."""

    chain = (path, *path.parents)
    try:
        for directory in chain:
            marker = directory / ".git"
            if marker.exists() or marker.is_symlink():
                return directory
        for directory in chain:
            if any((directory / name).exists() for name in PROJECT_MARKERS):
                return directory
    except OSError:
        return None
    return None
