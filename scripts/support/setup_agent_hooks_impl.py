"""Runtime hook setup entry flow for Tao Agent OS."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support.agy_setup import configure_agy
from support.claude_setup import configure_claude
from support.codex_permissions import merge_codex_worktree_roots
from support.codex_setup import merge_codex_stop_gate
from support.graphify_setup import (
    CANONICAL_SKILL_PATH,
    configure_global_graphify,
    configure_target_graphify,
    graphify_platforms_for_runtimes,
)
from support.graphify_contract import RUNTIME_BUNDLED_SKILL_DIR
from support.permission_entries import (
    claude_legacy_permission_entries,
    claude_project_permission_entries,
    codex_legacy_prefix_rule_entries,
    codex_prefix_rule_entries,
)
from support.project_type_detection import detect_project_permissions
from support.runtime_bridge import (
    merge_runtime_bridge,
    runtime_bridge_block,
    runtime_bridge_required_phrases,
)
from support.setup_config_files import (
    merge_codex_prefix_rules,
    merge_permissions_allow,
    print_results,
    quote,
)
from support.stable_launcher import ensure_stable_launcher, stable_launcher_path
from support.bounded_git import run_git
from agent_worktree_identity import worktree_root

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
DEFAULT_SPILL_SETUP_HELPER = (
    Path.home()
    / "Library/Application Support/Spill/adapters/setup/spill-token-metering-setup.mjs"
)
DEFAULT_GITHUB_DIR = Path.home() / "GitHub"

# Claude and Antigravity both let a status line run a command, which is how Tao
# draws the remaining quota there. Codex has a status line too -- `/statusline`
# configures it, and `status_line` stores it -- but it chooses from a fixed list
# of built-in items and offers no slot for a command of one's own, so there is
# nothing here for the installer to write. Saying so out loud is the point: the
# row was absent before, and an absent row reads as an oversight rather than as
# an answer.
CODEX_STATUS_LINE_STATUS = (
    "ok (codex has a status line, but /statusline selects from built-in items "
    "and takes no custom command; nothing to install)"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure AI runtime bridges, hooks, and permissions for Tao Agent OS."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any required hook is missing.",
    )
    parser.add_argument(
        "--target",
        metavar="PATH",
        help="Also install project-level permissions for this external project directory.",
    )
    parser.add_argument(
        "--github-projects",
        action="store_true",
        help="Also install project-level permissions for all ~/GitHub/* projects.",
    )
    graphify_group = parser.add_mutually_exclusive_group()
    graphify_group.add_argument(
        "--graphify",
        action="store_true",
        help="Also check Graphify local-graph readiness for --github-projects; --target enables it by default.",
    )
    graphify_group.add_argument(
        "--skip-graphify",
        action="store_true",
        help="Skip the default target-project Graphify readiness check (explicit opt-out).",
    )
    parser.add_argument(
        "--runtime",
        action="append",
        choices=("agy", "claude", "codex"),
        default=[],
        help="Limit user-level runtime bridge setup to one or more runtimes.",
    )
    args = parser.parse_args()

    if (args.graphify or args.skip_graphify) and not (args.target or args.github_projects):
        parser.error("--graphify/--skip-graphify requires --target or --github-projects")

    dry_run = args.dry_run or args.check
    selected_runtimes = set(args.runtime)
    spill_available = _has_spill_setup_helper()
    results: list[dict] = []
    configure_claude_runtime = _runtime_selected("claude", selected_runtimes) and _has_claude()
    configure_codex_runtime = _runtime_selected("codex", selected_runtimes) and _has_codex()
    configure_agy_runtime = _runtime_selected("agy", selected_runtimes) and _has_agy()
    launcher_configured = any(
        (configure_claude_runtime, configure_codex_runtime, configure_agy_runtime)
    )
    if launcher_configured:
        results += ensure_stable_launcher(ROOT, dry_run)

    if configure_claude_runtime:
        results += configure_claude(
            dry_run,
            root=ROOT,
            scripts_dir=SCRIPTS_DIR,
            launcher_path=stable_launcher_path(),
            spill_available=spill_available,
        )

    if configure_codex_runtime:
        results += configure_codex(dry_run, root=ROOT)

    if configure_agy_runtime:
        results += configure_agy(
            dry_run,
            root=ROOT,
            scripts_dir=SCRIPTS_DIR,
            launcher_path=stable_launcher_path(),
            spill_available=spill_available,
        )

    global_graphify_platforms = graphify_platforms_for_runtimes(
        selected_runtimes or {"agy", "claude", "codex"}
    )
    bundled_graphify = ROOT / RUNTIME_BUNDLED_SKILL_DIR
    if _should_configure_global_graphify(selected_runtimes) and (
        shutil.which("graphify")
        or (Path.home() / CANONICAL_SKILL_PATH).is_file()
        or (bundled_graphify / "SKILL.md").is_file()
    ):
        results += configure_global_graphify(
            Path.home(),
            global_graphify_platforms,
            dry_run,
            bundled_skill_dir=bundled_graphify,
        )

    results += configure_target_projects(
        args,
        selected_runtimes=selected_runtimes,
        dry_run=dry_run,
        launcher_configured=launcher_configured,
        spill_available=spill_available,
    )

    print_results(results, dry_run)
    fail_if_setup_incomplete(args, results)


def configure_target_projects(
    args: argparse.Namespace,
    *,
    selected_runtimes: set[str],
    dry_run: bool,
    launcher_configured: bool,
    spill_available: bool,
) -> list[dict]:
    """Configure explicit or bulk target repos without widening Graphify scope."""
    explicit_target = Path(args.target).expanduser().resolve() if args.target else None
    target_paths = [explicit_target] if explicit_target else []
    if args.github_projects:
        target_paths += _find_github_projects()

    results: list[dict] = []
    if target_paths and not launcher_configured:
        results += ensure_stable_launcher(ROOT, dry_run)

    configure_claude_target = _runtime_selected("claude", selected_runtimes) and _has_claude()
    configure_codex_target = _runtime_selected("codex", selected_runtimes) and _has_codex()
    # Never create Graphify skill copies or discovery links in target repos.
    graphify_platforms = graphify_platforms_for_runtimes(
        selected_runtimes or {"agy", "claude", "codex"}
    )
    for project_path in target_paths:
        if configure_claude_target:
            results += configure_external_project(
                project_path, SCRIPTS_DIR, dry_run, spill_available=spill_available
            )
        if configure_codex_target:
            config_target = Path.home() / ".codex" / "config.toml"
            status = merge_codex_worktree_roots(
                config_target,
                [worktree_root(project_path)],
                dry_run,
            )
            results.append(
                {
                    "tool": "codex",
                    "hook": f"permissions.worktrees.{project_path.name}",
                    "status": status,
                    "path": str(config_target),
                }
            )
        graphify_enabled = not args.skip_graphify and bool(
            args.graphify or (explicit_target and project_path == explicit_target)
        )
        if graphify_enabled:
            results += configure_target_graphify(project_path, graphify_platforms, dry_run)
    return results


def fail_if_setup_incomplete(args: argparse.Namespace, results: list[dict]) -> None:
    missing = [result for result in results if result["status"] == "missing"]
    if any(result["tool"] == "graphify" for result in missing):
        print(
            "\nGraphify setup is incomplete. Repair the shared ~/.tao skill and "
            "user-level runtime links, then read that skill, build the target graph "
            "under .agents/local/graphify-out, and rerun --check.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if args.check and missing:
        print(
            "\nRun `python3 scripts/setup-agent-hooks.py` to install missing bridges, hooks, or permissions.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _has_claude() -> bool:
    return (Path.home() / ".claude").is_dir() or bool(shutil.which("claude"))


def _runtime_selected(runtime: str, selected_runtimes: set[str]) -> bool:
    return not selected_runtimes or runtime in selected_runtimes


def _should_configure_global_graphify(selected_runtimes: set[str]) -> bool:
    """Every selected runtime consumes the same user-level Graphify bundle."""
    return not selected_runtimes or bool(selected_runtimes)


def _has_codex() -> bool:
    return (Path.home() / ".codex").is_dir() or bool(shutil.which("codex"))


def _has_agy() -> bool:
    gemini_home = Path.home() / ".gemini"
    return (
        gemini_home.is_dir()
        or bool(shutil.which("agy"))
        or bool(shutil.which("antigravity"))
        or bool(shutil.which("gemini"))
    )


def _spill_setup_helper_path() -> Path:
    override = os.environ.get("TAO_SPILL_HELPER_PATH", "")
    return Path(override) if override else DEFAULT_SPILL_SETUP_HELPER


def _has_spill_setup_helper() -> bool:
    return _spill_setup_helper_path().is_file()


def configure_codex(dry_run: bool, *, root: Path) -> list[dict]:
    bridge_target = Path.home() / ".codex" / "AGENTS.md"
    bridge_status = merge_runtime_bridge(
        bridge_target,
        dry_run,
        block=runtime_bridge_block(root, "Codex", "AGENTS.md"),
        required_phrases=runtime_bridge_required_phrases("Codex", "AGENTS.md"),
    )
    rules_target = Path.home() / ".codex" / "rules" / "default.rules"
    scripts_dir = root / "scripts"
    rules_status = merge_codex_prefix_rules(
        rules_target,
        codex_prefix_rule_entries(scripts_dir),
        dry_run,
        cleanup_entries=codex_legacy_prefix_rule_entries(scripts_dir),
    )
    hooks_target = Path.home() / ".codex" / "hooks.json"
    stop_command = (
        f"TAO_HOOK_SOFT_FAIL=1 {quote(str(stable_launcher_path()))} "
        "codex-stop-gate"
    )
    stop_status = merge_codex_stop_gate(hooks_target, stop_command, dry_run)
    config_target = Path.home() / ".codex" / "config.toml"
    permissions_status = merge_codex_worktree_roots(
        config_target,
        [worktree_root(root)],
        dry_run,
    )
    return [
        {
            "tool": "codex",
            "hook": "runtime_bridge.AGENTS",
            "status": bridge_status,
            "path": str(bridge_target),
        },
        {
            "tool": "codex",
            "hook": "rules.TaoAgentOSPython",
            "status": rules_status,
            "path": str(rules_target),
        },
        {
            "tool": "codex",
            "hook": "Stop_finish_gate",
            "status": stop_status,
            "path": str(hooks_target),
        },
        {
            "tool": "codex",
            "hook": "permissions.TaoWorkspace",
            "status": permissions_status,
            "path": str(config_target),
        },
        {
            "tool": "codex",
            "hook": "statusLine",
            "status": CODEX_STATUS_LINE_STATUS,
            "path": str(config_target),
        },
    ]


def configure_external_project(
    project_path: Path,
    scripts_dir: Path,
    dry_run: bool,
    *,
    spill_available: bool = True,
) -> list[dict]:
    """Install Tao Agent OS + project-type-specific permissions for an external project.

    Combines portable project-level worktree and verification entries with entries
    detected from the project's build toolchain (Swift,
    Node.js, Gradle, Rust, Go, Python) so that any parameter combination is
    covered after a single install run.
    """
    target = project_path / ".claude" / "settings.json"
    entries = claude_project_permission_entries(scripts_dir, spill_available=spill_available)
    entries += detect_project_permissions(project_path)
    status = merge_permissions_allow(
        target,
        entries,
        dry_run,
        cleanup_entries=claude_legacy_permission_entries(scripts_dir),
    )
    hook_label = f"permissions.project.{project_path.name}"
    exclude_status = ensure_local_claude_excluded(project_path, dry_run)
    return [
        {"tool": "claude", "hook": hook_label, "status": status, "path": str(target)},
        {
            "tool": "git",
            "hook": f"exclude.claude.{project_path.name}",
            "status": exclude_status,
            "path": str(project_path / ".git" / "info" / "exclude"),
        },
    ]


def ensure_local_claude_excluded(project_path: Path, dry_run: bool) -> str:
    """Keep generated project Claude permissions local unless already tracked."""
    git_dir = project_path / ".git"
    if not git_dir.is_dir():
        return "ok"
    if _git_path_matches(project_path, ["ls-files", "--error-unmatch", ".claude/settings.json"]):
        return "ok"
    if _git_path_matches(project_path, ["check-ignore", "-q", ".claude/settings.json"]):
        return "ok"

    exclude = git_dir / "info" / "exclude"
    text = exclude.read_text() if exclude.exists() else ""
    lines = text.splitlines()
    if ".claude/" in lines or ".claude/settings.json" in lines:
        return "ok"
    if dry_run:
        return "missing"

    exclude.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    exclude.write_text(text + ".claude/\n")
    return "installed"


def _git_path_matches(project_path: Path, args: list[str]) -> bool:
    result = run_git(
        ["git", "-C", str(project_path), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _find_github_projects() -> list[Path]:
    if not DEFAULT_GITHUB_DIR.exists():
        return []
    return sorted(
        p for p in DEFAULT_GITHUB_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
