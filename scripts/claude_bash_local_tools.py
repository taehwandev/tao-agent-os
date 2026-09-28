"""Exact read-only grammars for local developer tools the core list leaves out.

Owner: command-shape recognition for Node test/typecheck runs and pure lookups
(npm registry and dependency-tree queries, graphify graph queries,
`defaults read`, and the macOS process probes footprint, top and sample),
consulted by claude_bash_readonly.
Allowed imports: standard library, claude_bash_compile_check, claude_bash_syntax.
Forbidden: execution, run state, project policy.
Callers/tests: claude_bash_readonly; test_claude_bash_local_tools.
Verification: every grammar has an admitted case and a refused neighbour.

A Node test run executes repository code the way `python3 -m pytest` does, and
is bounded the same way: by naming the script -- `test`, never an arbitrary
`npm run <script>` -- or the type checker's no-output mode, and by keeping
every path the line visibly names inside the project it runs in, or in temp.
A lookup is admitted only for the subcommands that report and never write.
Anything else returns None, and the caller keeps its fail-closed default.
"""

from __future__ import annotations

from pathlib import Path

from claude_bash_compile_check import runner_target_local
from claude_bash_syntax import scratch_write_target

# `npm test` and its aliases; `npm run test` names the same script. Before
# `--`, npm itself parses every option (`--prefix` moves the project), so only
# the output-volume switches are stepped over there.
NPM_TEST_SCRIPTS = frozenset({"test", "t", "tst"})
NPM_RUN_SCRIPT = frozenset({"run", "run-script", "rum", "urn"})
NPM_QUIET_SWITCHES = frozenset({"--silent", "-s", "--quiet", "-q"})
NPX_PROMPT_SWITCHES = frozenset({"--yes", "-y", "--no-install"})
# `tsc --noEmit` checks types and writes nothing. Every other option may emit
# (`--outDir`, `--declaration`), write a build record (`--incremental`,
# `--generateTrace`) or create a config (`--init`), so it is not modelled.
TSC_SWITCHES = frozenset({"--noEmit", "--pretty", "--skipLibCheck", "--strict", "--noErrorTruncation"})
TSC_PATH_OPTIONS = frozenset({"-p", "--project"})
# Pure npm lookups. Their only writes are npm's own cache and log, and the two
# options that move those are refused.
NPM_LOOKUPS = frozenset({"view", "info", "show", "v", "whoami", "ls", "list", "la", "ll"})
NPM_LOCATION_OPTIONS = frozenset({"--cache", "--logs-dir"})
GRAPHIFY_LOOKUPS = frozenset({"query", "path", "explain"})
GRAPHIFY_SWITCHES = frozenset({"--dfs"})
GRAPHIFY_VALUE_OPTIONS = frozenset({"--context", "--budget", "--graph"})
DEFAULTS_READS = frozenset({"read", "read-type"})
FOOTPRINT_OUTPUT_OPTIONS = frozenset({"-j", "--json"})
SAMPLE_SWITCHES = frozenset({"-wait", "-mayDie", "-fullPaths"})
SAMPLE_OUTPUT_OPTIONS = frozenset({"-f", "-file"})


def node_test_kind(command: list[str], cwd: Path | None) -> str | None:
    """`read_only` for a local `npm test` or `tsc --noEmit`, None otherwise."""

    if not command:
        return None
    name = Path(command[0]).name
    if name == "npm":
        paths = _npm_test_paths(command[1:])
    elif name in {"npx", "tsc"}:
        arguments = command[1:]
        if name == "npx":
            while arguments and arguments[0] in NPX_PROMPT_SWITCHES:
                arguments = arguments[1:]
            if not arguments or arguments[0] != "tsc":
                return None
            arguments = arguments[1:]
        paths = _tsc_paths(arguments)
    else:
        return None
    if paths is None:
        return None
    # Without the directory the run starts in, its project cannot be named.
    if cwd is None:
        return "mutating"
    return "read_only" if all(runner_target_local(path, cwd) for path in paths) else "mutating"


