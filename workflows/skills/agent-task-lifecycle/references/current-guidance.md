---
keyflow_id: sys_agent_task_lifecycle_workflow
status: stable
type: human-reviewed-needed
---

# Agent Task Lifecycle Workflow

Use for any agent task, including implementation, review, documentation,
debugging, planning, local tool inspection, and operational handoff.

This is the agent-level workflow. It decides which development, review, release,
or task-specific workflow to load next.

## Read

- `common/skills/agent-operating-skill/SKILL.md`
- `common/skills/task-intake-effort-routing/SKILL.md` before loading broad context or using
  deep effort
- `common/skills/stack-discovery/SKILL.md` when commands, dependencies, runtime, or framework
  APIs matter
- `common/skills/agent-editing-safety/SKILL.md`
- `common/skills/agent-interaction/SKILL.md` when a blocker question or approval is needed
- `common/skills/local-tools/SKILL.md` when commands, local tools, runtime usage telemetry,
  or metering evidence matter
- `common/skills/tool-failure-recovery/SKILL.md` when a command fails
- `common/skills/verification-policy/SKILL.md` when the task has a checkable result
- `common/skills/definition-of-done/SKILL.md` before final report, handoff, commit, release,
  or PR creation
- `index.md` to select only task-specific cards

## Agentic Run State

Tao Agent OS supports agentic coding by making the active agent's state,
delegation decision, evidence, and recovery point explicit. Runtime-specific
agents, subagents, or external launchers can use this state to continue,
delegate, review, and recover work without guessing what already happened.
This is a bounded state machine, not an autonomous polling loop.

Use this compact state model for recovery and handoff. The states describe the
work; they are not separate evidence gates for ordinary code tasks:

```text
intake -> oriented -> scoped -> acting -> verifying -> reviewing -> done
                                   |-> blocked -> retrospective -> scoped/acting
```

Record the current state, the next transition, the gate or command evidence
that justified the transition, the checkpoint or stop condition, and the
blocker status. If the task is interrupted, transferred, or fails a gate,
resume from the last evidenced state instead of reconstructing the work from
memory.

## Steps

1. Intake: identify the user goal, target project, task type, constraints, and
   whether the user asked for edits or only analysis. Classify request clarity
   and effort before loading broad context. If the user asked a direct question,
   answer it before starting work.
2. Local rules: read repo-local instructions before project-specific work.
3. Stack discovery: inspect manifests, lockfiles, wrappers, and repo scripts
   before choosing commands or framework-specific APIs.
4. Risk scan: mark touched surfaces such as secrets, external state, auth,
   billing, data, release, generated files, dependencies, local tools, runtime
   bridges, or usage metering evidence.
5. Start: for multi-step tasks, run `<TAO_LAUNCHER> start ... --request
   "<USER_REQUEST>"` once before manually choosing workflow cards. It performs
   routing and preflight; do not separately repeat workflow list, classify,
   route, or preflight after it succeeds. Direct `workflow.py route` and
   `agent-preflight.py` calls are lower-level diagnostic or compatibility
   fallbacks only. Use `index.md` only for simple answer-only work or an
   explicitly accepted fallback when the start hook cannot run.
6. Work surface and required docs: after start, read the always-required runtime
   instructions and the work-surface resolution contract. For code routes,
   resolve the change owner with bounded read-only repository inspection.
   Then read every route `required_docs` / `Read First` entry before
   editing, coding, or reviewing. Treat
   `reference_docs` as lazy context and open one only when the current task
   touches that concern, platform, gate, or verification path. Required-document
   selection is owned by the route; reading those documents is a direct agent
   responsibility rather than a separate confirmation gate.
7. Scope-change lifecycle: for ordinary code routes, `start` establishes scope
   A. Work inside A without intermediate gate or checkpoint calls. If the user
   or repository evidence expands the work to A+B, write one semantic decision
   checkpoint that updates the accepted scope and verification. Start a new
   route only when the project, authority, effect ceiling, or external target
   changes. At closeout, record the route's final tests and run review once.
   Record one short retrospective before finish; do not restore intermediate
   ceremony or manufacture a skill change when no reusable gap remains.
   Specialized routes such as product, publication, release, cleanup, and
   multi-agent work retain the gates they explicitly list.
8. Agentic run state: use a semantic checkpoint when work is interrupted,
   transferred, materially re-scoped, blocked, or delegated. Ordinary state
   transitions inside an unchanged scope do not need separate ledger records.
9. Global lessons: when preflight includes accepted or promoted lessons from
   `~/.tao/`, check whether any apply to the current task before
   editing or reviewing.
10. Alignment and cycle contracts: `start` owns the initial intake. Record a
    separate alignment or cycle gate only when a specialized route lists it.
    For ordinary code work, put changed assumptions and acceptance criteria in
    the one A+B scope checkpoint instead of repeating the intake before edits.

### Completion Evidence Fields

When a specialized route lists one of these finish gates, record the actual
decision. Ordinary code routes carry documentation, structure, boundary, and
side-effect conclusions in their single final review rather than separate
ledger entries. For listed gates:

- `source docs`: state which route `required_docs` were read directly, which
  source-of-truth documents were searched and read (or that none existed), and
  the task-specific takeaway applied before work. Structured records use the
  exact fields `required_docs`, `source`, and `takeaway`; the ledger fills
  `required_docs` from the active route so a self-reported empty manifest cannot
  bypass required documents.
