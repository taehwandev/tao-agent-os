"""Where a hook's wall-clock went, recorded as stage names and numbers.

Owner: the hook timing boundary.
Allowed imports: the standard library only, and only json, time and
(inside the writer) datetime -- nothing that reaches into the project.
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

import json
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # `Path` is only ever a value the caller hands us.
    from pathlib import Path


_PROCESS_START = time.monotonic()
_STAGES: dict[str, float] = {}
_SINK: "Path | None" = None


def set_timing_sink(path: "Path | None") -> None:
    """Name the file this process should append its timings to.

    Recording them into the hook result was not enough: that record is
    written only when a caller passes an output path, and the lifecycle's
    own review and finish invocations do not. The measurement existed and
    landed nowhere, which is the same as not measuring.

    The sink is a run-local file, so the numbers sit beside the evidence
    they describe and inherit its Git-ignored boundary.
    """

    global _SINK
    _SINK = path


def timing_sink() -> "Path | None":
    return _SINK


def append_recorded_stages(hook: str, status: str) -> None:
    """Append one line of names and durations, if a sink was named.

    Appended rather than replaced: one run holds several hooks, and the
    question the numbers answer -- where a lifecycle spent its time -- needs
    all of them.
    """

    if not _SINK:
        return
    # A hook that named no stage is not a free hook: `gate-batch` spends
    # seconds before it validates anything, and a lifecycle's wall clock is
    # only accountable if every process in it reports its own total.
    timings = recorded_stages() or {"hook_total": _hook_total_ms()}
    from datetime import datetime, timezone

    line = json.dumps(
        {
            "hook": hook,
            "status": status,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "timings": timings,
        },
        sort_keys=True,
    )
    try:
        _SINK.parent.mkdir(parents=True, exist_ok=True)
        with _SINK.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        # Measurement must never be the reason a hook fails.
        return


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
    timings["hook_total"] = _hook_total_ms()
    return timings


def _hook_total_ms() -> int:
    """Milliseconds since this module was imported, which starts a hook."""

    return round((time.monotonic() - _PROCESS_START) * 1000)


def reset_stages() -> None:
    """Clear the store and the sink; for tests, which run many hooks here."""

    global _SINK
    _STAGES.clear()
    _SINK = None
