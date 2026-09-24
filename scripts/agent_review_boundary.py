"""Boundary-note requirements for changed runtime package structure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_review_purpose import role_for_name


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
PathPredicate = Callable[[Path, Path], bool]
TestPredicate = Callable[[Path], bool]

BOUNDARY_NOTE_FIELDS = (
    ("owner", ("owner",)),
    ("allowed imports", ("allowed imports", "allowed import", "allowed_imports")),
    ("forbidden imports", ("forbidden imports", "forbidden import", "forbidden_imports")),
    ("callers", ("callers", "caller", "tests", "consumers")),
    ("verification", ("verification", "verify", "check", "command")),
)


def boundary_note_requirements(
    project: Path,
    paths: list[Path],
    path_metadata: dict[str, dict[str, Any]],
    run_command: CommandRunner,
    review_source_path: PathPredicate,
    test_exempt_path: TestPredicate,
) -> list[dict[str, str]]:
    requirements: list[dict[str, str]] = []
    for parent in sorted({path.parent for path in paths if added_runtime_source(project, path, path_metadata, review_source_path, test_exempt_path)}):
        added = [path for path in paths if path.parent == parent and added_runtime_source(project, path, path_metadata, review_source_path, test_exempt_path)]
        reasons = boundary_reasons(project, parent, added, run_command)
        if reasons:
            requirements.append({"package": str(parent), "reason": "; ".join(reasons), "added": ", ".join(str(path) for path in added)})
    return requirements


def missing_boundary_note_fields(evidence: str) -> list[str]:
    normalized = " ".join(evidence.lower().replace("_", " ").replace("-", " ").split())
    return [label for label, aliases in BOUNDARY_NOTE_FIELDS if not any(alias in normalized for alias in aliases)]


def format_boundary_note_requirements(requirements: list[dict[str, str]]) -> str:
    visible = [f"{item['package']} ({item['reason']})" for item in requirements[:5]]
    return "; ".join(visible) + ("" if len(requirements) <= 5 else f"; ... (+{len(requirements) - 5} more)")


BOUNDARY_NOTE_TEMPLATE = (
    "owner: <owning module>; allowed imports: <modules>; forbidden imports: <modules>; "
    "callers/tests: <callers and tests>; verification: <check run>"
)


def structure_evidence_template(structure: dict[str, Any]) -> str:
    """Return a copyable --structure-review-evidence value naming each warned file.

    Message only: the evidence checks are unchanged. The boundary labels appear
    only when an added runtime file entered a multi-role package, because only
    that case requires them.
    """

    warnings = [str(item) for item in structure.get("warnings") or []]
    named = [
        str(path)
        for path in structure.get("checked_paths") or []
        if any(str(path) in warning for warning in warnings)
    ] or ["<file>"]
    parts = [
        f"{path}: expands public owner surface? <yes/no>; why the code stays here: <reason>"
        for path in named
    ]
    if structure.get("boundary_note_requirements"):
        parts.append(BOUNDARY_NOTE_TEMPLATE)
    return 'fill-in template: --structure-review-evidence "' + " | ".join(parts) + '"'


def added_runtime_source(
    project: Path,
    path: Path,
    path_metadata: dict[str, dict[str, Any]],
    review_source_path: PathPredicate,
    test_exempt_path: TestPredicate,
) -> bool:
    metadata = path_metadata.get(str(path), {})
    return (
        metadata.get("status") == "A"
        and review_source_path(project, path)
        and not test_exempt_path(path)
    )


def boundary_reasons(
    project: Path,
    parent: Path,
    added: list[Path],
    run_command: CommandRunner,
) -> list[str]:
    reasons: list[str] = []
    if package_missing_in_head(project, parent, run_command):
        reasons.append("new runtime package/folder")

    added_roles = sorted({role for role in (role_for_name(path.stem) for path in added) if role})
    if len(added_roles) > 1:
        reasons.append(f"new files introduce multiple roles: {', '.join(added_roles)}")

    sibling_roles = sorted({role for role in (role_for_name(path.stem) for path in (project / parent).iterdir() if path.is_file()) if role})
    if len(sibling_roles) > 1:
        reasons.append(f"package now contains multiple roles: {', '.join(sibling_roles)}")
    return reasons


def package_missing_in_head(project: Path, parent: Path, run_command: CommandRunner) -> bool:
    head = run_command(["git", "rev-parse", "--verify", "HEAD"], project)
    if head["returncode"] != 0:
        return True
    result = run_command(["git", "cat-file", "-e", f"HEAD:{parent.as_posix()}"], project)
    return result["returncode"] != 0
