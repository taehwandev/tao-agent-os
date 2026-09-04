"""Read-only structure checks for the Tao Agent OS review hook."""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from agent_review_boundary import boundary_note_requirements
from agent_review_purpose import purpose_failures
from agent_structure_rules import structure_rule_review
from agent_workspace_policy import is_non_git_workspace, is_writing_workspace


CommandRunner = Callable[[list[str], Path], dict[str, Any]]

REVIEW_SOURCE_FILE_LINE_LIMIT = 500
REVIEW_FILE_REVIEW_WARNING_LIMIT = 300
REVIEW_ADDED_LINE_LIMIT = 300
REVIEW_FUNCTION_LINE_LIMIT = 120
# The file/block gates above catch a unit that grew too large. They do nothing
# about the opposite failure: a small task spread across many new files, layers,
# and abstractions ("dozens of files for a few lines of behavior"). Count new
# development source files and require structure-review evidence past this limit
# so sprawl has to be justified per file/abstraction against a present risk. See
# llm-coding-discipline/references/current-guidance.md#match-structure-to-the-problem-hard-stop.
REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT = 5
# Test files legitimately run longer than production files (setup, fixtures,
# one scenario per case), so they get a wider budget instead of the source
# limit -- but an unbounded exemption is how a single test file grows to
# thousands of lines with no gate ever flagging it. See
# common/skills/testing/references/current-guidance.md#test-file-organization.
REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER = 3
REVIEW_TEST_FILE_LINE_LIMIT = REVIEW_SOURCE_FILE_LINE_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT = (
    REVIEW_FILE_REVIEW_WARNING_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
)
REVIEW_TEST_ADDED_LINE_LIMIT = REVIEW_ADDED_LINE_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
# Every structural check below inspects development source files only, so a
# rewrite that dropped a documented procedure out of a markdown file produced no
# signal from any gate: the result still parsed, still validated, and still
# passed review. Net line loss is therefore measured for every changed path
# regardless of extension, because losing content is a reviewable outcome of the
# diff rather than a property of the language it was written in.
REVIEW_NET_DELETION_LIMIT = 50
REVIEW_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".cjs",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".m",
    ".mjs",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sass",
    ".scss",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
REVIEW_STYLE_EXTENSIONS = {".css", ".scss", ".sass"}
STRUCTURE_REVIEW_SCOPE_NOTE = (
    "checks only changed files in the development-file extension allowlist; tests, "
    "fixtures, mocks, and specs use a wider file-size budget instead of the source limit "
    "(see REVIEW_TEST_FILE_LINE_LIMIT) but are not exempt from it; generated or pinned "
    "third-party files, config/build files, Markdown, MDX, and prose docs are excluded "
    "from runtime hard gates; test files are exempt only from the oversized-block check"
)
REVIEW_SKIP_PARTS = {
    ".tao",
    ".git",
    ".next",
    "DerivedData",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
}
REVIEW_GENERATED_PARTS = {"__generated__", "generated", "gen"}
REVIEW_CONFIG_FILE_NAMES = {
    "package.swift",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "setup.py",
}
REVIEW_CONFIG_SUFFIXES = (
    ".config.cjs", ".config.js", ".config.mjs", ".config.mts", ".config.py",
    ".config.ts", ".conf.js", ".conf.ts", ".gradle", ".gradle.kts",
)
TEST_PATH_PARTS = {
    "__fixtures__",
    "__mocks__",
    "__tests__",
    "fixture",
    "fixtures",
    "mock",
    "mocks",
    "spec",
    "specs",
    "test",
    "tests",
}
PYTHON_BLOCK_RE = re.compile(r"^(\s*)(?:async\s+def|def|class)\s+([A-Za-z_]\w*)\b")
BRACE_BLOCK_RE = re.compile(
    r"^\s*(?:"
    r"(?:export\s+)?(?:async\s+)?function\s+\w+"
    r"|(?:export\s+)?(?:default\s+)?class\s+\w+"
    r"|(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
    r"|(?:public|private|protected|internal|static|final|open|override|async|func|fun|def|fn|"
    r"function|method|class|struct|enum|interface|type)\b.*"
    r")"
)
BRACE_TYPE_BLOCK_RE = re.compile(
    r"^\s*(?:(?:export|default|public|private|protected|internal|static|final|open|abstract|"
    r"sealed|data|value|annotation|enum)\s+)*(?:class|struct|enum|interface|object|record|"
    r"actor|protocol|type)\b"
)
STYLE_BLOCK_RE = re.compile(r"^\s*[^@{}][^{}]*\{\s*$")


