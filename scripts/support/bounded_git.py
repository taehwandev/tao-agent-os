"""One bound on how long a local Git read may take.

Owner: the local-process boundary for Git reads.
Allowed imports: standard-library subprocess and path utilities only.
Forbidden imports: workflow routing, agent lifecycle, gate policy, or any
caller's own error handling -- this module decides how long to wait, never
what a caller does with the answer.
Callers/tests: every lifecycle path that shells out to Git; coverage lives in
``tests/test_support_bounded_git.py``.
Verification: run that module's timeout and passthrough tests, which assert
the converted refusal keeps each caller's existing failure path.

Fifteen Git reads ran with no bound. They are local and fast until they are
not: an index lock held by another process, a filesystem that stops
answering, a repository on a network mount. One stalled check has already
held a run for forty-one minutes, and nothing said which command was waiting.

A timeout is reported as a failed run rather than raised. Every caller
already handles a non-zero Git result -- refusing the write, returning None,
raising its own error -- and those paths are the fail-closed ones. Raising a
new exception type through them would replace tested behaviour with an
unhandled error at exactly the moment the system is already degraded, so the
bound reuses the answer each caller has: this Git command did not succeed,
and here is why.
"""

from __future__ import annotations

import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


# Local reads: rev-parse, status, check-ignore, worktree list. A second of
# work is generous; ten leaves room for a cold cache without leaving a run to
# wait on something that is never going to answer.
GIT_READ_TIMEOUT_SECONDS = 10


def run_git(
    args: list[str],
    *,
    cwd: Path | str | None = None,
    timeout: float = GIT_READ_TIMEOUT_SECONDS,
    **keywords: Any,
) -> subprocess.CompletedProcess:
    """Run one Git command, and report exceeding the bound as its failure."""

    try:
        return subprocess.run(args, cwd=cwd, timeout=timeout, **keywords)
    except subprocess.TimeoutExpired as expired:
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=_empty_like(expired.stdout, keywords),
            stderr=_timeout_message(args, timeout, keywords),
        )


def _timeout_message(args: list[str], timeout: float, keywords: dict[str, Any]):
    """Name the command and the bound, in the caller's own stream type."""

    text = (
        f"git {' '.join(str(item) for item in args[1:])} exceeded the "
        f"{timeout:g}s local read bound and was stopped"
    )
    if keywords.get("stderr") is subprocess.DEVNULL:
        return None
    return text if keywords.get("text") or keywords.get("encoding") else text.encode()


def _empty_like(captured: Any, keywords: dict[str, Any]):
    """Match what the caller asked to capture, so unpacking cannot break."""

    if keywords.get("stdout") in (None, subprocess.DEVNULL):
        return None
    if keywords.get("text") or keywords.get("encoding"):
        return captured.decode() if isinstance(captured, bytes) else (captured or "")
    return captured if isinstance(captured, bytes) else b""

# A streaming read is a different shape and a different risk. `git diff
# --binary` over a large change is legitimately slow, so a latency budget here
# would refuse work that is only big; this bound exists to end a stall, not to
# cap a cost.
GIT_STREAM_TIMEOUT_SECONDS = 120


class GitStreamStalled(RuntimeError):
    """Raised when a streaming Git read outlives its stall bound."""


@contextmanager
def stream_stall_guard(
    process: subprocess.Popen,
    args: tuple[str, ...],
    timeout: float = GIT_STREAM_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Kill a streaming read that stops answering, and say which one it was.

    Checking the clock between chunks cannot help against the failure that
    matters: a producer that writes nothing leaves the reader blocked inside
    `read()`, where no check of ours runs. A timer that kills the process is
    what turns that into an ordinary end of stream, which every caller here
    already handles.
    """

    stalled = False

    def stop() -> None:
        nonlocal stalled
        stalled = True
        process.kill()

    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()

    def stalled_error() -> "GitStreamStalled":
        return GitStreamStalled(
            f"git {' '.join(str(item) for item in args)} exceeded the "
            f"{timeout:g}s stall bound and was stopped"
        )

    try:
        yield
    except BaseException as error:
        # Killing the producer makes the reader see a failed command, and that
        # generic message is what the caller would report -- losing the one
        # fact worth having, which command stopped answering. The stall wins.
        if stalled:
            raise stalled_error() from error
        raise
    finally:
        timer.cancel()
    if stalled:
        raise stalled_error()
