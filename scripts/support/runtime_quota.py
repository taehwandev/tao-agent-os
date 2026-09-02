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

# A gauge is read before its number is, which is the point: the shape says
# "plenty" or "nearly gone" without being parsed. Eight cells at eighth-block
# resolution is what makes 3% and 12% look different -- whole blocks round both
# to nothing, and nothing is exactly the state worth seeing.
GAUGE_WIDTH = 8
GAUGE_FULL = "█"
GAUGE_EMPTY = "░"
GAUGE_PARTIALS = " ▏▎▍▌▋▊▉"

# Between windows. Two spaces alone let a gauge and the next label read as one
# run of blocks.
SEPARATOR = "  │  "


def remaining_summary(rate_limits: Any) -> str:
    """`5h ██▊░░░░░  35%  │  7d ███████▌  94%` -- what is left, not what is spent.

    Runtimes report a window as the fraction it has consumed, which answers
    "how much have I burned". The question a status line exists for is the
    other one, so the subtraction happens here rather than in the reader's
    head, and the gauge draws the answer rather than restating it.
    """

    parts = []
    for minutes, used in read_windows(rate_limits):
        remaining = max(0, min(100, round(100 - used)))
        mark = "!" if remaining <= LOW_REMAINING_PERCENT else ""
        label = WINDOW_LABELS[minutes]
        # The percentage is padded so the tail stops jittering between 7%, 35%
        # and 100% on a line that is redrawn constantly.
        parts.append(f"{mark}{label} {gauge(remaining)} {remaining:>3}%")
    return SEPARATOR.join(parts)


def gauge(percent: int) -> str:
    """A fixed-width bar for a percentage, filled to what is left.

    A window with anything left never draws as empty, which matters because an
    exhausted window and one with a sliver remaining are the two states it is
    most important to tell apart. That holds by arithmetic at this width rather
    than by a special case: eight cells of eight give 64 steps, so 1% already
    rounds to one. A narrower gauge would lose it, and the test that pins the
    property is what would say so.
    """

    eighths = round(percent / 100 * GAUGE_WIDTH * 8)
    full, remainder = divmod(eighths, 8)
    cells = GAUGE_FULL * full
    if remainder and full < GAUGE_WIDTH:
        cells += GAUGE_PARTIALS[remainder]
    return cells.ljust(GAUGE_WIDTH, GAUGE_EMPTY)


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