def structure_review(
    project: Path,
    max_file_lines: int,
    max_block_lines: int,
    run_command: CommandRunner,
    review_paths: list[str] | None = None,
    max_added_lines: int = REVIEW_ADDED_LINE_LIMIT,
    source_project: Path | None = None,
    review_commits: tuple[str, str] | None = None,
) -> dict[str, Any]:
    source_root = source_project or project
    discovery, paths = changed_source_paths(
        project,
        run_command,
        review_paths,
        review_commits=review_commits,
        source_project=source_root,
    )
    subject_run_command = _subject_run_command(project, run_command, review_commits)
    result = _structure_result(
        discovery,
        paths,
        max_file_lines=max_file_lines,
        max_block_lines=max_block_lines,
        max_added_lines=max_added_lines,
    )

    for relative in paths:
        is_test_path = test_exempt_path(relative)
        if is_test_path:
            result["test_exempt_paths"].append(str(relative))
        else:
            result["strict_checked_paths"].append(str(relative))

        absolute = source_root / relative
        try:
            lines = absolute.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            result["warnings"].append(f"{relative} is not valid UTF-8; manual structure review required")
            continue

        metadata = discovery["path_metadata"].get(str(relative), {})
        if is_test_path:
            # Tests are exempt only from the oversized-block check below (a
            # single long scenario/setup method is a normal test shape), not
            # from a file-size ceiling -- see REVIEW_TEST_FILE_LINE_LIMIT.
            check_file_size(
                relative,
                lines,
                REVIEW_TEST_FILE_LINE_LIMIT,
                metadata,
                result,
                max_added_lines=max_added_lines * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER,
                review_warning_file_lines=REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT,
            )
            continue

        check_file_size(
            relative,
            lines,
            max_file_lines,
            metadata,
            result,
            max_added_lines=max_added_lines,
        )
        block_failures, block_warnings = large_block_findings(
            source_root,
            relative,
            lines,
            max_block_lines,
            metadata,
            subject_run_command,
        )
        result["failures"].extend(block_failures)
        result["warnings"].extend(block_warnings)

    _add_cross_path_findings(
        result,
        source_root=source_root,
        paths=paths,
        discovery=discovery,
        subject_run_command=subject_run_command,
    )
    return result


def _structure_result(
    discovery: dict[str, Any],
    paths: list[Path],
    *,
    max_file_lines: int,
    max_block_lines: int,
    max_added_lines: int,
) -> dict[str, Any]:
    """The review's answer sheet, with every limit it will be judged against.

    The limits are recorded rather than only applied, because a reader who is
    told a file is too long has to be able to see what "too long" was for that
    file: the test budget and the source budget differ, and which one applied is
    not recoverable from the failure text alone.
    """

    return {
        "checked_paths": [str(path) for path in paths],
        "checked_path_count": len(paths),
        "development_extensions": sorted(REVIEW_SOURCE_EXTENSIONS),
        "strict_checked_paths": [],
        "test_exempt_paths": [],
        "max_file_lines": max_file_lines,
        "max_block_lines": max_block_lines,
        "max_added_lines": max_added_lines,
        "review_warning_file_lines": REVIEW_FILE_REVIEW_WARNING_LIMIT,
        "test_max_file_lines": REVIEW_TEST_FILE_LINE_LIMIT,
        "test_max_added_lines": max_added_lines * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER,
        "test_review_warning_file_lines": REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT,
        "scope": STRUCTURE_REVIEW_SCOPE_NOTE,
        "warnings": [],
        "failures": list(discovery["command_errors"]),
        "boundary_note_requirements": [],
        "net_deletion_limit": REVIEW_NET_DELETION_LIMIT,
        "net_deletions": net_deletion_findings(discovery["path_metadata"]),
        "discovery": discovery,
    }


