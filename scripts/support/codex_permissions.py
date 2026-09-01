"""Codex permission-profile setup owned by Tao Agent OS."""

from __future__ import annotations

import json
import re
from pathlib import Path


TAO_WORKSPACE_PROFILE = "tao-workspace"
_TABLE_HEADER = re.compile(r"(?m)^[ \t]*\[([^\]\n]+)\][ \t]*(?:#.*)?$")


def merge_codex_worktree_roots(
    target: Path,
    roots: list[Path],
    dry_run: bool,
) -> str:
    """Add exact Tao worktree roots without weakening Codex workspace protections."""

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    root_strings = list(dict.fromkeys(str(root.expanduser().resolve()) for root in roots))
    if _permission_ownership_conflicts(original, root_strings):
        return "missing"

    updated = _ensure_workspace_profile(original)
    updated = _ensure_worktree_roots(updated, root_strings)
    if updated == original:
        return "ok"
    if dry_run:
        return "missing"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return "installed"


def _permission_ownership_conflicts(text: str, roots: list[str]) -> bool:
    top_level = _top_level_text(text)
    if re.search(
        r"(?m)^[ \t]*(?:approval_policy|sandbox_mode)[ \t]*=",
        top_level,
    ):
        return True
    if _section(text, "sandbox_workspace_write"):
        return True

    default_assignments = _assignment_count(top_level, "default_permissions")
    defaults = _quoted_values(top_level, "default_permissions")
    if default_assignments != len(defaults):
        return True
    if len(defaults) > 1 or (defaults and defaults[0] != TAO_WORKSPACE_PROFILE):
        return True

    profile = _section(text, f"permissions.{TAO_WORKSPACE_PROFILE}")
    if profile:
        body = text[profile[0] : profile[1]]
        extensions = _quoted_values(body, "extends")
        if _assignment_count(body, "extends") != len(extensions):
            return True
        if len(extensions) > 1 or (extensions and extensions[0] != ":workspace"):
            return True

    roots_section = _section(
        text,
        f"permissions.{TAO_WORKSPACE_PROFILE}.workspace_roots",
    )
    if not roots_section:
        return False
    body = text[roots_section[0] : roots_section[1]]
    for root in roots:
        values = re.findall(
            rf"(?m)^[ \t]*{re.escape(_toml_key(root))}[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
            body,
        )
        if len(values) > 1 or (values and values[0] != "true"):
            return True
    return False


def _ensure_workspace_profile(text: str) -> str:
    updated = text
    if not _quoted_values(_top_level_text(updated), "default_permissions"):
        updated = f'default_permissions = "{TAO_WORKSPACE_PROFILE}"\n' + updated

    profile = _section(updated, f"permissions.{TAO_WORKSPACE_PROFILE}")
    if not profile:
        return _append_block(
            updated,
            "\n".join(
                (
                    f"[permissions.{TAO_WORKSPACE_PROFILE}]",
                    'description = "Workspace access plus the shared Tao Agent OS runtime."',
                    'extends = ":workspace"',
                )
            ),
        )
    if not _quoted_values(updated[profile[0] : profile[1]], "extends"):
        return _insert_section_line(updated, profile[1], 'extends = ":workspace"')
    return updated


def _ensure_worktree_roots(text: str, roots: list[str]) -> str:
    roots_section = _section(
        text,
        f"permissions.{TAO_WORKSPACE_PROFILE}.workspace_roots",
    )
    if not roots_section:
        block = [f"[permissions.{TAO_WORKSPACE_PROFILE}.workspace_roots]"]
        block += [f"{_toml_key(root)} = true" for root in roots]
        return _append_block(text, "\n".join(block))

    body = text[roots_section[0] : roots_section[1]]
    missing = [
        root
        for root in roots
        if not re.search(
            rf"(?m)^[ \t]*{re.escape(_toml_key(root))}[ \t]*=",
            body,
        )
    ]
    if not missing:
        return text
    lines = "\n".join(f"{_toml_key(root)} = true" for root in missing)
    return _insert_section_line(text, roots_section[1], lines)


def _quoted_values(text: str, key: str) -> list[str]:
    return re.findall(
        rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"([^"]+)"[ \t]*(?:#.*)?$',
        text,
    )


def _assignment_count(text: str, key: str) -> int:
    return len(
        re.findall(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=", text)
    )


def _top_level_text(text: str) -> str:
    first_table = _TABLE_HEADER.search(text)
    return text[: first_table.start()] if first_table else text


def _toml_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _section(text: str, name: str) -> tuple[int, int] | None:
    headers = list(_TABLE_HEADER.finditer(text))
    for index, header in enumerate(headers):
        if header.group(1).strip() != name:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        return header.end(), end
    return None


def _append_block(text: str, block: str) -> str:
    separator = "" if not text else "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{separator}{block}\n"


def _insert_section_line(text: str, index: int, line: str) -> str:
    before = text[:index]
    after = text[index:]
    prefix = "" if not before or before.endswith("\n") else "\n"
    suffix = "" if not after or after.startswith("\n") else "\n"
    return f"{before}{prefix}{line}\n{suffix}{after}"
