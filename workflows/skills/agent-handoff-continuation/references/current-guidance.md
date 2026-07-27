---
keyflow_id: sys_agent_handoff_continuation_workflow
status: stable
type: human-reviewed-needed
---

# Agent Handoff Continuation Workflow

Use when work may continue across turns, interruptions, context compaction, another agent, or a handoff back to the user.

## Read

- `workflows/skills/agent-task-lifecycle/SKILL.md`
- `common/skills/verification-policy/SKILL.md`
- `common/skills/agent-editing-safety/SKILL.md`
- `workflows/skills/session-continuation-protocol/SKILL.md` when the work must
  survive the process itself ending, rather than only crossing turns
- active task-specific workflow from `index.md`

This card selects what state is worth carrying. Persisting that state so a later
session can rediscover it after a closed terminal or a killed process is a
separate contract, owned by the session continuation protocol card above.

## Continuation State

Maintain enough state for another agent or future turn to continue:

- current objective and non-goals
- target repo, branch, and relevant local instructions
- files changed, files inspected, and files intentionally left alone
- commands run and their pass/fail/skip result
- active blockers, assumptions, and unresolved decisions
- next smallest useful step

## Steps

1. On resume, verify the newest user request still matches the active objective.
2. Re-check working tree state before assuming previous context is current.
3. Re-read only the minimum files needed to rebuild confidence.
4. Continue from the next smallest useful step, not from the beginning.
5. If handing off, write a concise state summary with verification and residual risk.
6. If blocked, state the blocker, what was tried, and exactly what input or external change is needed.

## Handoff Evidence

A useful handoff includes:

- active objective and whether it is still aligned with the newest request
- gate ledger state when a scripted route was used
- files changed, files inspected, files intentionally left alone, and known
  unrelated user-owned changes
- commands run with pass/fail/skip result and what each proved
- blockers, assumptions, decisions made, and decisions still needed
- next smallest safe step and which document/card should govern it

Do not hand off with only a narrative summary when verification, changed files,
or gate status are known.

## Stop If

- The newest user request changes the objective.
- The working tree changed in a way that makes the previous plan unsafe.
- Required verification or external state cannot be checked and the remaining risk is too high to continue.
