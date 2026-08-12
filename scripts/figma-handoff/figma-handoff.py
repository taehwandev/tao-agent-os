#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from figma_cli import FigmaHandoffCli


if __name__ == "__main__":
    try:
        raise SystemExit(FigmaHandoffCli().run())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
