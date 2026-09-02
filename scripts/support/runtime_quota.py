"""How much of a runtime's budget is left, read from what the runtime says.

Claude Code and Codex both report usage the same way: a set of rolling windows,
each stating the fraction it has consumed. This module turns that into the
number an operator actually acts on -- how much is left -- and it is kept apart
from any one runtime's status line so the second surface to need it does not
arrive with a second parser.

Nothing here reaches for the value. The runtime hands it over as part of a
payload it was already sending, so a reading is either present in that payload
or absent, never fetched.
"""

from __future__ import annotations

from typing import Any


# Below this, the window is worth looking at rather than glancing past.
LOW_REMAINING_PERCENT = 15

# The windows both runtimes report, shortest first. A window this map does not
# name is skipped rather than guessed at: an unlabelled percentage is worse than
# no percentage, because the reader cannot tell which budget it is about.
WINDOW_LABELS = {300: "5h", 10080: "7d"}


def remaining_summary(rate_limits: Any) -> str:
    """`5h 35% 7d 94%` -- what is left, not what is spent.

    Runtimes report a window as the fraction used, which answers "how much have
    I burned". The question a status line exists for is the other one, so the
    subtraction happens here rather than in the reader's head.
    """

    parts = []
    for minutes, used in read_windows(rate_limits):
        remaining = max(0, min(100, round(100 - used)))
        mark = "!" if remaining <= LOW_REMAINING_PERCENT else ""
        parts.append(f"{mark}{WINDOW_LABELS[minutes]} {remaining}%")
    return " ".join(parts)


def read_windows(rate_limits: Any) -> list[tuple[int, float]]:
    """Every window this module can name, as (minutes, percent used).

    The exact spelling belongs to the runtime and has changed before, so a
    window is recognised by the fields it must have rather than by one
    hardcoded layout. Both an object keyed by window name and a list of entries
    are read.
    """

    if isinstance(rate_limits, dict):
        entries = list(rate_limits.items())
    elif isinstance(rate_limits, list):
        entries = [
            (str(entry.get("kind") or entry.get("window") or ""), entry)
            for entry in rate_limits
            if isinstance(entry, dict)
        ]
    else:
        return []

    windows: dict[int, float] = {}
    for key, value in entries:
        if not isinstance(value, dict):
            continue
        used = _used_percent(value)
        if used is None:
            continue
        minutes = window_minutes(str(key), value)
        # Skipping on the label rather than on the length is what keeps a
        # runtime that adds an hourly window from becoming a lookup error on
        # every redraw: a stated length is believed, and an unlabelled one has
        # nowhere to be drawn.
        if minutes not in WINDOW_LABELS:
            continue
        # Two spellings of the same window would otherwise both be drawn. The
        # later entry wins, matching how a payload restates a corrected value.
        windows[minutes] = used
    return sorted(windows.items())


def window_minutes(key: str, value: dict[str, Any]) -> int | None:
    """A stated length wins; otherwise the window's own name says it."""

    stated = _number(value.get("window_minutes"))
    if stated is not None and stated > 0:
        return round(stated)
    name = key.lower()
    if "five_hour" in name or "5_hour" in name or name in {"session", "primary"}:
        return 300
    if "seven_day" in name or "7_day" in name or "week" in name or name == "secondary":
        return 10080
    return None


def _used_percent(value: dict[str, Any]) -> float | None:
    for name in ("used_percentage", "used_percent", "percent", "utilization"):
        number = _number(value.get(name))
        if number is not None:
            return number
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
