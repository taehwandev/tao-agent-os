"""Find a repository's other checkouts that hold Tao run state.

Owner: the bounded list of checkouts a session-wide settle may look at, the
content-free question of whether a settled run's checkout still holds
unfinished work, and whether removing a checkout would lose work or a run.
Allowed imports: the standard library.
Forbidden imports: the run registry and runtime-session modules; the caller
hands in each checkout and run id and does the settling itself. The registry
file is read here directly, without its locks, because a removal check only
reads and must fail towards keeping the checkout.
Callers/tests: agent_runtime_session.settle_superseded_session_runs,
claude_pretool_checkout_removal, agent_worktree_session.remove_worker_worktree;
tests/test_settle_superseded_session_runs.py,
tests/test_claude_pretool_checkout_removal.py.
Verification: those test modules and the runtime-session suite.

A session that leaves a run paused in the main checkout and moves on to a
linked worktree never settled the paused run: supersession only scanned the
checkout the new start ran in. Git already registers every checkout of one
repository, so asking it -- rather than walking the filesystem -- keeps the
scan to that repository, and only checkouts that already carry a run registry
are worth opening at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# A repository with more registered checkouts than this is not one a start
# should walk on every call; the excess is left to its own sessions.
MAX_CHECKOUTS = 64
REGISTRY_RELATIVE_PATH = Path(".tao") / "run-registry.json"
# agent_run_registry.SETTLED_RUN_STATES, repeated because that module may not
# be imported here; a test holds the two equal.
SETTLED_RUN_STATES = frozenset({"completed", "cancelled"})


def checkouts_with_run_state(project: Path) -> list[Path]:
    """Every other checkout of ``project``'s repository with a run registry."""

    try:
        result = subprocess.run(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    own = _resolved(project)
    found: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = _resolved(Path(line[len("worktree "):]))
        if candidate is None or candidate == own or candidate in found:
            continue
        if (candidate / REGISTRY_RELATIVE_PATH).is_file():
            found.append(candidate)
        if len(found) >= MAX_CHECKOUTS:
            break
    return found


def checkout_keeps_unfinished_work(checkout: Path, run_id: str) -> bool:
    """Whether settling ``run_id`` leaves work behind that someone must see.

    True when the checkout has uncommitted tracked changes, or the run's
    continuation packet records changed scope, remaining work or a pending
    mutation. An unreadable status counts as work kept: the answer only
    decides whether to say so, and saying so needlessly costs one line.
    """

    try:
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if status.returncode != 0 or status.stdout.strip():
        return True
    return _packet_records_unfinished_work(checkout, run_id)


def _packet_records_unfinished_work(checkout: Path, run_id: str) -> bool:
    packet_path = checkout / ".tao" / "runs" / run_id / "continuation.json"
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(packet, dict):
        return False
    work = packet.get("work") if isinstance(packet.get("work"), dict) else {}
    checkpoint = packet.get("checkpoint") if isinstance(packet.get("checkpoint"), dict) else {}
    return bool(
        work.get("changed_scope")
        or work.get("remaining_work")
        or checkpoint.get("mutation_pending") is not None
    )


def unsettled_run_states(checkout: Path) -> list[str]:
    """The states of runs in ``checkout``'s registry that still owe something.

    Anything but ``completed`` or ``cancelled`` -- running, paused, claiming,
    failed, blocked, interrupted, reconcile_required -- is somebody's open
    work. A registry that exists but cannot be read answers ``["unreadable"]``
    so a removal check keeps the checkout rather than guessing it is empty.
    """

    path = checkout / REGISTRY_RELATIVE_PATH
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs = payload.get("runs")
        if not isinstance(runs, list):
            raise ValueError("runs")
    except (OSError, ValueError, AttributeError):
        return ["unreadable"]
    states = {
        str(run.get("state"))
        for run in runs
        if isinstance(run, dict) and run.get("state") not in SETTLED_RUN_STATES
    }
    return sorted(states)


def checkout_removal_hazard(checkout: Path, *, count_changes: bool = True) -> str:
    """Why deleting ``checkout`` would lose something, or "" when it would not.

    Two things are lost with a checkout and no branch keeps them: changes
    git has not committed (modified or untracked, not ignored) and a Tao run
    that is not yet settled. A branch that looks merged says nothing about
    either -- a task branch with no commits of its own sits at an ancestor of
    main from the moment it is created -- so neither is inferred from it.
    A status git cannot produce is no evidence of work, and stays silent.
    ``count_changes=False`` is for a checkout declared disposable, whose files
    are scratch by definition; its open run still counts.
    """

    states = unsettled_run_states(checkout)
    if states:
        return f"it holds an unsettled Tao run ({', '.join(states)})"
    if not count_changes:
        return ""
    try:
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=normal"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if status.returncode == 0 and status.stdout.strip():
        return "it has uncommitted or untracked changes"
    return ""


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None
