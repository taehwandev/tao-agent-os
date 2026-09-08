---
keyflow_id: minimal_workflow_prd
status: review
type: ai-generated
---

# Minimal Workflow

## Outcome

Complete the user's work with fewer agent-authored workflow calls, without
weakening effect authorization, project ownership, or truthful verification.
The first implementation slice is accepted: stateless lookup and resumable
blocked/interrupted termination. Local verification and commit reuse remain
planned. The architecture and migration contract are in [ard.md](ard.md).

## Observed problem

The legacy analysis route requires four gates, commit five, and workflow setup
twenty. Agents author gate fields, checkpoints, review prose and retrospective
records in addition to doing the work. Incorrect administrative arguments create
more calls and source reads. These counts describe legacy route manifests, not
measured token or latency savings.

The legacy Codex stop hook reacts to an active run by demanding closeout. Its next
continuation stops the turn if the run remains active. It does not distinguish a
truthful report of an external blocker from an attempted completion. The registry
has no explicit resumable blocked outcome; paused runs still count as active.

## Proposed user contract

| Work | Default workflow | Maximum explicit ceremony calls on the successful path |
| --- | --- | --- |
| Read-only lookup, explanation, status | Inspect direct evidence and answer; no durable task run | 0 |
| Local code, config or document change | Open bounded scope; edit; verify and close | 2 |
| Local commit after verified changes | Inspect exact staged unit; reuse valid checks; check readiness | 1 per distinct staged unit |
| External write, destructive action or deployment | Check exact target, effects and applicable approval at execution | One authority decision per distinct action; no universal call cap |

These budgets count agent-authored Tao administration, not useful source reads,
edits, tests, Git commands, required sandbox prompts or human decisions. A large
or risky task can require more substantive work, but not duplicated bookkeeping.
Read-only is an effect restriction, not a request keyword or a safety exemption.
Unclear effect/target boundaries require clarification before mutation.

## Keep

- Scope and project ownership checks, protected worktree rules and preservation
  of unrelated changes.
- Relevant tests, exact diff review, secret checks and verification freshness.
- Existing user authority for the identical action, target and effect ceiling.
  A materially changed target or applicable fresh-approval rule is checked again.
- Sandbox enforcement and production/deletion safeguards. Missing permission
  is never solved by changing policy or pretending an approval window exists.
- Runtime-owned metering and timing integration without new per-turn ceremonies.

## Remove from the default path

- Agent-authored source-doc receipts, alignment/state/cycle gate fields and
  manual ledgers for ordinary work. Keep useful decisions in one bounded brief.
- Mandatory retrospective, skill drafting/curation/maintenance and worker-split
  decisions on every task. Learning becomes a separately scoped improvement task.
- Repeated full audits, implementation intake and document routing solely because
  the user asks for a local commit of the same verified bytes.
- Forced continuation when a task is honestly blocked or interrupted. Such an
  outcome is not successful completion and does not permit publication.

## Acceptance scenarios

1. API field, configuration and function questions create no task registry entry,
   gate ledger, checkpoint or stop continuation; direct required rules still apply.
2. A bounded local edit needs no manually authored gate records. Real failed tests
   prevent a verified outcome; successful exit text alone is insufficient evidence.
3. A tool denial allows one accurate blocked response and preserves resumable scope.
   DNS failure alone is reported as name-resolution failure, not permission denial.
4. A blocked run with partial edits preserves those bytes and reports their state;
   it neither restores files automatically nor becomes commit-ready.
5. A matching staged snapshot reuses verification. Changed bytes invalidate only
   checks whose inputs changed; a changed HEAD or scope requires revalidation.
6. A changed external target or missing required fresh approval blocks that action.
   Repeating an already authorized identical action does not ask the same question.
7. An external timeout with unknown effects cannot be retried until reconciliation
   proves whether the original effect occurred.
8. Restart/resume binds the actual runtime session and project. It never invents a
   session id, adopts another session's run or replays an uncertain external write.

## Rollout boundary

Implement in bounded slices; do not disable every hook at once. The accepted
first slice covers ceremony-free read-only work and honest blocked exits,
then automatic local verification, then staged commit reuse. External authority
checks remain in force throughout. Measure explicit ceremony calls and document
selection in these scenarios; do not infer model latency or token savings.