def _add_cross_path_findings(
    result: dict[str, Any],
    *,
    source_root: Path,
    paths: list[Path],
    discovery: dict[str, Any],
    subject_run_command: CommandRunner,
) -> None:
    """Everything that can only be seen with the whole changed set in view.

    Sprawl, content-preserving copies, purpose overlap and boundary notes are
    all statements about how the changed files relate to each other, so none of
    them can be decided inside the per-file loop above.
    """

    flag_new_source_file_sprawl(result, discovery["path_metadata"])
    flag_content_preserving_source_copies(result, discovery["path_metadata"])
    result["failures"].extend(
        purpose_failures(
            source_root,
            paths,
            discovery["path_metadata"],
            review_source_path,
            test_exempt_path,
            subject_run_command,
        )
    )
    structure_rules = structure_rule_review(
        source_root,
        paths,
        discovery["path_metadata"],
        review_source_path,
        test_exempt_path,
    )
    result["structure_rules"] = structure_rules
    result["failures"].extend(structure_rules["failures"])
    result["warnings"].extend(structure_rules["warnings"])
    result["boundary_note_requirements"] = boundary_note_requirements(
        source_root,
        paths,
        discovery["path_metadata"],
        subject_run_command,
        review_source_path,
        test_exempt_path,
    )


def flag_new_source_file_sprawl(
    result: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
) -> None:
    """Require justification when a change spawns many new source files.

    Test, config, generated, and pinned third-party files are already excluded
    from strict_checked_paths, so this counts only new development source files.
    """
    added = [
        path
        for path in result["strict_checked_paths"]
        if path_metadata.get(path, {}).get("status") == "A"
    ]
    result["new_source_file_count"] = len(added)
    result["new_source_file_pressure_limit"] = REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT
    if len(added) <= REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT:
        return

    shown = ", ".join(added[:8])
    if len(added) > 8:
        shown += "; ..."
    result["warnings"].append(
        f"change adds {len(added)} new development source files ({shown}); "
        f"new-file review-pressure limit is {REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT}; "
        "structure-review evidence must justify each new file or abstraction against a "
        "concrete present risk (see Match Structure To The Problem), or the change should "
        "be collapsed into fewer files"
    )


def flag_content_preserving_source_copies(
    result: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
) -> None:
    """Keep copy-first migrations visible without treating retained debt as new work."""
    copied = [
        path
        for path in result["strict_checked_paths"]
        if path_metadata.get(path, {}).get("status") == "C"
    ]
    result["content_preserving_source_copy_count"] = len(copied)
    if not copied:
        return

    shown = ", ".join(copied[:8])
    if len(copied) > 8:
        shown += "; ..."
    result["warnings"].append(
        f"change adds {len(copied)} content-preserving source copy/copies ({shown}); "
        "structure-review evidence must name the copy-first source and target, the "
        "behavior-parity verification, and the caller-cutover or legacy-removal condition"
    )


