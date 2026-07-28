---
keyflow_id: sys_workflows_session_continuation_protocol_skill
status: review
type: human-reviewed-needed
tao_card_contract: strict
requires_docs:
  - workflows/skills/agent-handoff-continuation/SKILL.md
  - workflows/skills/scripted-agent-workflow/SKILL.md
---

# Session Continuation Protocol

Use when work must survive the death of the process doing it, and be picked up
by a later session or a different runtime.

## Use When

- A runtime session can end without running its own shutdown path: a closed
  terminal, `kill -9`, a crashed host, a revoked container.
- A second session must discover unfinished work in a checkout it did not start.
- A runtime is being wired to Tao Agent OS and needs the resume behavior other
  runtimes already have.
- A handoff must survive longer than the conversation that produced it.

Do not use this card for continuation inside one living session. Carrying an
objective across turns, context compaction, or a delegated worker is behavior,
not persistence, and belongs to
`workflows/skills/agent-handoff-continuation/SKILL.md`.

## Read

- `references/current-guidance.md` for the packet schema, storage, discovery,
  drift, and takeover contracts.
- `workflows/skills/agent-handoff-continuation/SKILL.md` for what state is worth
  carrying at all; this card only persists what that card selects.
- `workflows/skills/scripted-agent-workflow/SKILL.md` for the run lifecycle and
  the execution capsule this protocol must not duplicate.

## Decision Rule

Tao Agent OS owns the protocol; a runtime owns only its own wiring. Schema,
storage, discovery, drift verification, takeover, and the resume commands are
implemented once in the shared library. A runtime adapter supplies the
checkpoint content its agent already knows and invokes the shared commands.

An adapter that reimplements storage, takeover, or drift rules is a defect, not
a variation. Divergent resume semantics per IDE is the failure this card exists
to prevent.

## Two Records, Two Purposes

| Record | Holds | Boundary |
| --- | --- | --- |
| `execution-capsule.json` | trust, routing, gate binding | content-free, hashes and fingerprints only |
| `continuation.json` | goal, decisions, changed scope, verification, next step | project-local work summary, never synced |

Keep them separate. The capsule answers whether a worker may reuse a parent's
decisions; the continuation packet answers what a human or later agent should
do next. Merging them would either leak request content into the trust record or
strip the resume record of the content that makes it useful.

## Process

1. Write the initial checkpoint before mutation, bracket every bounded mutation
   with pre/post checkpoints, and refresh at lifecycle transitions; Stop is
   best-effort only.
2. On session start, discover unfinished packets for this checkout.
3. Verify HEAD, worktree, and required-doc state against the packet.
4. Reuse `agent_run_owner` and the registry claim transaction exactly: proven
   death releases immediately, live/unproven owners hold for the existing
   bounded policy, and only one resume generation wins.
5. Resume at the first unfinished checkpoint, never from the beginning.
6. Refuse and explain when verification fails; a fresh `start` is the recovery.

## Common Rationalizations

| Rationalization | Required response |
| --- | --- |
| "Write it on the Stop hook." | A shutdown-time write cannot describe a shutdown that never runs; write initial, pre/post-mutation, and lifecycle checkpoints while working. |
| "Warn on drift and continue." | Resuming onto changed bytes reuses decisions that may no longer hold; refuse and name what moved. |
| "Continuation needs its own takeover rule." | Two takeover rules in one system is a defect; reuse `agent_run_owner`. |
| "Just tell agents not to store prompts." | A prohibition an implementation can silently violate is not a boundary; bound the schema instead. |
| "Each IDE knows its own resume best." | Then each IDE has different resume semantics, which is the problem, not the solution. |

## Red Flags

- An adapter blocks a mutation for a condition that produces no checkpoint:
  missing storage, a missing module, an edit outside the project, or a pending
  whose tool never wrote. Blocking guards against a checkpoint that would
  misdescribe the mutation, so where none can exist it only removes the editor
  needed to fix the cause.
- A refusal is raised after the bytes already landed.
- A packet field accepts unbounded free text.
- A packet or aggregate prose payload exceeds the schema cap.
- A resume path reads a packet without verifying HEAD or worktree state.
- An adapter contains storage, drift, or takeover logic.
- A stale packet is taken over before the shared live-owner grace ceiling or
  unproven-owner fallback window permits it.
- The packet is written anywhere that is synced, published, or committed.

## Do Not

- Do not store prompts, responses, terminal output, logs, diffs, source content,
  environment values, or secrets in the packet.
- Do not duplicate execution-capsule fields into the continuation packet.
- Do not resume a route whose required documents changed under it.
- Do not let a runtime adapter define its own packet schema version.

## Stop If

- The current run is not eligible under the exact age-aware PR #6 owner policy.
- HEAD, worktree, or required-doc state does not match the packet.
- The packet schema version is newer than the reading implementation.
- The packet is found outside the project state directory.

## Verification

Before claiming this protocol works in a runtime, verify with negative controls:

- resume after `kill -9`, proving the packet survived a process that never ran
  its shutdown path
- interruption between a pre-mutation checkpoint and its post-mutation rewrite,
  proving unchanged bytes resume and changed bytes require reconciliation
- refusal after worktree drift, proving verification fails when it should
- refusal while a live owner is inside the shared grace ceiling, plus recovery
  after that ceiling, proving takeover follows one age-aware owner rule

- a first edit in a freshly cloned checkout, proving the run establishes its own
  storage precondition rather than inheriting one the fixtures wrote

A green resume test that never fails when the property is broken proves nothing.
Check what the fixture sets up before trusting it: a non-git workspace, or one
whose `.gitignore` the test wrote itself, passes every storage check while a
real checkout fails all of them.

## Report

Report the packet path, the checkpoint the resume started from, the drift
verification result, and whether takeover occurred and on what evidence.
