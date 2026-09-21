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

## Steps

1. On resume, verify the newest user request still matches the active objective.
2. Re-check working tree state before assuming previous context is current.
3. Re-read only the minimum files needed to rebuild confidence.
4. Continue from the next smallest useful step, not from the beginning.
5. If handing off, carry the evidence below with verification and residual risk.
6. If blocked, state the blocker, what was tried, and exactly what input or external change is needed.

## Handoff Evidence

A useful handoff includes:

- active objective, non-goals, authority/prohibitions, and alignment with the
  newest request
- target repo/worktree, branch/commit and applicable local instructions
- gate ledger state when a scripted route was used
- files changed (including uncommitted changes), inspected or intentionally left
  alone, and known unrelated user-owned changes
- commands run with pass/fail/skip result, what each proved, and evidence
  references; identify incomplete verification explicitly
- blockers, assumptions, decisions made, and decisions still needed
- decision pivots that affect the next action: rejected approach, reason and
  replacement, so the receiver does not re-propose it
- deliberately-unapplied follow-up items recommended for separate work, kept
  distinct from blockers, so scope discipline survives the handoff
- next smallest safe step and which document/card should govern it

Do not hand off with only a narrative summary when verification, changed files,
or gate status are known.

Keep a persistent note bounded to its most recent N entries, newest first,
with branch, changes and verification status in each. Replace obsolete recap
instead of appending the session; do not copy transcripts, tool output, source
or diffs. Preserve underlying evidence and use the session continuation protocol
for persistence, without another tracker, packet format or routine gate.

## Completed Cycle Boundary

After a verified cycle closes, its handoff may support a fresh thread if older
context is unnecessary. Use only an authorized, supported runtime transition;
never abandon unfinished work, pending commands or required checks to reset
context. If unavailable, continue in the current thread without claiming a reset
or making one a prerequisite. The receiver verifies state and evidence before
reuse. Thread age or summary length alone does not prove token savings.

## Stop If

- The newest user request changes the objective.
- The working tree changed in a way that makes the previous plan unsafe.
- Required verification or external state cannot be checked and the remaining risk is too high to continue.
