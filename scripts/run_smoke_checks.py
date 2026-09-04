#!/usr/bin/env python3
"""Run automated smoke checks to verify Tao Agent OS hooks and search library E2E."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Union

ROOT = Path(__file__).resolve().parents[1]


def run_command(cmd: List[str], cwd: Union[Path, str] = ROOT) -> subprocess.CompletedProcess:
    print(f"Running command: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_start_hook(temp_dir: str) -> None:
    print("\n--- Test 1: Start hook (triage command) ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "start",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--command",
        "triage",
        "--request",
        "재검증해줘 이제 코덱스가 마무리했네",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, (
        f"Start hook failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    print("SUCCESS: Start hook completed successfully.")

    # Start now claims a run-scoped evidence path; the legacy flat path remains
    # valid for direct preflight callers, so accept either location.
    state_dir = Path(temp_dir) / ".tao"
    candidates = [state_dir / "preflight.json", *state_dir.glob("runs/*/preflight.json")]
    assert any(path.exists() for path in candidates), "preflight.json was not created!"
    print("SUCCESS: preflight.json exists.")


def test_gate_validation_failures(temp_dir: str) -> None:
    print("\n--- Test 2: Gate validation failures (checking constraints) ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "gate",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--gate-name",
        "alignment brief",
        "--status",
        "SUCCESS",
        "--gate-evidence",
        "invalid brief without shared understanding phrase",
    ]
    result = run_command(cmd)
    assert result.returncode != 0, (
        "Gate should have failed validation due to missing required phrases!"
    )
    print("SUCCESS: Gate validation correctly rejected weak alignment brief.")


def test_gate_validation_success(temp_dir: str) -> None:
    print("\n--- Test 3: Gate validation success ---")
    gates_data = [
        {
            "gate": "source docs",
            "fields": {
                "source": "workflows/skills/request-triage/SKILL.md, references/current-guidance.md",
                "takeaway": "Identified inspection verb target rule.",
            },
            "evidence": "Checked request triage workflow rules.",
        },
        {"gate": "classify request", "evidence": "vague-action: no named target."},
        {"gate": "select effort", "evidence": "quick: short validation."},
        {
            "gate": "alignment brief",
            "evidence": "Shared understanding: Codex completed. Possible differences: none. Unsupported assumptions: none. User-visible checkpoint: pytest."
        },
        {
            "gate": "grill-me if needed",
            "evidence": "Grill-Me protocol /grilling session output: question=re-verify?, recommended answer=run pytest, user decision=execute, resolved/no-blocker outcome=passed."
        },
        {"gate": "product route re-entry", "evidence": "no new product work and no implementation proposed; triage only."},
        {"gate": "route recommendation", "evidence": "test"},
        {
            "gate": "retrospective check",
            "fields": {
                "skills_checked": "request-triage, retrospective-learning",
                "outcome": "no_reusable_gap",
                "observation": "not_needed",
            },
            "evidence": "skills checked: request-triage, retrospective-learning; outcome: no_reusable_gap; observation: not_needed",
        },
    ]
    # One batch, not one process per gate. The route's own start output tells
    # agents to record simultaneously-ready gates together, and this check ran
    # eight separate interpreters instead -- so it was slower than it needed to
    # be and, worse, it smoke-tested a path the guidance tells nobody to use.
    records = [
        {
            "gate": data["gate"],
            "status": "SUCCESS",
            "evidence": data["evidence"],
            "fields": data.get("fields", {}),
        }
        for data in gates_data
    ]
    batch = Path(temp_dir) / "smoke-gates.json"
    batch.write_text(json.dumps(records), encoding="utf-8")
    result = run_command(
        [
            sys.executable,
            str(ROOT / "scripts" / "agent-hook.py"),
            "gate-batch",
            "--project",
            temp_dir,
            "--rules",
            str(ROOT),
            "--gate-json",
            str(batch),
        ]
    )
    assert result.returncode == 0, f"Failed to record the gate batch:\n{result.stderr}"
    for data in gates_data:
        assert data["gate"] in result.stdout or "truncated" in result.stdout, (
            f"Gate {data['gate']} is missing from the batch result:\n{result.stdout}"
        )
    print("SUCCESS: All gates populated with valid evidence.")


def test_finish_hook(temp_dir: str) -> None:
    print("\n--- Test 4: Finish hook check ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "finish",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--allow-vibeguard-review",
        "E2E testing in temporary directory",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, f"Finish hook failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    print("SUCCESS: Finish hook approved completed triage workflow.")


def test_workflow_query() -> None:
    print("\n--- Test 5: Workflow search query check ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "workflow.py"),
        "query",
        "triage",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, f"Workflow query failed: {result.stderr}"
    assert "triage" in result.stdout.lower(), "Expected search results not found!"
    print("SUCCESS: Search query returned results correctly.")


def main() -> int:
    print("==================================================")
    print("Starting E2E Hook Smoke Checks")
    print("==================================================")
    with tempfile.TemporaryDirectory() as temp_dir:
        run_command(["git", "init"], cwd=temp_dir)
        run_command(["git", "config", "user.name", "Test User"], cwd=temp_dir)
        run_command(["git", "config", "user.email", "test@example.com"], cwd=temp_dir)

        dummy_file = Path(temp_dir) / "README.md"
        dummy_file.write_text("Dummy project", encoding="utf-8")
        run_command(["git", "add", "README.md"], cwd=temp_dir)
        run_command(["git", "commit", "-m", "Initial commit"], cwd=temp_dir)

        shutil.copy(
            str(ROOT / ".vibeguard.json"),
            str(Path(temp_dir) / ".vibeguard.json"),
        )

        try:
            test_start_hook(temp_dir)
            test_gate_validation_failures(temp_dir)
            test_gate_validation_success(temp_dir)
            test_finish_hook(temp_dir)
            test_workflow_query()
            print("\n==================================================")
            print("✅ All E2E smoke checks passed successfully!")
            print("==================================================")
            return 0
        except AssertionError as err:
            print(f"\n❌ Smoke check failed: {err}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
