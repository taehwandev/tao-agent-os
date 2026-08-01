---
keyflow_id: sys_multi_agent_collaboration_workflow
status: stable
type: human-reviewed-needed
---

# Multi-Agent Collaboration

Use when work is split across subagents, multiple agents, delegated roles,
parallel tasks, or a builder/verifier pair.

## Roles

Product owner agent:

- owns user problem, feature boundaries, user-facing behavior, success criteria,
  and non-goals
- should not prescribe low-level implementation unless product-critical

Architecture agent:

- owns module boundaries, contracts, data models, permission model, failure
  modes, dependencies, and verification strategy
- should not accept behavior that cannot be verified

Builder agent:

- implements the assigned slice only
- keeps the repo buildable
- does not broaden scope silently
- preserves user-owned changes

Verifier agent:

- reviews the patch against request, PRD, ARD, repo-local rules, and risk cards
- checks behavior, tests, failure states, and residual risk
- leads with findings

## Gates

For non-trivial feature work, use this sequence unless repo-local workflow says
otherwise:

```text
intake -> ambiguity gate -> PRD -> ARD -> task breakdown -> agent briefs -> implementation -> review -> verification -> closeout
```

Use `workflows/skills/product-architecture-delivery/SKILL.md` for the PRD, ARD, and commit
readiness gates.

## Parallel Work

Subagents or agents may edit in parallel only when write scopes are disjoint,
with one carve-out: overlapping `owned_scope` is allowed only when both
overlapping workers declare `isolation: "worktree"` and each runs inside its
own real `git worktree` (see the worktree-isolation exception under
"Delegation Decision Record").
When a scripted route is used, consult `parallel_execution.phases` before
spawning workers. A `conditional_parallel` worker phase is permission to look
for a split, not permission to skip roles, write scopes, briefs, or integration
review.

Rules:

- The lead agent should actively look for safe subagent/parallel slices when a
  task has independent surfaces. Do not wait for the user to request parallel
  agents when the split is obvious and low risk.
- Treat two or more meaningful independent slices as the automatic-delegation
  threshold when the runtime exposes workers and the contract, scopes,
  integration owner, and focused checks are already stable. Explicit user
  multi-agent wording is not required and its absence is not a serial reason.
- A `multi-agent` route's worker phase is parallel by contract after roles,
  scopes, briefs, and the delegation plan are valid. Other code routes remain
  conditional until the lead records the eligibility decision.
- Assign each writer explicit owned files or modules.
- Assign explicit forbidden files or modules when overlap is likely.
- Do not assign two writers to the same file, unless both writers declare
  `isolation: "worktree"` and each runs in its own real `git worktree` (the
  worktree-isolation carve-out described under "Delegation Decision Record").
- Serialize architecture, shared model, migration, dependency, generated-file,
  and release-config changes.
- If one task depends on an undefined model or contract from another task,
  define the contract first or serialize the work.
- Keep implementation briefs narrow enough that a worker can finish without
  changing another worker's contract, route, schema, state model, or config.
- Review and integrate parallel changes before broad verification.

Shared-checkout build discipline:

When parallel workers share one checkout and the build tool holds global
locks, daemons, or shared caches (Gradle is the canonical case), workers only
write files. Workers never run build or VCS commands — parallel invocations
corrupt lock and daemon state. Each worker reports its changed-file list plus
its verification requirements. After all workers return, the lead runs the
needed module-level compile and test commands once, merges the results, and
greps the integrated tree for residual violations.

Good splits:

- domain logic versus UI wiring after the model contract is stable
- docs update versus isolated source change
- provider/adapter implementation versus tests for a separate helper

Bad splits:

- two agents editing the same view, route, reducer, schema, or config file in a
  shared checkout (allowed only under the worktree-isolation carve-out, where
  both workers declare `isolation: "worktree"` and each runs in its own real
  `git worktree`)
- one agent changing shared models while another consumes the unstable shape
- broad refactors mixed with feature work across the same modules
- multiple agents adding exports to the same package barrel, public API, design
  system surface, generated client, migration chain, or release manifest

## Cross-Repo Product Work

When one product spans several repos, keep a lead decision separate from worker
execution:

