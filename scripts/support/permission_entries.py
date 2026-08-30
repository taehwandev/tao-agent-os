"""Build runtime permission entries for Tao Agent OS scripts."""

from __future__ import annotations

import json
from pathlib import Path

from support.setup_config_files import quote
from support.spill_permissions import obsolete_spill_helper_permission_commands as _obsolete_spill_helper_permission_commands
from support.spill_permissions import spill_helper_permission_commands as _spill_helper_permission_commands
from support.stable_launcher import stable_launcher_path


# The public Python commands that an agent may invoke directly. This is the
# union of the stable launcher's script targets and the standalone maintenance
# CLIs; import-only modules and tests are intentionally absent.
EXECUTABLE_ENTRYPOINTS = (
    "agent-entry.py",
    "agent-finish-check.py",
    "agent-hook.py",
    "agent-os-maintenance.py",
    "agent-os-status.py",
    "agent-os-watchdog.py",
    "agent-preflight.py",
    "agent_execution_capsule.py",
    "check_android_external_skill_manifest.py",
    "check_react_rn_external_skill_manifest.py",
    "claude_pretool_gate.py",
    "migrate_skill_bundles.py",
    "project-discover.py",
    "run_smoke_checks.py",
    "setup-agent-hooks.py",
    "setup-project-graphify.py",
    "workflow.py",
    "workflow_dispatch.py",
    "workflow_dispatch_launch.py",
)

# Historical names retained only so setup can remove obsolete permissions.
# They are not executable entrypoints and must never be offered to a runtime.
STALE_PERMISSION_ENTRYPOINTS = ("agent-docs-read.py", "agent_route_docs.py")


def claude_permission_entries(scripts_dir: Path, *, spill_available: bool = True) -> list[str]:
    entries: list[str] = []
    for command in _stable_launcher_commands("claude", include_spill_env=spill_available):
        _add_permission_command_entries(entries, "Bash", command)
    if spill_available:
        for command in _spill_helper_permission_commands("claude"):
            _add_permission_command_entries(entries, "Bash", command)
    for command in _common_tao_tool_commands():
        _add_permission_command_entries(entries, "Bash", command)
    return entries


def claude_legacy_permission_entries(scripts_dir: Path) -> list[str]:
    entries: list[str] = ["$defaults"]
    for command in _obsolete_stable_launcher_commands("claude"):
        _add_permission_command_entries(entries, "Bash", command)
    for command in _obsolete_spill_helper_permission_commands("claude"):
        _add_permission_command_entries(entries, "Bash", command)
    for script in _legacy_tao_python_scripts(scripts_dir):
        for command in _python_entrypoint_commands(script, "claude", scripts_dir.parent, include_legacy=True):
            _add_permission_command_entries(entries, "Bash", command)
    return entries


def claude_project_permission_entries(scripts_dir: Path, *, spill_available: bool = True) -> list[str]:
    # The stable launcher is a user-level machine path. Project settings stay
    # portable and rely on the user-level Claude permission installed above.
    entries: list[str] = []
    for subcommand in ("log", "status", "diff", "show"):
        entries.append(f"Bash(git -C * {subcommand} *)")
    entries.extend(_branch_listing_permission_entries())
    entries.extend(_worktree_permission_entries())
    for command in _common_tao_tool_commands():
        _add_permission_command_entries(entries, "Bash", command)
    return entries


def _branch_listing_permission_entries() -> list[str]:
    """Auto-approve reading branches, never deleting or renaming one.

    `Bash(git -C * branch *)` reads as "inspecting branches", but the matcher's
    `*` is any remainder, so it approved `git branch -D main` and `-M` with it.
    Refs live in the one Git directory every worktree shares, so that is the
    protected checkout's history, deleted without a prompt.

    A Bash rule matches a prefix and cannot express "except these flags", so the
    listing flags are named instead. They come from the gate's own read-only
    classifier: a second hand-written list here would be the copy that drifts,
    and the direction it drifts is toward approving more than the gate reads.
    """

    from claude_bash_git import BRANCH_READ_ONLY_OPTIONS

    entries = ["Bash(git -C * branch)"]
    entries.extend(
        f"Bash(git -C * branch {option}*)"
        for option in sorted(BRANCH_READ_ONLY_OPTIONS)
    )
    return entries


