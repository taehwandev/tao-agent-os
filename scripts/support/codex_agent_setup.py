"""Install Tao's thin Codex roles without replacing user-owned agents.

Owner: Codex role setup; allowed imports: Python stdlib, managed_agent_files;
forbidden imports: workflow execution and runtime state; callers/tests:
setup_agent_hooks_impl, test_codex_agent_setup; verification: focused installer
and template tests.
"""

from __future__ import annotations

from pathlib import Path

from support.managed_agent_files import install_managed_agents


MANAGED_MARKER = "# Tao Agent OS managed Codex agent"
AGENT_NAMES = ("tao_explorer", "tao_worker", "tao_reviewer")


def _is_managed(content: bytes) -> bool:
    """Ownership is the marker as the exact first line."""

    lines = content.splitlines()
    return bool(lines) and lines[0] == MANAGED_MARKER.encode()


def install_codex_agents(root: Path, agents_dir: Path, dry_run: bool) -> list[dict]:
    """Install namespaced roles; source failures stop before any writes."""

    return install_managed_agents(
        template_dir=root / "templates" / "codex-agents",
        agents_dir=agents_dir,
        names=AGENT_NAMES,
        suffix=".toml",
        tool="codex",
        is_managed=_is_managed,
        dry_run=dry_run,
    )
