"""Run an external command for a hook, and read what it said.

Owner: the shared shape of a hook's subprocess result.
Allowed imports: the standard library only. Every lifecycle hook depends on
this, so it must not depend on any of them.
Callers/tests: ``agent-preflight``, ``agent_hook_runtime`` and
``agent_finish_common``, each of which re-exports what it needs so its own
callers are unchanged; coverage lives in
``tests/test_agent_command_runtime.py``.
Verification: run that module, and the preflight, review and finish suites that
consume these results.

These four functions existed three times over, once in each of those modules,
and the copies had already started to disagree. `parse_overall` is the warning:
two of the three return a `{status, line}` record and the third returns a bare
status string, and the two are not interchangeable -- the review gate compares
its result to `"Ready"`, so handing it the record would fail every audit that
passed. They are kept as two named functions here rather than merged, because
they are two functions; what was wrong was that they shared a name across
modules and a `Callable[[str], str]` annotation that described only one of
them.

`write_json` is deliberately not here. Its three versions differ in atomicity
and in an outbound-content assertion, so collapsing them is a behaviour change
rather than a de-duplication, and it needs its own review.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def clean_output(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "stdout": clean_output(result.stdout),
        "stderr": clean_output(result.stderr),
    }


def vibeguard_command(project: Path, rules: Path) -> list[str]:
    binary = shutil.which("vibeguard")
    if binary:
        return [binary, "audit", str(project), "--rules", str(rules)]
    return [
        "npx",
        "--yes",
        "@taehwandev/vibeguard@latest",
        "audit",
        str(project),
        "--rules",
        str(rules),
    ]


def parse_overall(output: str) -> str:
    """The audit verdict alone, for a caller that compares it to a verdict."""

    return parse_overall_record(output)["status"]


def parse_overall_record(output: str) -> dict[str, str]:
    """The verdict and the line it was read from, for a caller storing both.

    Evidence files keep the line as well as the status, so a reader can see
    what the audit actually printed rather than this module's reading of it.
    """

    for raw_line in clean_output(output).splitlines():
        line = raw_line.strip()
        if not line.startswith("Overall:"):
            continue
        value = line.split("Overall:", 1)[1].strip()
        if "Ready" in value:
            status = "Ready"
        elif "Needs review" in value:
            status = "Needs review"
        elif "Blocked" in value:
            status = "Blocked"
        else:
            status = value or "unknown"
        return {"status": status, "line": line}
    return {"status": "unknown", "line": ""}
