"""Inspect Graphify input policy and manifest coverage."""

from __future__ import annotations

import hashlib
from pathlib import Path

from support.graphify_contract import (
    GRAPHIFY_RUNTIME_ADAPTER_INPUTS,
    PROJECT_MANIFEST_PATH,
)


# Tao project knowledge is owned under .agents. User-level runtime discovery and
# settings under .claude/.codex are not target-project knowledge inputs.
KNOWLEDGE_ROOTS = (".agents",)
KNOWLEDGE_SUFFIXES = {
    ".json", ".js", ".md", ".mdx", ".mjs", ".py", ".rst", ".sh",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}


def inspect_project_graph_inputs(
    project_path: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    blanket_exclusions = blanket_knowledge_exclusions(project_path)
    knowledge_files = project_knowledge_files(project_path)
    manifest, _ = read_manifest_state(project_path, manifest_path=manifest_path)
    manifest_keys = set(manifest)
    knowledge_relatives = {
        path.relative_to(project_path).as_posix() for path in knowledge_files
    }
    missing = knowledge_relatives - manifest_keys
    stale = {
        relative
        for relative in knowledge_relatives & manifest_keys
        if not manifest_entry_current(project_path / relative, manifest[relative])
    }
    return {
        "project_knowledge_file_count": len(knowledge_relatives),
        "project_agent_knowledge_file_count": len(knowledge_relatives),
        "knowledge_manifest_file_count": len(knowledge_relatives & manifest_keys),
        "knowledge_manifest_missing_count": len(missing),
        "knowledge_manifest_stale_count": len(stale),
        "knowledge_manifest_ready": not knowledge_relatives or not (missing or stale),
        "blanket_knowledge_input_exclusions": blanket_exclusions,
        "blanket_agent_input_exclusions": blanket_exclusions,
        "graph_input_policy_ready": not blanket_exclusions,
    }


def project_knowledge_files(project_path: Path) -> list[Path]:
    roots = [project_path / name for name in KNOWLEDGE_ROOTS]
    narrow_exclusions = literal_knowledge_exclusions(project_path)
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in KNOWLEDGE_SUFFIXES:
                continue
            relative = path.relative_to(project_path)
            if is_graphify_runtime_adapter_input(relative):
                continue
            if any(
                relative == excluded or excluded in relative.parents
                for excluded in narrow_exclusions
            ):
                continue
            files.append(path)
    return sorted(files, key=str)


def literal_knowledge_exclusions(project_path: Path) -> set[Path]:
    exclusions: set[Path] = set()
    for relative in (".gitignore", ".graphifyignore"):
        path = project_path / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            value = line.strip()
            if not value or value.startswith(("#", "!")):
                continue
            normalized = value.lstrip("/").rstrip("/")
            if not normalized or any(char in normalized for char in "*?[]"):
                continue
            candidate = Path(normalized)
            if (
                len(candidate.parts) > 1
                and candidate.parts[0] in KNOWLEDGE_ROOTS
            ):
                exclusions.add(candidate)
    return exclusions


def is_graphify_runtime_adapter_input(relative: str | Path) -> bool:
    path = Path(normalize_relative_path(str(relative)))
    return any(
        path == adapter or adapter in path.parents
        for adapter in GRAPHIFY_RUNTIME_ADAPTER_INPUTS
    )


def blanket_knowledge_exclusions(project_path: Path) -> list[str]:
    matches: list[str] = []
    for relative in (".gitignore", ".graphifyignore"):
        path = project_path / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            value = line.strip()
            if not value or value.startswith(("#", "!")):
                continue
            normalized = value.lstrip("/")
            if normalized.startswith("**/"):
                normalized = normalized[3:]
            for root in KNOWLEDGE_ROOTS:
                if not normalized.startswith(root):
                    continue
                remainder = normalized[len(root):].strip("/")
                if not remainder or set(remainder) <= {"*", "/"}:
                    matches.append(f"{relative}:{value}")
                break
    return matches


def read_manifest_state(
    project_path: Path,
    *,
    manifest_path: Path | None = None,
) -> tuple[dict[str, object], set[str]]:
    path = manifest_path or project_path / PROJECT_MANIFEST_PATH
    if not path.is_file():
        return {}, set()
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, set()
    if not isinstance(payload, dict):
        return {}, set()
    manifest = {normalize_relative_path(str(key)): value for key, value in payload.items()}
    stale = {
        relative
        for relative, entry in manifest.items()
        if not manifest_entry_current(project_path / relative, entry)
    }
    return manifest, stale


def manifest_entry_current(path: Path, entry: object) -> bool:
    if not path.is_file() or not isinstance(entry, dict):
        return False
    stored_hash = entry.get("semantic_hash") or entry.get("ast_hash")
    if isinstance(stored_hash, str) and stored_hash:
        try:
            digest = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324
        except OSError:
            return False
        return digest == stored_hash
    mtime = entry.get("mtime")
    if not isinstance(mtime, (int, float)):
        return False
    try:
        return abs(path.stat().st_mtime - float(mtime)) < 0.001
    except OSError:
        return False


def normalize_relative_path(value: str) -> str:
    return value[2:] if value.startswith("./") else value.lstrip("/")
