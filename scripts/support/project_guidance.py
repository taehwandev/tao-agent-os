"""Refresh the known dispatch paragraph in existing managed project guidance.

Owner: explicit project-guidance installation; imports: pathlib, re and setup
file writer; forbidden: lifecycle or project source mutation. Caller: setup
entrypoint; tests: test_support_project_guidance.
"""

from pathlib import Path
import re

from support.setup_config_files import SetupConfigError, _atomic_write_bytes

_BEGIN = "<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->"
_END = "<!-- END MANAGED TAO AGENT OS ROUTING -->"
_OLD = re.compile(
    r"For a Codex leaf, use `dispatch --execute`\s+"
    r"only when the selected model, reasoning effort, sandbox, or required isolation\s+"
    r"differs from the parent\. When the selected profile and sandbox match and\s+"
    r"isolation is unnecessary, stay in the current process or use a native worker\s+"
    r"instead of launching a fresh Codex process\."
)


def refresh_project_guidance(project: Path, root: Path, *, dry_run: bool) -> dict:
    """Patch only the known stale paragraph, preserving all repo-owned content."""
    path = project.expanduser().resolve() / "AGENTS.md"
    if not path.is_file():
        raise SetupConfigError(f"project guidance is unavailable: {path}")
    original = path.read_text(encoding="utf-8")
    if original.count(_BEGIN) != 1 or original.count(_END) != 1:
        raise SetupConfigError(f"expected one managed routing block in {path}")
    start, end = original.index(_BEGIN), original.index(_END)
    if end < start:
        raise SetupConfigError(f"invalid managed routing block in {path}")
    template = (root / "templates/repo-agents-routing.md").read_text(encoding="utf-8")
    prefix = "For a Codex leaf, use `dispatch --execute`"
    replacement = template[template.index(prefix):template.index("\nIf the direct question", template.index(prefix))]
    block = original[start:end]
    updated_block, count = _OLD.subn(lambda _match: replacement, block)
    if count > 1 or (not count and " ".join(replacement.split()) not in " ".join(block.split())):
        raise SetupConfigError(f"unrecognized dispatch guidance in {path}; left unchanged")
    status = "ok"
    if count:
        status = "missing" if dry_run else "installed"
        if not dry_run:
            target = path.resolve()
            payload = original[:start] + updated_block + original[end:]
            _atomic_write_bytes(target.with_name(target.name + ".tao-backup"), original.encode("utf-8"), target)
            _atomic_write_bytes(target, payload.encode("utf-8"), target)
    return {"tool": "project", "hook": "guidance.dispatch", "status": status, "path": str(path)}