- Choose the primary repo from the final user path or acceptance result.
- Treat another repo as secondary until a checkpoint proves it must be written.
- Use `primary-led secondary read` when the secondary repo only confirms a
  contract, route, schema, config, docs, or platform behavior.
- Use `primary-led secondary write` only for a small bounded secondary change
  with explicit write scope and cross-repo verification.
- Use `multi-session` when both repos need meaningful implementation, their own
  tests, or separate commits. The lead owns the shared contract, ordering,
  integration review, and final verification.

Do not let two sessions change the same shared contract independently. Define
the contract first, then assign repo-specific implementation scopes.

## Lead-Agent Split Decision

Before spawning subagents or assigning parallel implementation work, the lead
agent must name:

- the stable contract that all workers can rely on
- each worker's owned files, packages, or modules
- each worker's forbidden files, packages, or modules
- the integration point and who owns it
- the focused verification for each slice and the final merged check

If any of those cannot be named, keep the work serial until the boundary is
clear. The lead agent remains responsible for integrating the result, resolving
conflicts, and ensuring the final diff still satisfies the original request.

## Delegation Decision Record

Record the delegation decision before code work:

- `serial`: state why the task is too small, same-file, contract-bound,
  migration/dependency-sensitive, release-sensitive, or otherwise unsafe to
  split.
- `parallel`: list each worker, run state, owned files/modules, forbidden
  files/modules, input contract, expected output, acceptance checks,
  integration owner, and verification command or manual scenario.
- `sequential`: several workers dispatched one at a time, each starting only
  after the previous one returned, so no two writers are ever active together.
  Record the same per-worker detail as `parallel`. Do not record this as
  `serial`: real workers ran, and `serial` states that a single agent did the
  work.

Delegation is not a handoff of responsibility. The lead agent owns the shared
contract, integration point, review of worker changes, side-effect audit, and
final verification. If a worker changes the contract, route, schema, state
model, or config outside its brief, stop integration and restart from the split
decision.

The two-slice eligibility threshold counts a meaningful slice retained by the
lead as well as worker slices. Therefore one worker plus a distinct lead-owned
integration or implementation slice can be a valid parallel plan. Multiple
workers must use unique ids. Disjoint `owned_scope` entries are the default and
keep the shared checkout.

Every `owned_scope` entry must be a normalized repo-relative POSIX path or glob:
no leading slash, backslash separator, duplicate `/`, or `.` / `..` path
segment. Validation rejects non-canonical aliases before comparing overlap so
two spellings of the same path cannot bypass worktree isolation.

Overlapping `owned_scope` is allowed only when both overlapping workers declare
`isolation: "worktree"`. Each such worker then runs inside its own real
`git worktree` created from the base ref, the lead reviews the worker results
and integrates them sequentially. The lead then invokes the verified
`workflow.py dispatch-finalize` path for each worker; cleanup proceeds only
when every tracked and untracked worker change matches the lead checkout.
Unintegrated or mismatched results remain in their worker worktrees, and ignored
files require the lead's explicit discard policy.
If one overlapping worker omits the isolation declaration, the exact or
unambiguous parent/child path overlap is still rejected before work starts.

Base-ref constraint: worktrees branch from `HEAD`, so uncommitted parent changes
are not visible inside a worker worktree. When an overlapping scope has
uncommitted parent changes the lead must make a checkpoint commit first, or
serialize that slice instead of isolating it.

Choose the `multi-agent` route only when the parallel decision is already
positive. When automatic eligibility fails, stay on the original work route,
record its structured serial split decision with the concrete policy reason,
and do not create a parallel delegation plan.

When two or more writers are active at the same time, write a structured local
plan before workers start. The plan coordinates concurrent writers, so a
`sequential` run does not need one; every other delegated or parallel run does:

```text
<TARGET_REPO>/.tao/agent-delegation-plan.json
```

Use this schema:

```json
{
  "schema_version": 1,
  "mode": "parallel",
  "workers": [
    {
      "id": "docs-a",
      "role": "docs reviewer",
      "owned_scope": ["workflows/*.md"],
      "forbidden_scope": ["scripts/*.py"],
      "isolation": "worktree",
      "contract": "report documentation gaps only",
      "acceptance": ["findings include file and rule"],
      "verification": ["python3 scripts/workflow.py validate"]
    }
  ],
  "integration_review": {
    "owner": "lead agent",
    "contract_drift_check": "compare worker findings with route gate policy",
    "final_verification": ["python3 -m unittest discover tests"]
  }
}
```

Copy the schema keys exactly when creating the plan manually. In particular,
`mode` must be the literal `"parallel"`; `workers` must use `id`, `role`,
`owned_scope`, `forbidden_scope`, `contract`, `acceptance`, and `verification`;
`isolation` is optional and, when present, must be the literal `"worktree"` (set
it only on workers that run in their own real `git worktree` to share an
overlapping `owned_scope`);
and the lead record must be named `integration_review`. Alternate descriptive
keys such as `current_state`, `scope`, or `serial_integration` do not satisfy
the executable finish contract even when their prose sounds equivalent.

Finish-check treats parallel/subagent evidence or the `multi-agent` route's
role/write-scope/brief/integration gates as incomplete without this plan. A
`sequential` split decision is the one exception, and only for the plan itself;
the route's role/write-scope/brief/integration gates still require it. The
plan is local runtime evidence; do not commit it unless the repo explicitly
tracks agent execution artifacts.

Record the structured multi-agent gate fields before workers start. Gate and
gate-batch hooks reject incomplete `SUCCESS` records before writing them and
report the complete missing-field set in one pass. For a parallel or sequential
split, the required field names are `mode`, `reason`, `owned_scope`,
`forbidden_scope`, `contract`, `acceptance`, `integration_owner`, and
`verification`. Alias keys such as `contract_brief` or `acceptance_checks` do
not satisfy the executable contract. The same pre-worker record validates the
delegation-plan structure so schema mistakes are corrected before finish and do
not consume the bounded repair cycle.

## Agent Briefs

Each brief should include:

- task id
- role
- goal
- owned files or modules
- forbidden files or modules
- acceptance checks
- verification commands or manual scenarios
- expected final report shape

For code-edit workers, include:

- the checkout may contain user-owned changes
- do not revert changes outside assigned scope
- list changed files and verification in the final report

## Worker Escalation Lifecycle

Workers that may need a mid-task decision must be spawned resumable and
addressable: long-lived and messageable, so the lead can deliver a decision
and the worker resumes. A one-shot worker that emits an escalation and exits
leaves no target for the answer.

On an escalation:

1. Review the options the worker presented and decide. Re-ask the user only
   when the choice is genuinely unclear.
2. Send the decision to the worker.
3. Wait for the worker to resume before integrating anything from it.

If the worker already exited (one-shot call), re-spawn it with the prior
context plus the decision embedded in the new brief.

After a worker returns, compare its result against the agreed plan. If it
diverged unilaterally, instruct rollback of the divergent changes and re-spawn
with a strengthened mandatory-escalation clause in the brief.

Stop a worker after prolonged silence and re-plan. Terminate finished workers
or let them exit naturally; do not accumulate idle worker sessions.

## Closeout

Before the review hook, count the complete code-only changed-path union from
the delegation plan, including untracked files. Do not narrow the review paths
and claim that the exact integrated diff was reviewed merely to fit the default
changed-path budget.

If a valid multi-agent integration exceeds that budget, either split the
delivery or pass a bounded `--max-changed-paths` value that covers the exact
planned union. Record why the override is safe in the integration-review
evidence. This budget override does not waive one-public-owner, file-size,
oversized-block, side-effect, or verification gates; fix those structural
findings before resuming review.

Closeout should state:

- what changed
- what was verified
- what remains risky
- which follow-up tasks exist
- whether docs, tests, or run artifacts were updated

## Stop If

- Two agents would edit the same file, schema, migration, generated artifact, or
  release config at the same time, unless both writers declare `isolation:
  "worktree"` and each runs in its own real git worktree per the Delegation
  Decision Record carve-out.
- The shared contract between parallel tasks is not defined.
- A worker brief lacks owned files, forbidden files, acceptance checks, or
  verification expectations.
- Integration review cannot be performed before broad verification or handoff.