def changed_source_paths(
    project: Path,
    run_command: CommandRunner,
    review_paths: list[str] | None = None,
    *,
    review_commits: tuple[str, str] | None = None,
    source_project: Path | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    commands: dict[str, Any] = {}
    names: set[str] = set()
    path_metadata: dict[str, dict[str, Any]] = {}
    command_errors: list[str] = []

    if review_commits is not None:
        base_sha, head_sha = review_commits
        collect_commit_diff(
            project,
            run_command,
            commands,
            names,
            path_metadata,
            command_errors,
            base_sha,
            head_sha,
            review_paths,
        )
        paths = [Path(name) for name in sorted(names)]
        source_root = source_project or project
        checked = [path for path in paths if review_source_path(source_root, path)]
        return {
            "commands": commands,
            "command_errors": command_errors,
            "path_metadata": path_metadata,
            "review_commits": {"base_sha": base_sha, "head_sha": head_sha},
        }, checked

    head = run_command(["git", "rev-parse", "--verify", "HEAD"], project)
    commands["rev_parse_head"] = head
    if head["returncode"] != 0 and (
        is_writing_workspace(project) or is_non_git_workspace(project)
    ):
        return {
            "commands": commands,
            "command_errors": [],
            "path_metadata": path_metadata,
            "review_only": "non_git_workspace",
        }, []
    if head["returncode"] == 0:
        collect_head_diff(project, run_command, commands, names, path_metadata, command_errors, review_paths)
    else:
        tracked = run_command(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", *_pathspec_args(review_paths)],
            project,
        )
        commands["ls_files_initial"] = tracked
        if tracked["returncode"] == 0:
            for name in _listed_paths(tracked["stdout"]):
                record_path(names, path_metadata, name, status="A")
        else:
            command_errors.append("git ls-files changed source discovery failed")

    untracked = run_command(
        ["git", "ls-files", "-z", "--others", "--exclude-standard", *_pathspec_args(review_paths)],
        project,
    )
    commands["ls_files_untracked"] = untracked
    if untracked["returncode"] == 0:
        for name in _listed_paths(untracked["stdout"]):
            record_path(names, path_metadata, name, status="A", untracked=True)
    else:
        command_errors.append("git ls-files untracked source discovery failed")

    if head["returncode"] == 0:
        reclassify_untracked_moves(
            project,
            run_command,
            commands,
            path_metadata,
            command_errors,
            review_paths,
        )
        reclassify_untracked_copies(
            project,
            run_command,
            commands,
            path_metadata,
            command_errors,
        )

    paths = [Path(name) for name in sorted(names)]
    checked = [path for path in paths if review_source_path(project, path)]
    return {
        "commands": commands,
        "command_errors": command_errors,
        "path_metadata": path_metadata,
    }, checked


def collect_commit_diff(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    base_sha: str,
    head_sha: str,
    review_paths: list[str] | None = None,
) -> None:
    pathspec = _pathspec_args(review_paths)
    status = run_command(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base_sha,
            head_sha,
            *pathspec,
        ],
        project,
    )
    commands["commit_diff_name_status"] = status
    if status["returncode"] == 0:
        for destination, status_code, previous in _parse_name_status(status["stdout"]):
            updates: dict[str, Any] = {"status": status_code}
            if previous:
                updates["previous_path"] = previous
            record_path(names, path_metadata, destination, **updates)
    else:
        command_errors.append("git commit-range changed source discovery failed")

    numstat = run_command(
        [
            "git",
            "diff",
            "--numstat",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base_sha,
            head_sha,
            *pathspec,
        ],
        project,
    )
    commands["commit_diff_numstat"] = numstat
    if numstat["returncode"] == 0:
        for destination, additions, deletions in _parse_numstat(numstat["stdout"]):
            record_path(
                names,
                path_metadata,
                destination,
                additions=additions,
                deletions=deletions,
            )
    else:
        command_errors.append("git commit-range line-count discovery failed")


def _subject_run_command(
    git_project: Path,
    run_command: CommandRunner,
    review_commits: tuple[str, str] | None,
) -> CommandRunner:
    if review_commits is None:
        return run_command
    base_sha, _head_sha = review_commits

    def subject_command(command: list[str], _cwd: Path) -> dict[str, Any]:
        rewritten = [
            base_sha if argument == "HEAD" else f"{base_sha}:{argument[5:]}"
            if argument.startswith("HEAD:")
            else argument
            for argument in command
        ]
        return run_command(rewritten, git_project)

    return subject_command


def collect_head_diff(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    review_paths: list[str] | None = None,
) -> None:
    pathspec = _pathspec_args(review_paths)
    status = run_command(
        ["git", "diff", "--name-status", "-z", "--diff-filter=ACMRTUXB", "HEAD", *pathspec],
        project,
    )
    commands["diff_name_status"] = status
    if status["returncode"] == 0:
        for destination, status_code, previous in _parse_name_status(status["stdout"]):
            updates: dict[str, Any] = {"status": status_code}
            if previous:
                updates["previous_path"] = previous
            record_path(names, path_metadata, destination, **updates)
    else:
        command_errors.append("git diff changed source discovery failed")

    numstat = run_command(
        ["git", "diff", "--numstat", "-z", "--diff-filter=ACMRTUXB", "HEAD", *pathspec],
        project,
    )
    commands["diff_numstat"] = numstat
    if numstat["returncode"] == 0:
        for destination, additions, deletions in _parse_numstat(numstat["stdout"]):
            record_path(
                names,
                path_metadata,
                destination,
                additions=additions,
                deletions=deletions,
            )
    else:
        command_errors.append("git diff line-count discovery failed")


def _listed_paths(stdout: str) -> list[str]:
    """Return the paths of a one-path-per-record ``-z`` git listing.

    Without ``-z`` git quotes any path holding a special character, so a file
    named ``we<newline>ird.py`` arrives as the literal 11-character text
    ``"we\\nird.py"``. Discovery then recorded that quoted string as a filename
    and dropped the real file from review entirely -- a silent miss in a gate
    whose whole job is to see every changed file. NUL is the one byte a path
    cannot contain, and ``-z`` output is never quoted, so the fields are the
    paths verbatim and must not be stripped.
    """

    if "\0" not in stdout:
        # Injected command runners in tests still provide the line-oriented
        # form; keep reading it for paths that carry no separator character.
        return [line.strip() for line in stdout.splitlines() if line.strip()]
    return [field for field in stdout.split("\0") if field]