def _npm_test_paths(arguments: list[str]) -> list[str] | None:
    """Every word `npm test` hands its script that could name a path."""

    if arguments and arguments[0] in NPM_RUN_SCRIPT:
        arguments = arguments[1:]
        if not arguments or arguments[0] != "test":
            return None
    elif not arguments or arguments[0] not in NPM_TEST_SCRIPTS:
        return None
    paths: list[str] = []
    for index, word in enumerate(arguments[1:], start=1):
        if word == "--":
            # The script receives the rest verbatim; a value spelled
            # `--flag=value` or `-xvalue` is judged like an operand.
            for passed in arguments[index + 1:]:
                if passed.startswith("--"):
                    passed = passed.partition("=")[2]
                elif passed.startswith("-"):
                    passed = passed[2:]
                if passed:
                    paths.append(passed)
            return paths
        if word.startswith("-"):
            if word not in NPM_QUIET_SWITCHES:
                return None
            continue
        paths.append(word)
    return paths


def _tsc_paths(arguments: list[str]) -> list[str] | None:
    """The project and file operands of a `tsc --noEmit` line."""

    if "--noEmit" not in arguments:
        return None
    paths: list[str] = []
    index = 0
    while index < len(arguments):
        word = arguments[index]
        index += 1
        if word in TSC_SWITCHES:
            continue
        if word in TSC_PATH_OPTIONS:
            if index >= len(arguments):
                return None
            paths.append(arguments[index])
            index += 1
            continue
        # `--noEmit false` turns emission back on; any other option is unmodelled.
        if word.startswith("-") or word in {"true", "false"}:
            return None
        paths.append(word)
    return paths


def lookup_command_kind(command: list[str], cwd: Path | None) -> str | None:
    """`read_only` for one exact lookup grammar, None otherwise."""

    if not command or command[0] != Path(command[0]).name:
        return None
    name, arguments = command[0], command[1:]
    if name == "npm":
        admitted = bool(arguments) and arguments[0] in NPM_LOOKUPS and not any(
            word.partition("=")[0] in NPM_LOCATION_OPTIONS for word in arguments
        )
    elif name == "graphify":
        admitted = bool(arguments) and arguments[0] in GRAPHIFY_LOOKUPS and _graphify_options(arguments[1:])
    elif name == "defaults":
        if arguments[:1] == ["-currentHost"]:
            arguments = arguments[1:]
        elif arguments[:1] == ["-host"]:
            arguments = arguments[2:]
        admitted = bool(arguments) and arguments[0] in DEFAULTS_READS
    elif name == "footprint":
        admitted = _outputs_scratch(arguments, FOOTPRINT_OUTPUT_OPTIONS, cwd)
    elif name == "top":
        admitted = _top_logging(arguments)
    elif name == "sample":
        admitted = _sample_arguments(arguments, cwd)
    else:
        return None
    return "read_only" if admitted else None


def _graphify_options(arguments: list[str]) -> bool:
    index = 0
    while index < len(arguments):
        word = arguments[index]
        index += 1
        flag, equal, _value = word.partition("=")
        if flag in GRAPHIFY_VALUE_OPTIONS:
            if not equal:
                index += 1
        elif word.startswith("-") and word not in GRAPHIFY_SWITCHES:
            return False
    return index <= len(arguments)


def _outputs_scratch(arguments: list[str], output_options: frozenset[str], cwd: Path | None) -> bool:
    """Every output option names a temp path; other options only report."""

    for index, word in enumerate(arguments):
        flag, equal, value = word.partition("=")
        if flag not in output_options:
            continue
        if not equal:
            value = arguments[index + 1] if index + 1 < len(arguments) else ""
        if not scratch_write_target(value, cwd):
            return False
    return True


def _top_logging(arguments: list[str]) -> bool:
    """`top -l <n>`: logging mode samples n times and exits, never interactive."""

    for index, word in enumerate(arguments):
        if word == "-l":
            count = arguments[index + 1] if index + 1 < len(arguments) else ""
        elif word.startswith("-l"):
            count = word[2:]
        else:
            continue
        return count.isdigit() and int(count) > 0
    return False


def _sample_arguments(arguments: list[str], cwd: Path | None) -> bool:
    """`sample <pid|name> [secs [ms]]` with a temp `-file`; `-e` opens an editor."""

    operands = 0
    index = 0
    while index < len(arguments):
        word = arguments[index]
        index += 1
        if word in SAMPLE_OUTPUT_OPTIONS:
            index += 1
        elif word.startswith("-") and word not in SAMPLE_SWITCHES:
            return False
        elif not word.startswith("-"):
            operands += 1
    return 1 <= operands <= 3 and index <= len(arguments) and _outputs_scratch(
        arguments, SAMPLE_OUTPUT_OPTIONS, cwd,
    )
