#!/usr/bin/env python3
"""Claude Code's entry point to the shared Tao status line.

Claude Code renders a status line by running this on every draw and printing
whatever it writes, handing it the session as JSON on stdin. Everything the line
is made of lives in `support.statusline`, which Antigravity renders from too;
what belongs here is only how this runtime calls it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.statusline import color_enabled, render  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the Tao status line for Claude Code."
    )
    parser.add_argument(
        "--chain",
        default="",
        help="shell command that previously held the status line; it is given "
        "the same payload and its output is kept",
    )
    arguments = parser.parse_args(argv)

    line = render(_read_stdin(), arguments.chain, color=color_enabled())
    if line:
        sys.stdout.write(line)
    return 0


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
