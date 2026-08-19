"""Where a hook's wall-clock went, recorded as stage names and numbers.

Owner: the hook timing boundary.
Allowed imports: standard-library time and typing only.
Forbidden imports: anything that could tempt a stage to record what it was
working on -- this module stores durations, never content.
Callers/tests: the lifecycle hooks and their shared result writer; coverage
lives in ``tests/test_support_stage_timing.py``.
Verification: run that module's accumulation, naming and payload tests.

Local checks measure under a second while whole tasks run for minutes, so the
cost is somewhere other than the checks -- but nothing recorded where, and a
plan built on a guess is how the last round of tuning started. Recording is
the step that makes the next reduction an argument from evidence.

The store is process-global on purpose: one hook invocation is one process,
so a stage does not have to be threaded through call chains that have no
other reason to know about timing. That keeps this change small enough to
land without touching the logic it measures.

Only a stage name and a duration are kept. No path, request, command, or
output goes in, which is what lets the numbers be written into evidence the
protocol already treats as content-free.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator


_PROCESS_START = time.monotonic()
_STAGES: dict[str, float] = {}


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Accumulate the time spent inside this block under ``name``.

    Accumulated rather than assigned: a stage that runs twice in one hook --
    the same status check before and after a review -- is one cost to the
    person waiting, and reporting only the second occurrence would understate
    it.
    """

    started = time.monotonic()
    try:
        yield
    finally:
        _STAGES[name] = _STAGES.get(name, 0.0) + (time.monotonic() - started)


def recorded_stages() -> dict[str, int]:
    """Return whole milliseconds per stage, plus the process total."""

    if not _STAGES:
        return {}
    timings = {name: round(seconds * 1000) for name, seconds in _STAGES.items()}
    timings["hook_total"] = round((time.monotonic() - _PROCESS_START) * 1000)
    return timings


def reset_stages() -> None:
    """Clear the store; for tests, which run many hooks in one process."""

    _STAGES.clear()
