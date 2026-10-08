"""Install Tao's thin Codex roles without replacing user-owned agents.

Owner: Codex role setup; allowed imports: Python stdlib; forbidden imports:
workflow execution and runtime state; callers/tests: setup_agent_hooks_impl,
test_codex_agent_setup; verification: focused installer and template tests.
"""

from __future__ import annotations

from pathlib import Path


MANAGED_MARKER = "# Tao Agent OS managed Codex agent"
AGENT_NAMES = ("tao_explorer", "tao_worker", "tao_reviewer")


def install_codex_agents(root: Path, agents_dir: Path, dry_run: bool) -> list[dict]:
    """Install namespaced roles; source failures stop before any writes."""

    templates = {}
    for name in AGENT_NAMES:
        source = root / "templates" / "codex-agents" / f"{name}.toml"
        content = source.read_bytes()
        if not content.splitlines() or content.splitlines()[0] != MANAGED_MARKER.encode():
            raise ValueError(f"Codex agent template lacks Tao ownership marker: {source}")
        templates[name] = content

    rows = []
    directory_conflict = agents_dir.is_symlink() or (
        agents_dir.exists() and not agents_dir.is_dir()
    )
    for name, content in templates.items():
        target = agents_dir / f"{name}.toml"
        if directory_conflict or target.is_symlink():
            status = "conflict"
        elif target.exists() and not target.is_file():
            status = "conflict"
        else:
            current = target.read_bytes() if target.exists() else None
            if current == content:
                status = "ok"
            elif current is not None and (
                not current.splitlines()
                or current.splitlines()[0] != MANAGED_MARKER.encode()
            ):
                status = "conflict"
            elif dry_run:
                status = "would_update" if current is not None else "missing"
            else:
                agents_dir.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                status = "installed"
        rows.append({
            "tool": "codex", "hook": f"agents.{name}",
            "status": status, "path": str(target),
        })
    return rows
