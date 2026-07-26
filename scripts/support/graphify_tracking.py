"""Graphify project-input policy helpers."""

from __future__ import annotations

import re
from pathlib import Path

from support.graphify_contract import GRAPHIFY_INPUT_BLOCK


SUPERSEDED_INPUT_BLOCK_PATTERN = re.compile(
    r"# (?P<name>[a-z0-9-]+)-graphify-inputs:start[\s\S]*?"
    r"# (?P=name)-graphify-inputs:end\n?",
    re.MULTILINE,
)


def install_tracking_policies(project_path: Path) -> list[dict[str, str]]:
    """Compatibility facade: Graphify now owns only its input policy."""

    return [install_graphify_input_policy(project_path)]


def install_graphify_input_policy(project_path: Path) -> dict[str, str]:
    path = project_path / ".graphifyignore"
    status = write_managed_block(path, GRAPHIFY_INPUT_BLOCK)
    return {
        "tool": "graphify",
        "hook": "tracking.install.graphify-inputs",
        "status": status,
        "path": str(path),
    }


def write_managed_block(path: Path, block: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = original = path.read_text(encoding="utf-8") if path.exists() else ""
    begin = block.splitlines()[0]
    end = block.splitlines()[-1]
    content = SUPERSEDED_INPUT_BLOCK_PATTERN.sub(
        lambda match: match.group(0) if match.group(0).startswith(begin) else "",
        content,
    )
    cursor = 0
    found = False
    fragments: list[str] = []
    while True:
        start = content.find(begin, cursor)
        if start < 0:
            fragments.append(content[cursor:])
            break
        finish = content.find(end, start + len(begin))
        if finish < 0:
            fragments.append(content[cursor:])
            break
        fragments.append(content[cursor:start])
        if not found:
            fragments.append(block)
            found = True
        cursor = finish + len(end)
    if found:
        updated = "".join(fragments)
    else:
        separator = "" if not content else ("" if content.endswith("\n\n") else "\n")
        updated = content + separator + block + "\n"
    if updated == original:
        return "ok"
    path.write_text(updated, encoding="utf-8")
    return "installed"
