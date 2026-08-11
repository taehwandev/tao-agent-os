"""Tell the global Tao Agent OS install apart from per-project runtime state.

``.tao`` names two unrelated things:

- per-project runtime state -- ``<repo>/.tao/preflight.json``, gate evidence,
  session markers;
- the global install -- ``~/.tao/bin/tao-hook``, ``~/.tao/tao-root``,
  ``~/.tao/projects.json``, ``~/.tao/claude-session-projects/``.

Every "is this a Tao Agent OS project?" check used to be ``(path / ".tao").is_dir()``,
so the home directory that hosts the global install always answered yes. That
made ``$HOME`` classify as a project, which let a harness path such as
``~/.claude/plans/x.md`` register ``$HOME`` as a session project and left the
Stop gate demanding a finish for ``$HOME`` -- a finish that cannot pass, because
auditing ``~`` dies on unreadable directories like ``~/.Trash``. An
unsatisfiable gate pushes the agent toward switching the gate off, so the
discriminator belongs here rather than in each gate.

The rule is the one the layout already implies: what is global stays global,
what is per-project stays per-project. A ``.tao`` directory is per-project state
exactly when it is not the global install directory.
"""

from __future__ import annotations

import os
from pathlib import Path


STATE_DIR_NAME = ".tao"
# Set by tests and by anyone relocating the global install; the same variable
# agent_global_lessons has always used to find lessons/skills state.
STATE_HOME_ENV = "TAO_STATE_HOME"
# Files the installer writes into the global directory and that no project's
# .tao ever contains. Identity is checked first; these are the fallback for a
# global install reached through a different HOME, a symlink, or a relocation
# that happened after this process read the environment.
GLOBAL_ONLY_MARKERS = ("tao-root", "projects.json", "bin/tao-hook")


def global_state_dir() -> Path:
    """The one directory that holds global install state."""
    override = os.environ.get(STATE_HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / STATE_DIR_NAME


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unreadable path
        return None


def is_global_state_dir(path: Path) -> bool:
    """True when this ``.tao`` directory is the global install, not project state."""
    resolved = _resolved(path)
    if resolved is None:
        return False
    global_resolved = _resolved(global_state_dir())
    if global_resolved is not None and resolved == global_resolved:
        return True
    return any((resolved / marker).exists() for marker in GLOBAL_ONLY_MARKERS)


def is_project_state_dir(path: Path) -> bool:
    """True when ``path`` is an existing ``.tao`` holding per-project state.

    Used by the opt-in checks in both Claude gates. Keeping it here stops the
    two gates from drifting into disagreeing about what a project is.
    """
    if not path.is_dir():
        return False
    return not is_global_state_dir(path)



def is_host_config_dir(path: Path) -> bool:
    """True when ``path`` is host configuration rather than a project checkout.

    Setup writes the managed runtime bridge into each runtime's own config
    directory, so ``~/.claude/CLAUDE.md`` and ``~/.codex/AGENTS.md`` always carry
    the opt-in token. Marker-file opt-in then reads those directories as projects
    and the edit gate demands a workflow lifecycle before touching, for instance,
    a session memory file. ``$HOME`` itself is already excluded; these are the
    same case one level down.

    The rule is the shape rather than a list of vendor names, so a runtime this
    file has never heard of is covered too. A hidden directory sitting directly
    in ``$HOME`` is configuration unless it is itself a Git checkout; ``.git``
    may be either a directory or a linked-worktree file, and both prove project
    ownership more strongly than the hidden-directory heuristic.
    """
    resolved = _resolved(path)
    home = _resolved(Path.home())
    if resolved is None or home is None:
        return False
    if (resolved / ".git").exists():
        return False
    return resolved.parent == home and resolved.name.startswith(".")



def prefer_git_root(candidates: list[Path]) -> Path | None:
    """Choose the project root from opt-in candidates ordered nearest-first.

    A repository keeps its agent documentation in a subdirectory, and that
    subdirectory carries its own ``AGENTS.md``. Marker opt-in alone therefore
    reads it as a project and it shadows the repository that owns it. Everything
    downstream then resolves against the wrong root at once: run evidence lands
    outside the repository, the VibeGuard scan root is no longer a Git checkout,
    and the skill catalog looks for project skills one level too deep.

    A project root is a repository root, so the nearest candidate that is one
    wins. Nearest rather than outermost, because a submodule or a linked
    worktree is its own project. When no candidate is a repository the nearest
    candidate still stands: a plain directory may opt in deliberately.
    """
    for candidate in candidates:
        # A linked worktree records ``.git`` as a file, a main checkout as a
        # directory. Both are repository roots.
        if (candidate / ".git").exists():
            return candidate
    return candidates[0] if candidates else None

def project_state_dir_target(project: Path) -> Path:
    """Where per-project state for ``project`` belongs."""
    return project / STATE_DIR_NAME


STATE_DIR_IGNORE = """\
# Tao Agent OS per-project runtime state. Local-only by construction.
#
# The continuation packet records what a run decided and what remains. It is a
# project-local work summary, so publishing it is a boundary violation rather
# than a mess -- and the storage layer proves local-only status by asking Git,
# not by trusting this directory's name. Without this file a fresh checkout
# answers "not ignored", the packet write is refused, and a feature that should
# merely be unavailable instead reads as a hard failure.
#
# Ignoring this file too keeps the whole state root invisible to the project.
/*
"""


def ensure_local_only_state_dir(project: Path) -> Path:
    """Create ``<project>/.tao`` already ignored by Git, and return it.

    Callers create this directory implicitly by writing evidence into it, which
    is why the ignore rule has to be established by whoever opens the run rather
    than by whoever happens to write first. An existing ignore file is left
    alone: a project that already declared its own rules for this directory --
    tracking a skills subtree, say -- must not have them silently replaced.
    """
    state_dir = project_state_dir_target(project)
    if is_global_state_dir(state_dir):
        # The global install is not project state; `project_scoped_state_error`
        # already refuses this target, and writing here would ignore the install.
        return state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    ignore_path = state_dir / ".gitignore"
    if not ignore_path.exists():
        ignore_path.write_text(STATE_DIR_IGNORE, encoding="utf-8")
    return state_dir


def project_scoped_state_error(project: Path) -> str:
    """Why ``project`` may not receive project-scoped state, or "" when it may.

    The distinction that matters is "new project, no state yet" versus "not a
    project at all". A fresh repo whose ``.tao`` does not exist must still be
    able to start, so absence of state is never the failure -- this only refuses
    a target whose ``.tao`` *is* the global install directory. That is the case
    that produced ``~/.tao/preflight.json``: project-scoped route state written
    into global state, which later gates then demanded a finish for.
    """
    state_dir = project_state_dir_target(project)
    if not is_global_state_dir(state_dir):
        return ""
    return (
        f"refusing to write project-scoped state to {state_dir}: that is the "
        "global Tao Agent OS install directory, not a project. Re-run with "
        "--project pointing at the repository you are working in."
    )