def _parse_name_status(stdout: str) -> list[tuple[str, str, str]]:
    """Return (destination, status, previous) from ``git diff --name-status -z``.

    Splitting the human-readable form on tabs silently corrupts any path that
    contains one: the parser kept the fragment after the last tab and recorded a
    file that does not exist, while ``--numstat`` recorded the real path, so the
    two discovery passes disagreed and invented a phantom entry. A newline in a
    path breaks the line split the same way. NUL is the only separator no path
    can contain.
    """

    if "\0" not in stdout:
        # Injected command runners in tests still provide the line-oriented
        # form; keep reading it for paths that carry no separator character.
        records: list[tuple[str, str, str]] = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                code = parts[0][:1]
                previous = parts[-2] if code in {"R", "C"} and len(parts) >= 3 else ""
                records.append((parts[-1], code, previous))
        return records

    fields = stdout.split("\0")
    records = []
    index = 0
    while index + 1 < len(fields):
        code = fields[index][:1]
        index += 1
        if not code:
            continue
        source = fields[index]
        index += 1
        if code in {"R", "C"}:
            if index >= len(fields):
                break
            records.append((fields[index], code, source))
            index += 1
        else:
            records.append((source, code, ""))
    return records


def _parse_numstat(stdout: str) -> list[tuple[str, int, int]]:
    """Return destination-path line counts from ``git diff --numstat -z``.

    A rename or copy has an empty path in its header followed by separate source
    and destination NUL fields. Human-readable numstat instead renders
    ``{old => new}``, which is not a filesystem path and cannot join the counts
    to the destination discovered by ``--name-status``.
    """

    if "\0" not in stdout:
        # Preserve compatibility with injected command runners that still
        # provide the traditional line-oriented form for ordinary paths.
        records: list[tuple[str, int, int]] = []
        for line in stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[2]:
                records.append(
                    (parts[2], _numstat_count(parts[0]), _numstat_count(parts[1]))
                )
        return records

    fields = stdout.split("\0")
    records = []
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        if not header:
            continue
        parts = header.split("\t", 2)
        if len(parts) != 3:
            continue
        additions, deletions, destination = parts
        if not destination:
            if index + 1 >= len(fields):
                break
            index += 1  # source path
            destination = fields[index]
            index += 1
        if destination:
            records.append((destination, _numstat_count(additions), _numstat_count(deletions)))
    return records


def _numstat_count(value: str) -> int:
    return int(value) if value.isdigit() else 0