def _worktree_permission_entries() -> list[str]:
    """Cover the whole worktree root, because each worktree name is new.

    A task runs in its own linked worktree under `.tao/worktrees/<16-hex>`, and
    that directory name is generated fresh every time. A permission approved for
    one worktree therefore never matches the next, so the prompts never stop and
    the honest response is to switch permissions off -- which discards the
    protection along with the noise.

    The directory name comes from `agent_worktree_identity`, which is what the
    dispatcher uses; spelling it again here would be a second definition, and
    the copy nobody edits is the one that stops matching.

    The leading slash anchors the pattern at the directory holding the settings
    file -- the project root -- while a bare `.tao/...` is read relative to the
    working directory. The two agree only while the agent sits at the root, and
    the whole point of these rules is the moment it does not: from inside
    `<project>/.tao/worktrees/<hex>` the unanchored form asks for a second
    `.tao/worktrees` nested under the first, matches nothing, and every path
    prompts again -- the failure these entries exist to end.

    Reading, writing and entering only. Removing a worktree deletes work and
    stays a decision rather than a default.
    """

    from agent_worktree_identity import WORKTREE_DIRNAME

    root = f"/.tao/{WORKTREE_DIRNAME}"
    return [
        f"Read({root}/**)",
        f"Edit({root}/**)",
        f"Write({root}/**)",
        # A Bash rule matches command text, not a path, so it keeps the
        # spelling an agent actually types -- no leading slash to anchor.
        f"Bash(cd {root[1:]}/*)",
    ]


def agy_permission_entries(scripts_dir: Path, *, spill_available: bool = True) -> list[str]:
    entries: list[str] = []
    for command in _stable_launcher_commands("antigravity", include_spill_env=spill_available):
        _add_permission_command_entries(entries, "command", command)
    if spill_available:
        for command in _spill_helper_permission_commands("antigravity"):
            _add_permission_command_entries(entries, "command", command)
    for command in _common_tao_tool_commands():
        _add_permission_command_entries(entries, "command", command)
    return entries


def agy_legacy_permission_entries(scripts_dir: Path) -> list[str]:
    entries: list[str] = []
    for command in _obsolete_stable_launcher_commands("antigravity"):
        _add_permission_command_entries(entries, "command", command)
    for command in _obsolete_spill_helper_permission_commands("antigravity"):
        _add_permission_command_entries(entries, "command", command)
    for script in _legacy_tao_python_scripts(scripts_dir):
        for command in _python_entrypoint_commands(script, "antigravity", scripts_dir.parent, include_legacy=True):
            entries.append(f"command({command})")
            entries.append(f"command({command}:*)")
            entries.append(f"command({command} *)")
    for command in _spill_helper_permission_commands("antigravity"):
        entries.append(f"command({command})")
        entries.append(f"command({command}:*)")
        entries.append(f"command({command} *)")
    return entries


def codex_prefix_rule_entries(scripts_dir: Path) -> list[str]:
    entries = [_codex_prefix_rule([str(stable_launcher_path())])]
    for script in _tao_python_scripts(scripts_dir):
        path = str(script.resolve())
        entries.append(_codex_prefix_rule(["python3", path]))
        entries.append(_codex_prefix_rule(["python", path]))
        entries.append(_codex_prefix_rule([path]))
    return entries


def codex_legacy_prefix_rule_entries(scripts_dir: Path) -> list[str]:
    """Exact legacy rules setup may remove outside its managed block."""
    entries: list[str] = []
    for script in _legacy_tao_python_scripts(scripts_dir):
        path = str(script.resolve())
        entries.append(_codex_prefix_rule(["python3", path]))
        entries.append(_codex_prefix_rule(["python", path]))
        entries.append(_codex_prefix_rule([path]))
    return entries


def _tao_python_scripts(scripts_dir: Path) -> list[Path]:
    return [scripts_dir / name for name in EXECUTABLE_ENTRYPOINTS]


def _legacy_tao_python_scripts(scripts_dir: Path) -> list[Path]:
    """All paths emitted by the former recursive permission generator."""
    project_root = scripts_dir.parent
    exclude_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".wikimap"}
    scripts: list[Path] = []
    for path in project_root.rglob("*.py"):
        if any(part in exclude_dirs for part in path.parts):
            continue
        scripts.append(path)
    removed = [scripts_dir / name for name in STALE_PERMISSION_ENTRYPOINTS]
    return sorted({*scripts, *removed})


def _python_entrypoint_commands(
    script: Path,
    tool: str,
    project_root: Path | None = None,
    *,
    include_legacy: bool = False,
    include_spill_env: bool = True,
) -> list[str]:
    commands: list[str] = []
    env_prefixes = ("",)
    if include_spill_env:
        env_prefixes += (
            f"SPILL_AI_TOOL={tool} ",
            f"SPILL_TOKEN_USAGE_AI_TOOL={tool} ",
        )
    path_variants = (
        _legacy_entrypoint_path_variants(script, project_root)
        if include_legacy
        else _entrypoint_path_variants(script)
    )
    for path in path_variants:
        for prefix in env_prefixes:
            commands.append(f"{prefix}python3 {path}")
            commands.append(f"{prefix}python {path}")
            commands.append(f"{prefix}{path}")
    return commands


