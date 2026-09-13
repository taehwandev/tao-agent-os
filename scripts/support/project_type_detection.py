"""Detect project type and return appropriate Claude permission entries."""

from __future__ import annotations

import json
from pathlib import Path


def detect_project_permissions(project_path: Path) -> list[str]:
    """Return permission entries for a project based on detected build tools.

    Covers parameter variations via the 'cmd *' wildcard form so one install
    handles any argument combination at runtime.
    """
    entries: list[str] = []
    entries += _swift_permissions(project_path)
    entries += _node_permissions(project_path)
    entries += _gradle_permissions(project_path)
    entries += _rust_permissions(project_path)
    entries += _go_permissions(project_path)
    entries += _python_permissions(project_path)
    return entries


# ── Swift / Xcode ──────────────────────────────────────────────────────────

def _swift_permissions(project_path: Path) -> list[str]:
    is_swift = (
        (project_path / "Package.swift").exists()
        or any(project_path.glob("*.xcodeproj"))
        or any(project_path.glob("*.xcworkspace"))
    )
    if not is_swift:
        return []
    entries: list[str] = []
    for base in ("swift build", "swift test", "swift run", "swift package"):
        entries += _cmd_entries(base)
    return entries


# ── Node.js / Bun / npm ────────────────────────────────────────────────────

def _node_permissions(project_path: Path) -> list[str]:
    entries: list[str] = []
    for pkg_json in _find_package_jsons(project_path):
        entries += _entries_for_package_json(pkg_json)
    return _dedupe(entries)


def _find_package_jsons(project_path: Path) -> list[Path]:
    """Return package.json files at root or one level deep (monorepo support)."""
    found = []
    root_pkg = project_path / "package.json"
    if root_pkg.exists():
        found.append(root_pkg)
    # Monorepo: apps/*, packages/*, etc. — limit depth to avoid node_modules
    for sub in project_path.iterdir():
        if sub.is_dir() and sub.name not in ("node_modules", ".git", "dist", ".next", "build"):
            sub_pkg = sub / "package.json"
            if sub_pkg.exists():
                found.append(sub_pkg)
    return found


def _entries_for_package_json(pkg_json: Path) -> list[str]:
    entries: list[str] = []
    try:
        data = json.loads(pkg_json.read_text())
    except Exception:
        return []

    scripts = data.get("scripts", {})
    for name in scripts:
        for runner in ("npm run", "bun run", "yarn", "pnpm run"):
            entries += _cmd_entries(f"{runner} {name}")

    # Install commands (always needed in a Node project)
    for install_cmd in (
        "npm install", "npm i", "npm ci",
        "bun install", "bun i",
        "yarn install", "yarn",
        "pnpm install", "pnpm i"
    ):
        entries += _cmd_entries(install_cmd)

    return entries


# ── Gradle (Kotlin/Java) ───────────────────────────────────────────────────

def _gradle_permissions(project_path: Path) -> list[str]:
    has_gradle = (
        (project_path / "build.gradle.kts").exists()
        or (project_path / "build.gradle").exists()
        or (project_path / "settings.gradle.kts").exists()
        or any(project_path.rglob("build.gradle.kts"))  # monorepo / nested modules
    )
    if not has_gradle:
        return []
    entries: list[str] = []
    for base in ("./gradlew", "gradle"):
        entries += _cmd_entries(base)
    return entries


# ── Rust / Cargo ───────────────────────────────────────────────────────────

def _rust_permissions(project_path: Path) -> list[str]:
    if not (project_path / "Cargo.toml").exists():
        return []
    entries: list[str] = []
    for base in ("cargo build", "cargo test", "cargo check", "cargo run", "cargo clippy"):
        entries += _cmd_entries(base)
    return entries


# ── Go ─────────────────────────────────────────────────────────────────────

def _go_permissions(project_path: Path) -> list[str]:
    if not (project_path / "go.mod").exists():
        return []
    entries: list[str] = []
    for base in (
        "go build", "go test", "go run", "go vet", "go generate",
        "go mod download", "go get"
    ):
        entries += _cmd_entries(base)
    return entries


# ── Python ─────────────────────────────────────────────────────────────────

def _python_permissions(project_path: Path) -> list[str]:
    packaged = (
        (project_path / "pyproject.toml").exists()
        or (project_path / "setup.py").exists()
        or (project_path / "requirements.txt").exists()
    )
    if not (packaged or _has_python_sources(project_path)):
        return []
    # Edit only. Claude Code matches file permissions against Edit(path) rules
    # and not Write(path) ones, so a Write rule approved nothing and printed a
    # startup warning in every Python project that carried it.
    entries: list[str] = [
        "Edit(**/*.py)",
    ]
    if not packaged:
        return entries
    for base in (
        "uv run", "uv pip install", "uv sync",
        "poetry run", "poetry install",
        "pip install", "pip3 install"
    ):
        entries += _cmd_entries(base)
    return entries


def _has_python_sources(project_path: Path) -> bool:
    """Detect script-style Python repos that ship no packaging manifest.

    Bounded to the top two levels so this stays cheap on large checkouts.
    """
    if any(project_path.glob("*.py")):
        return True
    for child in project_path.iterdir():
        if child.name.startswith(".") or not child.is_dir():
            continue
        if any(child.glob("*.py")):
            return True
    return False


# ── Helpers ────────────────────────────────────────────────────────────────

def _cmd_entries(base: str) -> list[str]:
    """Return exact and wildcard-arg forms for a base command."""
    return [
        f"Bash({base})",
        f"Bash({base} *)",
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
