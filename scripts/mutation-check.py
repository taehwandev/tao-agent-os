"""Judge a mutation by the test run's exit code, never by reading its output.

Owner: the hand-run verification boundary -- proving a test can fail.
Allowed imports: the standard library only. A tool that decides whether a check
is trustworthy must not depend on the code it is checking.
Forbidden imports: the workflow route, the agent lifecycle, and anything under
``scripts`` that a mutation could break.
Callers/tests: run by hand; coverage lives in ``tests/test_mutation_check.py``.
Verification: run that module, then this script against a spec whose mutants are
known dead and known alive.

A green test proves something works, not that the thing it names works. The
separation is a mutant: break the code on purpose and watch the test fail. The
technique is only as good as the judgement, and judgement by reading output is
where it fails.

Counting ``FAIL:`` lines calls a dead mutant a survivor, because a mutant that
breaks the module -- a SyntaxError, a RecursionError, an import error -- prints
a traceback and no ``FAIL:`` line at all. Reading ``$?`` after any other command
does the same for a different reason. Both happened in one session, in both
directions.

The exit code answers it. Non-zero means the suite could not pass, whatever the
reason, which is exactly what "the test would have caught this" means.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

KILLED = "KILLED"
SURVIVED = "SURVIVED"
UNAPPLIED = "NOT APPLIED"


def load_spec(path: Path) -> list[dict[str, Any]]:
    """Read a mutant list, refusing anything that is not one."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("spec must be a list of mutants")
    for index, mutant in enumerate(payload):
        if not isinstance(mutant, dict):
            raise ValueError(f"mutant {index} is not an object")
        for field in ("label", "file", "old", "new"):
            if not isinstance(mutant.get(field), str) or not mutant[field]:
                raise ValueError(f"mutant {index} is missing {field}")
    return payload


def apply_mutant(path: Path, old: str, new: str) -> str | None:
    """Replace exactly one occurrence, or refuse and change nothing.

    A mutation that matched twice would test two things at once, and one that
    matched nothing would report SURVIVED for a mutant that never existed --
    the most expensive false negative this tool can produce.
    """

    original = path.read_text(encoding="utf-8")
    if original.count(old) != 1:
        return None
    path.write_text(original.replace(old, new), encoding="utf-8")
    return original


def run_check(command: list[str], cwd: Path) -> int:
    """Return the exit code. Nothing here reads stdout or stderr."""

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode


def judge(mutant: dict[str, Any], command: list[str], root: Path) -> str:
    path = root / mutant["file"]
    original = apply_mutant(path, mutant["old"], mutant["new"])
    if original is None:
        return UNAPPLIED
    try:
        return KILLED if run_check(command, root) != 0 else SURVIVED
    finally:
        # Restoration is not optional. A mutant left in the tree is a defect
        # this tool introduced, so it is written back even when the run above
        # raised rather than returned.
        path.write_text(original, encoding="utf-8")


def check_command(test: str) -> list[str]:
    return [sys.executable, "-m", "unittest", test]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--test", required=True, help="unittest selector to run")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    try:
        mutants = load_spec(args.spec)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"unusable spec: {error}")
        return 2

    command = check_command(args.test)
    print(f"check: {' '.join(command)}")
    verdicts = []
    for mutant in mutants:
        verdict = judge(mutant, command, args.root)
        verdicts.append(verdict)
        print(f"{verdict:>11}  {mutant['label']}")

    survived = verdicts.count(SURVIVED)
    unapplied = verdicts.count(UNAPPLIED)
    print(f"{verdicts.count(KILLED)}/{len(verdicts)} killed")
    if unapplied:
        print(f"{unapplied} mutant(s) never applied: the `old` text was not found exactly once")
    return 1 if survived or unapplied else 0


if __name__ == "__main__":
    raise SystemExit(main())
