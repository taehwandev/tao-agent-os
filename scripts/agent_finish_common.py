"""Shared helpers for Tao Agent OS finish checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


SIGNAL_DISPLAY = {
    "SUCCESS": "\U0001f431\U0001f7e2 SUCCESS",
    "FAIL": "\U0001f431\U0001f534 FAIL",
}


from agent_command_runtime import (
    ANSI_RE,
    clean_output,
    parse_overall_record as parse_overall,
    run_command,
    vibeguard_command,
)


def add_gate_signal(
    gate_signals: list[dict[str, str]],
    signal: str,
    gate: str,
    status: str,
    evidence: str,
) -> None:
    gate_signals.append(
        {
            "gate": gate,
            "signal": signal,
            "status": status,
            "evidence": evidence,
        }
    )


def display_signal(signal: str) -> str:
    return SIGNAL_DISPLAY.get(signal, signal)


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def requires_retrospective(
    missed_gates: list[str],
    gate_policy_failures: list[str],
    finish_failures: list[str],
) -> bool:
    return bool(missed_gates or gate_policy_failures or finish_failures)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
