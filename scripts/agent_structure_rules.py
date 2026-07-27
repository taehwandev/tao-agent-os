"""Repo-local package and import boundary checks for review hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent_structure_imports import (
    import_candidates,
    imports_for_path,
    matches_any,
    matches_one,
    should_check_allowed_import,
)
from agent_structure_rule_config import load_structure_rule_configs, string_list


PathPredicate = Callable[[Path, Path], bool]
TestPredicate = Callable[[Path], bool]


def structure_rule_review(
    project: Path,
    paths: list[Path],
    path_metadata: dict[str, dict[str, Any]],
    review_source_path: PathPredicate,
    test_exempt_path: TestPredicate,
) -> dict[str, Any]:
    configs, load_failures = load_structure_rule_configs(project)
    result: dict[str, Any] = {
        "config_paths": [config["path"] for config in configs],
        "failures": list(load_failures),
        "warnings": [],
        "checked_paths": [],
    }
    if not configs:
        return result

    for config in configs:
        apply_config(project, paths, path_metadata, review_source_path, test_exempt_path, config, result)
    return result


def apply_config(
    project: Path,
    paths: list[Path],
    path_metadata: dict[str, dict[str, Any]],
    review_source_path: PathPredicate,
    test_exempt_path: TestPredicate,
    config: dict[str, Any],
    result: dict[str, Any],
) -> None:
    payload = config["payload"]
    include_tests = bool(payload.get("include_tests", False))
    candidates = [
        path
        for path in paths
        if review_source_path(project, path) and (include_tests or not test_exempt_path(path))
    ]
    result["checked_paths"].extend(str(path) for path in candidates)

    forbidden_new_paths = string_list(payload.get("forbidden_new_paths"), config["path"], "forbidden_new_paths", result)
    allowed_new_paths = string_list(payload.get("allowed_new_paths"), config["path"], "allowed_new_paths", result)
    check_new_path_rules(candidates, path_metadata, forbidden_new_paths, allowed_new_paths, config, result)

    rules = payload.get("rules", [])
    if rules is None:
        rules = []
    if not isinstance(rules, list):
        result["failures"].append(f"structure rules: {config['path']} field `rules` must be a list")
        return
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            result["failures"].append(
                f"structure rules: {config['path']} rule #{index + 1} must be a JSON object"
            )
            continue
        check_import_rule(project, candidates, raw_rule, config, result)


def check_new_path_rules(
    paths: list[Path],
    path_metadata: dict[str, dict[str, Any]],
    forbidden_new_paths: list[str],
    allowed_new_paths: list[str],
    config: dict[str, Any],
    result: dict[str, Any],
) -> None:
    for path in paths:
        metadata = path_metadata.get(str(path), {})
        if metadata.get("status") not in {"A", "R", "C"}:
            continue
        path_text = path.as_posix()
        for pattern in forbidden_new_paths:
            if matches_any(path_text, [pattern]):
                result["failures"].append(
                    f"structure rules: {path_text} is a new source path forbidden by "
                    f"{config['path']} pattern `{pattern}`"
                )
        if allowed_new_paths and not matches_any(path_text, allowed_new_paths):
            result["failures"].append(
                f"structure rules: {path_text} is a new source path but does not match "
                f"{config['path']} allowed_new_paths"
            )


def check_import_rule(
    project: Path,
    paths: list[Path],
    rule: dict[str, Any],
    config: dict[str, Any],
    result: dict[str, Any],
) -> None:
    name = str(rule.get("name") or "unnamed")
    path_patterns = string_list(rule.get("paths", ["**"]), config["path"], f"rules.{name}.paths", result)
    forbidden_imports = string_list(
        rule.get("forbidden_imports"),
        config["path"],
        f"rules.{name}.forbidden_imports",
        result,
    )
    allowed_imports = string_list(
        rule.get("allowed_imports"),
        config["path"],
        f"rules.{name}.allowed_imports",
        result,
    )
    project_prefixes = string_list(
        rule.get("project_import_prefixes"),
        config["path"],
        f"rules.{name}.project_import_prefixes",
        result,
    )
    allow_external = bool(rule.get("allow_external_imports", True))
    if not forbidden_imports and not allowed_imports:
        return

    for path in paths:
        path_text = path.as_posix()
        if not matches_any(path_text, path_patterns):
            continue
        imports = imports_for_path(project / path)
        for spec in imports:
            candidates = import_candidates(spec, path)
            for pattern in forbidden_imports:
                if any(matches_one(candidate, pattern) for candidate in candidates):
                    result["failures"].append(
                        f"structure rules: {path_text} imports `{spec}`, forbidden by "
                        f"{config['path']} rule `{name}` pattern `{pattern}`"
                    )
            if allowed_imports and should_check_allowed_import(spec, candidates, project_prefixes, allow_external):
                if not any(matches_any(candidate, allowed_imports) for candidate in candidates):
                    result["failures"].append(
                        f"structure rules: {path_text} imports `{spec}`, which is not allowed by "
                        f"{config['path']} rule `{name}` allowed_imports"
                    )
