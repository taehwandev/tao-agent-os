"""Reuse Git answers inside one hook invocation, never across invocations.

Owner: the per-invocation memo for local Git reads.
Allowed imports: standard library only.
Forbidden imports: Git runners, lifecycle, gate policy -- callers compute the
answer; this module only decides whether an earlier answer may be returned.
Callers/tests: agent-hook opens a scope for `review` and `finish`;
agent_execution_capsule_state, agent_review_rules_inputs and
agent_continuation_store consult it. Coverage lives in
``tests/test_support_git_read_scope.py`` and the review call-count bound in
``tests/test_agent_review_git_calls.py``.
Verification: those tests, plus the review/finish lifecycle tests that assert
unchanged verdicts.

One review hook read the same worktree's HEAD twenty-three times and its
porcelain status eleven times. Nothing the hook does between those reads
touches tracked files -- it writes only ignored `.tao/` state -- so each repeat
paid ten to twenty milliseconds of process start for an answer it already had.

Two lifetimes are kept apart:

* stable answers (a checkout's top level, whether a path is ignored) cannot
  move while the hook runs and live for the whole scope;
* worktree answers (HEAD, status signature, content fingerprint) are only
  reused until `invalidate_worktree_reads()`. A hook calls it after anything
  it ran could have changed the tree -- validators, VibeGuard -- so a read that
  must observe the state after that work is fresh again.

Outside a scope every lookup misses, so any caller not opted in behaves
exactly as before.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Hashable, Iterator


_STABLE = "stable"
_WORKTREE = "worktree"
_MISSING = object()

_scope: dict[str, dict[Hashable, Any]] | None = None


@contextmanager
def git_read_scope(enabled: bool = True) -> Iterator[None]:
    """Open a fresh memo for one hook run; a nested scope starts empty too."""

    global _scope
    outer = _scope
    _scope = {_STABLE: {}, _WORKTREE: {}} if enabled else None
    try:
        yield
    finally:
        _scope = outer


def invalidate_worktree_reads() -> None:
    """Forget every worktree answer; stable answers remain valid."""

    if _scope is not None:
        _scope[_WORKTREE].clear()


def stable_read(key: Hashable, compute: Callable[[], Any]) -> Any:
    """Return a scope-long answer, computing it once. Errors are not cached."""

    return _read(_STABLE, key, compute)


def worktree_entry(key: Hashable) -> dict[str, Any] | None:
    """The mutable per-root worktree memo, or None outside a scope."""

    if _scope is None:
        return None
    return _scope[_WORKTREE].setdefault(key, {})


def _read(kind: str, key: Hashable, compute: Callable[[], Any]) -> Any:
    if _scope is None:
        return compute()
    bucket = _scope[kind]
    value = bucket.get(key, _MISSING)
    if value is _MISSING:
        value = compute()
        bucket[key] = value
    return value