- `documentation impact` and `documentation`: state the artifact class, the
  updated/created/unchanged/not-applicable decision, affected path or class,
  and why the durable behavior or acceptance criteria require that result.
- `ambiguity check`: use `blocker_status`, `assumptions`, and `decision`.
  `blocker_status` must be `none` or `resolved`; `decision` must be `proceed`.
- `alignment brief`: use `shared_understanding`, `possible_differences`,
  `assumptions`, and `checkpoint`. `checkpoint` must be
  `user_visible_before_edits`.
- `cycle contract` and `boundary plan`: state the owned and forbidden scope,
  nearest verification, stop condition, and handoff point.
- `work surface resolution`: use `result`, `owner`, `anchors`, `evidence`,
  `surface_paths`, `concerns`, `search_hops`, and `verification`. Only
  `result=resolved`, one to four evidence hops, an anchor-to-owner repository
  chain, and the nearest falsifying verification can pass.
- `retrospective check`: use `skills_checked`, `outcome`, and `observation`.
  `outcome` must be `no_reusable_gap`, `reusable_gap`, or `no_skill_used`;
  `observation` must be `not_needed`, `recorded`, or `deferred`, using the
  pairing defined by the retrospective-learning skill.
  For the common no-gap closeout, copy the exact pair
  `{"outcome":"no_reusable_gap","observation":"not_needed"}` instead of
  substituting near-miss natural-language values such as `no_change`, which is
  a different real status in the retrospective lifecycle.
12. Inspect: read existing code, docs, tests, commands, and current user changes
   before editing or judging.
13. Decide: make a reasonable assumption when safe; ask only when ambiguity
   changes result or risk.
14. Act: execute the scoped work with periodic progress updates for long tasks.
15. Verify: collect evidence with the narrowest reliable command or manual
    check. For usage telemetry, distinguish setup, label, hook, and diagnostic
    evidence from exact queued/imported usage event evidence.
16. Recover: when a command fails, diagnose stdout/stderr and make the smallest
    correction before retrying.
17. Ledger check: before finalizing, compare required gates against executed
    evidence and `SUCCESS`/`FAIL` state. Completion requires every required gate
    to be `🐱🟢 SUCCESS`. If any required gate is missing, blocked, failed, or
    lacks evidence, report `🐱🔴 FAIL` and follow missed-gate recovery in
    `workflows/skills/scripted-agent-workflow/SKILL.md`.
18. Definition of Done: before final report, handoff, commit, release, or PR
    creation, compare the final diff and evidence against
    `common/skills/definition-of-done/SKILL.md`.
19. Retrospective restart: when finish-check sets `retrospective_required`, run
    `workflows/skills/retrospective-learning/SKILL.md`, record the immediate correction
    plan, use or update the generated global lesson candidate when safe, apply
    safe scoped fixes, then restart at the first missed gate or same failed
    scope. The restarted attempt must cite or apply the plan.
20. Review: after meaningful edits, run the route's review hook and inspect the
    final diff, output, or artifact against the request and risks.
21. Retrospective check: when the active route requires it, inspect the skills
    actually used and record the structured result. Ordinary code and bounded
    local changes retain this short check. Stateless lookup and unchanged commit
    follow-ups do not create a new learning cycle. If a reusable gap remains,
    follow the retrospective-learning skill's conditional maintenance flow;
    otherwise record `no_reusable_gap` with `not_needed` and leave skills alone.
22. Finish: run `<TAO_LAUNCHER> finish` before final report, handoff,
    commit, or release. Use `agent-finish-check.py` directly only as a
    lower-level diagnostic or compatibility fallback when the finish hook is
    unavailable.
23. Report: state what changed or was found, verification status, skipped
    checks, and residual risk.

## Route To

- Product or feature delivery with PRD/ARD gates: `workflows/skills/product-architecture-delivery/SKILL.md`
- Request clarity, effort routing, or Grill-Me: `workflows/skills/request-triage/SKILL.md`
- Bounded work cycles and stop conditions: `workflows/skills/cycle-contract/SKILL.md`
- Lower-level coding work: `workflows/skills/development-cycle/SKILL.md`
- Feature behavior: `workflows/skills/feature-implementation/SKILL.md`
- Bug or regression: `workflows/skills/bugfix-debugging/SKILL.md`
- Refactor or cleanup: `workflows/skills/refactor-cleanup/SKILL.md`
- Release-sensitive work: `workflows/skills/release-readiness/SKILL.md`
- Final review or commit: `workflows/skills/review-and-commit/SKILL.md`
- Repeatable lesson after task, handoff, incident, or missed signal:
  `workflows/skills/retrospective-learning/SKILL.md`
- Long-running, interrupted, or transferred work: `workflows/skills/agent-handoff-continuation/SKILL.md`

## Stop If

- The target project cannot be identified safely.
- Required repo-local instructions or referenced task documents are unavailable.
- The user asked a direct question and it has not been answered.
- The task requires external-state changes without clear user approval.
- The current agentic run state, resume point, or responsible owner cannot be
  identified after interruption, delegation, or failed-gate recovery.
- The same blocker repeats and no meaningful progress is possible without user
  input or an external change.