def _obsolete_stable_launcher_commands(tool: str) -> list[str]:
    """Launcher commands built from spellings setup no longer emits."""
    commands: list[str] = []
    env_prefixes = (
        "",
        f"SPILL_AI_TOOL={tool} ",
        f"SPILL_TOKEN_USAGE_AI_TOOL={tool} ",
        f"TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL={tool} ",
    )
    for path in _obsolete_stable_launcher_path_variants():
        for prefix in env_prefixes:
            commands.append(f"{prefix}{path}")
    return commands


def _stable_launcher_commands(tool: str, *, include_spill_env: bool = True) -> list[str]:
    commands: list[str] = []
    env_prefixes = ("",)
    if include_spill_env:
        env_prefixes += (
            f"SPILL_AI_TOOL={tool} ",
            f"SPILL_TOKEN_USAGE_AI_TOOL={tool} ",
            f"TAO_HOOK_SOFT_FAIL=1 SPILL_AI_TOOL={tool} ",
        )
    for path in _stable_launcher_path_variants():
        for prefix in env_prefixes:
            commands.append(f"{prefix}{path}")
    return commands


def _stable_launcher_path_variants() -> list[str]:
    """Canonical launcher path: one install-time resolved absolute form.

    Home-relative spellings are deliberately excluded because the managed
    runtime contracts use machine-resolved executable paths. Obsolete
    spellings are removed by the cleanup path, not regenerated here.
    """
    return [str(stable_launcher_path())]


def _obsolete_stable_launcher_path_variants() -> list[str]:
    """Home-relative launcher spellings that setup must now remove."""
    raw = str(stable_launcher_path())
    variants = [quote(raw), _double_quote(raw)]
    home = str(Path.home())
    if raw.startswith(home + "/"):
        suffix = raw[len(home) + 1:]
        variants += [
            f"~/{suffix}",
            f"$HOME/{suffix}",
            _double_quote(f"$HOME/{suffix}"),
            f"${{HOME}}/{suffix}",
            _double_quote(f"${{HOME}}/{suffix}"),
        ]
    return _dedupe(variants)


def _entrypoint_path_variants(script: Path) -> list[str]:
    return [str(script.resolve())]


def _legacy_entrypoint_path_variants(script: Path, project_root: Path | None = None) -> list[str]:
    raw = str(script.resolve())
    variants = [
        raw,
        quote(raw),
        _double_quote(raw),
        str(Path("scripts") / script.name),
    ]
    if project_root:
        try:
            rel = str(script.resolve().relative_to(project_root.resolve()))
            variants += [rel, quote(rel), _double_quote(rel)]
        except ValueError:
            pass
    home = str(Path.home())
    if raw.startswith(home + "/"):
        suffix = raw[len(home) + 1:]
        variants += [
            f"~/{suffix}",
            f"$HOME/{suffix}",
            _double_quote(f"$HOME/{suffix}"),
            f"${{HOME}}/{suffix}",
            _double_quote(f"${{HOME}}/{suffix}"),
        ]
    # Add $TAO_HOME variants for the scripts/ relative path.
    # TAO_HOME points to the Tao Agent OS root, so the relative
    # path from root is scripts/<name> — not the same suffix as from HOME.
    ap_rel = f"scripts/{script.name}"
    variants += [
        f"$TAO_HOME/{ap_rel}",
        _double_quote(f"$TAO_HOME/{ap_rel}"),
        f"${{TAO_HOME}}/{ap_rel}",
        _double_quote(f"${{TAO_HOME}}/{ap_rel}"),
    ]
    return _dedupe(variants)


def _add_permission_command_entries(entries: list[str], prefix: str, command: str) -> None:
    entries.append(f"{prefix}({command})")
    entries.append(f"{prefix}({command}:*)")
    entries.append(f"{prefix}({command} *)")


def _codex_prefix_rule(pattern: list[str]) -> str:
    encoded = ", ".join(json.dumps(item) for item in pattern)
    return f"prefix_rule(pattern=[{encoded}], decision=\"allow\")"


def _double_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _common_tao_tool_commands() -> list[str]:
    return [
        "vibeguard",
        "npx --yes @taehwandev/vibeguard",
        "npx --yes @taehwandev/vibeguard audit",
        "git status",
        "git status --short",
        "git status --short --untracked-files=all",
        "git diff",
        "git diff --check",
        "git log",
        "git log -n 1",
        "npm test",
        "pytest",
        "python3 -m pytest",
        "python -m pytest",
        "python3 -m unittest",
        "python -m unittest",
        "python3 -m unittest discover -s tests",
        "python -m unittest discover -s tests",
        "python3 -m py_compile",
        "python -m py_compile",
    ]