def reclassify_untracked_moves(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    review_paths: list[str] | None = None,
) -> None:
    """Recognize unstaged content-preserving moves before applying new-file gates.

    Git does not report a filesystem move as a rename until it is staged. The
    review hook still has to distinguish a moved legacy owner from hundreds of
    newly added lines without mutating the caller's index. Limit matching to
    deleted files with the same filename and require high line similarity.
    """

    deleted = run_command(
        ["git", "diff", "--name-only", "-z", "--diff-filter=D", "HEAD", *_pathspec_args(review_paths)],
        project,
    )
    commands["diff_deleted_paths"] = deleted
    if deleted["returncode"] != 0:
        command_errors.append("git diff deleted source discovery failed")
        return

    deleted_by_filename: dict[str, list[str]] = {}
    for previous_path in _listed_paths(deleted["stdout"]):
        deleted_by_filename.setdefault(Path(previous_path).name, []).append(previous_path)

    matches: list[dict[str, Any]] = []
    for current_path, metadata in path_metadata.items():
        if metadata.get("status") != "A" or metadata.get("untracked") is not True:
            continue
        candidates = deleted_by_filename.get(Path(current_path).name, [])
        if not candidates:
            continue
        try:
            current_lines = (project / current_path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        scored_candidates: list[tuple[float, str, list[str]]] = []
        for previous_path in candidates:
            previous = run_command(["git", "show", f"HEAD:{previous_path}"], project)
            if previous["returncode"] != 0:
                continue
            previous_lines = previous["stdout"].splitlines()
            similarity = SequenceMatcher(
                None,
                previous_lines,
                current_lines,
                autojunk=False,
            ).ratio()
            scored_candidates.append((similarity, previous_path, previous_lines))

        if not scored_candidates:
            continue
        scored_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        similarity, previous_path, previous_lines = scored_candidates[0]
        if similarity < 0.8:
            continue
        additions, deletions = line_change_counts(previous_lines, current_lines)
        metadata.update(
            status="R",
            previous_path=previous_path,
            additions=additions,
            deletions=deletions,
            similarity=round(similarity, 4),
        )
        matches.append(
            {
                "current_path": current_path,
                "previous_path": previous_path,
                "similarity": round(similarity, 4),
            }
        )

    commands["unstaged_move_detection"] = {
        "similarity_threshold": 0.8,
        "matches": matches,
    }


def reclassify_untracked_copies(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
) -> None:
    """Recognize copy-first migrations while the tracked source remains in place.

    Copy-first work intentionally keeps the current runtime owner until parity is
    proven. Git therefore reports the destination as an untracked addition rather
    than a copy. Compare only remaining untracked additions against tracked HEAD
    files with the same filename and require high line similarity.
    """

    tracked = run_command(["git", "ls-files", "-z", "--cached", "--"], project)
    commands["ls_files_copy_candidates"] = tracked
    if tracked["returncode"] != 0:
        command_errors.append("git ls-files copy candidate discovery failed")
        return

    tracked_by_filename: dict[str, list[str]] = {}
    for previous_path in _listed_paths(tracked["stdout"]):
        tracked_by_filename.setdefault(Path(previous_path).name, []).append(previous_path)

    matches: list[dict[str, Any]] = []
    for current_path, metadata in path_metadata.items():
        if metadata.get("status") != "A" or metadata.get("untracked") is not True:
            continue
        candidates = [
            previous_path
            for previous_path in tracked_by_filename.get(Path(current_path).name, [])
            if previous_path != current_path
        ]
        if not candidates:
            continue
        try:
            current_lines = (project / current_path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        scored_candidates: list[tuple[float, str, list[str]]] = []
        for previous_path in candidates:
            previous = run_command(["git", "show", f"HEAD:{previous_path}"], project)
            if previous["returncode"] != 0:
                continue
            previous_lines = previous["stdout"].splitlines()
            similarity = SequenceMatcher(
                None,
                previous_lines,
                current_lines,
                autojunk=False,
            ).ratio()
            scored_candidates.append((similarity, previous_path, previous_lines))

        if not scored_candidates:
            continue
        scored_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        similarity, previous_path, previous_lines = scored_candidates[0]
        if similarity < 0.8:
            continue
        additions, deletions = line_change_counts(previous_lines, current_lines)
        metadata.update(
            status="C",
            previous_path=previous_path,
            additions=additions,
            deletions=deletions,
            similarity=round(similarity, 4),
        )
        matches.append(
            {
                "current_path": current_path,
                "previous_path": previous_path,
                "similarity": round(similarity, 4),
            }
        )

    commands["unstaged_copy_detection"] = {
        "similarity_threshold": 0.8,
        "matches": matches,
    }


def line_change_counts(previous_lines: list[str], current_lines: list[str]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for tag, previous_start, previous_end, current_start, current_end in SequenceMatcher(
        None,
        previous_lines,
        current_lines,
        autojunk=False,
    ).get_opcodes():
        if tag in {"insert", "replace"}:
            additions += current_end - current_start
        if tag in {"delete", "replace"}:
            deletions += previous_end - previous_start
    return additions, deletions


def record_path(
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    name: str,
    **updates: Any,
) -> None:
    names.add(name)
    path_metadata.setdefault(name, {}).update(updates)


def net_deletion_findings(path_metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return changed paths whose net line loss needs an explicit account.

    ``path_metadata`` carries the numstat counts for every changed path, not just
    the development sources the structural checks read, so this is the one place
    a large removal in documentation, configuration, or fixtures is observable.
    """

    findings: list[dict[str, Any]] = []
    for name in sorted(path_metadata):
        metadata = path_metadata[name]
        additions = metadata.get("additions")
        deletions = metadata.get("deletions")
        if not isinstance(additions, int) or not isinstance(deletions, int):
            continue
        net = deletions - additions
        if net >= REVIEW_NET_DELETION_LIMIT:
            findings.append(
                {"path": name, "additions": additions, "deletions": deletions, "net": net}
            )
    return findings


def _pathspec_args(review_paths: list[str] | None) -> list[str]:
    paths = [path.strip() for path in (review_paths or []) if path.strip()]
    return ["--", *paths] if paths else ["--"]


def review_source_path(project: Path, path: Path) -> bool:
    absolute = project / path
    return (
        path.suffix.lower() in REVIEW_SOURCE_EXTENSIONS
        and not any(part in REVIEW_SKIP_PARTS for part in path.parts)
        and not config_or_generated_path(path)
        and not pinned_third_party_source(project, path)
        and absolute.exists()
        and absolute.is_file()
    )


def config_or_generated_path(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts.intersection(REVIEW_GENERATED_PARTS):
        return True

    name = path.name.lower()
    return name in REVIEW_CONFIG_FILE_NAMES or name.endswith(REVIEW_CONFIG_SUFFIXES)


def pinned_third_party_source(project: Path, path: Path) -> bool:
    """Recognize an isolated vendor package only when provenance is present."""
    lower_parts = [part.lower() for part in path.parts]
    try:
        boundary = lower_parts.index("third_party")
    except ValueError:
        return False
    if boundary + 1 >= len(path.parts):
        return False

    package = project.joinpath(*path.parts[: boundary + 2])
    readme = package / "README.md"
    license_file = package / "LICENSE"
    if not readme.is_file() or not license_file.is_file():
        return False
    try:
        provenance = readme.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return all(marker in provenance for marker in ("upstream", "commit", "sha-256", "license"))


def test_exempt_path(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts.intersection(TEST_PATH_PARTS):
        return True

    stem = path.stem
    lower_stem = stem.lower()
    return (
        lower_stem.startswith(("test_", "test-"))
        or lower_stem.endswith(("_test", "-test", ".test", "_tests", "-tests", ".tests"))
        or lower_stem.endswith(("_spec", "-spec", ".spec", "_specs", "-specs", ".specs"))
        or stem.endswith(("Test", "Tests", "Spec", "Specs"))
    )


def check_file_size(
    path: Path,
    lines: list[str],
    max_file_lines: int,
    metadata: dict[str, Any],
    result: dict[str, Any],
    *,
    max_added_lines: int = REVIEW_ADDED_LINE_LIMIT,
    review_warning_file_lines: int = REVIEW_FILE_REVIEW_WARNING_LIMIT,
) -> None:
    line_count = len(lines)
    status = metadata.get("status", "")
    added_lines = metadata.get("additions")
    if added_lines is None:
        added_lines = line_count if status == "A" else 0
    deleted_lines = metadata.get("deletions", 0)
    is_net_reducing_rewrite = status != "A" and deleted_lines > added_lines

    if status == "A" and line_count > max_file_lines:
        result["failures"].append(
            f"{path} is a new development source/style file with {line_count} lines; "
            f"new-file hard limit is {max_file_lines}; split by responsibility before approval"
        )
    if added_lines > max_added_lines and is_net_reducing_rewrite:
        result["warnings"].append(
            f"{path} adds {added_lines} lines but deletes {deleted_lines} lines, so the file "
            "is not growing; structure-review evidence is required instead of an addition-limit failure"
        )
    elif added_lines > max_added_lines:
        result["failures"].append(
            f"{path} adds {added_lines} lines in one development source/style file; "
            f"per-file addition limit is {max_added_lines}; split the change before approval. "
            "Move independently reviewable previews, demos, or samples to a subject-named "
            "sibling file, or extract the nearest real behavior owner"
        )
    if status != "A" and line_count > max_file_lines and added_lines > 0:
        result["warnings"].append(
            f"{path} is already over {max_file_lines} lines and adds {added_lines} line(s); "
            "structure-review evidence is required and the new responsibility should be extracted "
            "when it expands the public owner surface"
        )
    elif line_count > review_warning_file_lines:
        result["warnings"].append(
            f"{path} is a changed development source/style file with {line_count} lines; "
            f"review-pressure limit is {review_warning_file_lines}; "
            "structure-review evidence is required before approving more behavior"
        )


def large_block_failures(path: Path, lines: list[str], max_block_lines: int) -> list[str]:
    failures, _warnings = large_block_findings(
        Path("."),
        path,
        lines,
        max_block_lines,
        {"status": "A"},
        lambda _command, _cwd: {"returncode": 1, "stdout": "", "stderr": ""},
    )
    return failures


def large_block_findings(
    project: Path,
    path: Path,
    lines: list[str],
    max_block_lines: int,
    metadata: dict[str, Any],
    run_command: CommandRunner,
) -> tuple[list[str], list[str]]:
    current = oversized_blocks(path, lines, max_block_lines)
    if not current:
        return [], []

    previous = previous_oversized_blocks(project, path, metadata, run_command, max_block_lines)
    previous_by_label = {str(record["label"]): record for record in previous}
    failures: list[str] = []
    warnings: list[str] = []
    for record in current:
        previous_record = previous_by_label.get(str(record["label"]))
        if previous_record and int(record["span"]) <= int(previous_record["span"]):
            warnings.append(preexisting_block_warning(record, int(previous_record["span"]), max_block_lines))
        else:
            failures.append(block_failure(record, max_block_lines))
    return failures, warnings


def previous_oversized_blocks(
    project: Path,
    path: Path,
    metadata: dict[str, Any],
    run_command: CommandRunner,
    max_block_lines: int,
) -> list[dict[str, Any]]:
    if metadata.get("status") == "A":
        return []
    previous_path = str(metadata.get("previous_path") or path.as_posix())
    previous = run_command(["git", "show", f"HEAD:{previous_path}"], project)
    if previous.get("returncode") != 0:
        return []
    return oversized_blocks(path, str(previous.get("stdout") or "").splitlines(), max_block_lines)


def oversized_blocks(path: Path, lines: list[str], max_block_lines: int) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".py":
        return python_blocks(path, lines, max_block_lines)
    return brace_blocks(path, lines, max_block_lines)


def python_blocks(path: Path, lines: list[str], max_block_lines: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    starts: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = PYTHON_BLOCK_RE.match(line)
        if match:
            starts.append((index, count_line_indent(line), match.group(2)))

    for start_index, start_indent, name in starts:
        span = python_block_span(lines, start_index, start_indent)
        if span > max_block_lines:
            blocks.append(block_record(path, start_index, name, span))
    return blocks


def python_block_span(lines: list[str], start_index: int, start_indent: int) -> int:
    end_index = len(lines) - 1
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if count_line_indent(lines[index]) <= start_indent and not stripped.startswith("@"):
            end_index = index - 1
            break
    return end_index - start_index + 1


def count_line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def brace_blocks(path: Path, lines: list[str], max_block_lines: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "{" not in stripped or not starts_review_block(path, stripped):
            continue
        span = brace_block_span(lines, index)
        if span > max_block_lines:
            label = stripped[:80].replace("`", "'")
            blocks.append(block_record(path, index, label, span))
    return blocks


def starts_review_block(path: Path, stripped_line: str) -> bool:
    if path.suffix.lower() in REVIEW_STYLE_EXTENSIONS:
        return bool(STYLE_BLOCK_RE.match(stripped_line))
    if BRACE_TYPE_BLOCK_RE.match(stripped_line):
        return False
    return bool(BRACE_BLOCK_RE.match(stripped_line))


def brace_block_span(lines: list[str], start_index: int) -> int:
    balance = 0
    for index in range(start_index, len(lines)):
        balance += lines[index].count("{") - lines[index].count("}")
        if balance <= 0:
            return index - start_index + 1
    return len(lines) - start_index


def block_record(path: Path, start_index: int, label: str, span: int) -> dict[str, Any]:
    return {
        "path": path,
        "line": start_index + 1,
        "label": label,
        "span": span,
    }


def block_failure(record: dict[str, Any], max_block_lines: int) -> str:
    return (
        f"{record['path']}:{record['line']} block `{record['label']}` spans {record['span']} lines; "
        f"limit is {max_block_lines}; split responsibilities until the block is within the "
        "limit, or use an explicitly reviewed project-specific max-function-lines limit; "
        "structure-review prose alone does not bypass this hard gate"
    )


def preexisting_block_warning(
    record: dict[str, Any],
    previous_span: int,
    max_block_lines: int,
) -> str:
    return (
        f"{record['path']}:{record['line']} block `{record['label']}` is a pre-existing "
        f"oversized unit spanning {record['span']} lines (previously {previous_span}); "
        f"limit is {max_block_lines}; structure-review evidence is required, but this "
        "does not block the current scoped change unless the diff grows the unit or adds "
        "a new responsibility"
    )
