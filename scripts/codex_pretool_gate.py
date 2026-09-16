#!/usr/bin/env python3
"""Run Tao's shared pre-mutation policy for a Codex PreToolUse event."""

from __future__ import annotations

import os
import runpy
from pathlib import Path


os.environ["TAO_PRETOOL_RUNTIME"] = "codex"
runpy.run_path(str(Path(__file__).with_name("claude_pretool_gate.py")), run_name="__main__")
