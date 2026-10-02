"""Choose a recorded task and navigate to its exact Codex conversation.

Owner: task-to-session navigation. Imports: work-card reads and subprocess.
Forbidden: session-file edits, work authorization, run resume, or auto-selection.
Caller: work-cards resume; tests: test_agent_work_card_resume.
"""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import run as _run
from uuid import UUID

from agent_work_cards import WORK_ID_RE, list_cards


def _session_id(card: dict) -> str:
    binding = card
    if not card.get("runtime") and not card.get("session_id"):
        # Older cards can use their own retained evidence; never guess latest.
        run_id = card.get("run_id") or card["work_id"]
        if not WORK_ID_RE.fullmatch(run_id):
            return ""
        try:
            evidence = Path(card["project"]) / ".tao" / "runs" / run_id / "preflight.json"
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            if payload.get("work", {}).get("id") != card["work_id"]:
                return ""
            binding = payload.get("runtime_session") or {}
        except (OSError, ValueError, AttributeError):
            return ""
    try:
        session = binding.get("session_id", "")
        if binding.get("runtime") == "codex" and str(UUID(session)) == session:
            return session
    except (ValueError, AttributeError, TypeError):
        pass
    return ""


def resume_task(project: Path) -> int:
    """Show task summaries, then run native resume only after explicit selection."""
    options = [(card, _session_id(card)) for card in list_cards(project, include_settled=True)]
    options = [(card, session) for card, session in options if session]
    if not options:
        raise ValueError("no tasks with a recorded Codex session in this repository")
    print("Codex tasks (choose a number; Enter cancels):")
    for number, (card, _session) in enumerate(options, 1):
        print(f"{number}. {card['summary']} [{card['state']}, {card['updated_at'][:10]}]")
    try:
        selection = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return 0
    if not selection:
        return 0
    if not selection.isascii() or not selection.isdecimal() or not 1 <= int(selection) <= len(options):
        raise ValueError("choose a number from the displayed task list")
    _card, session = options[int(selection) - 1]
    # Run in the selected repository, even when a card's old worktree is gone.
    # The conversation and native permission flow decide subsequent actions.
    return _run(["codex", "resume", session], cwd=project, check=False).returncode
