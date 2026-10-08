"""Install Tao-managed runtime agent files without replacing user-owned agents.

Owner: provider-neutral managed agent file installation; allowed imports: Python
stdlib; forbidden imports: workflow execution and runtime state; callers/tests:
codex_agent_setup, claude_agent_setup, test_codex_agent_setup,
test_claude_agent_setup; verification: focused installer and template tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path


def install_managed_agents(
    *,
    template_dir: Path,
    agents_dir: Path,
    names: Iterable[str],
    suffix: str,
    tool: str,
    is_managed: Callable[[bytes], bool],
    dry_run: bool,
    source_suffix: str | None = None,
) -> list[dict]:
    """Install namespaced roles; source failures stop before any writes.

    `is_managed` decides ownership from file bytes. A destination that fails it
    is user-owned and reported as a conflict; symlinks and non-file paths are
    conflicts too, so setup never writes through or replaces them.
    `source_suffix` names templates differently from installed files.
    """

    templates = {}
    for name in names:
        source = template_dir / f"{name}{source_suffix or suffix}"
        content = source.read_bytes()
        if not is_managed(content):
            raise ValueError(f"{tool} agent template lacks Tao ownership marker: {source}")
        templates[name] = content

    rows = []
    directory_conflict = agents_dir.is_symlink() or (
        agents_dir.exists() and not agents_dir.is_dir()
    )
    for name, content in templates.items():
        target = agents_dir / f"{name}{suffix}"
        if directory_conflict or target.is_symlink():
            status = "conflict"
        elif target.exists() and not target.is_file():
            status = "conflict"
        else:
            current = target.read_bytes() if target.exists() else None
            if current == content:
                status = "ok"
            elif current is not None and not is_managed(current):
                status = "conflict"
            elif dry_run:
                status = "would_update" if current is not None else "missing"
            else:
                agents_dir.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                status = "installed"
        rows.append({
            "tool": tool, "hook": f"agents.{name}",
            "status": status, "path": str(target),
        })
    return rows
