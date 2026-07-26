---
keyflow_id: sys_development_cycle_workflow
status: stable
type: human-reviewed-needed
---

# Development Cycle Workflow

Use for multi-step implementation work from request intake through handoff. This
is the default workflow when the task is larger than a one-line edit.

The goal is one complete cycle: understand the request, make the smallest useful
change, verify the changed surface, audit side effects, and report evidence.

When this cycle is reached from `scripts/workflow.py`, treat the script output as
the command manifest and keep the implementation inside its listed gates.

## Read

- `common/skills/agent-operating-skill/SKILL.md`
- `common/skills/llm-coding-discipline/SKILL.md`
- `common/skills/code-conventions/SKILL.md`
- `common/skills/stack-discovery/SKILL.md`
- `common/skills/incremental-implementation/SKILL.md` when the change can be split into
  verified slices
- `common/skills/source-driven-development/SKILL.md` when framework, SDK, platform, API, or
  external documentation behavior can change over time
- `common/skills/doubt-driven-development/SKILL.md` when the plan depends on high-risk or
  non-obvious assumptions
- `common/skills/change-size-policy/SKILL.md`
- `common/skills/worktree-hygiene/SKILL.md` when the checkout already contains changes
- `common/skills/tool-failure-recovery/SKILL.md` when verification or build commands fail
- one matching platform architecture card from `index.md`
- task-specific concern cards from `index.md`

## Phases

1. Orient: identify target repo, repo-local rules, current user changes,
   discovered stack, affected surface, and existing verification commands.
2. Alignment brief: before changing files, tell the user the understood change,
   what should remain unchanged, where user/agent understanding may differ, and
   the default assumption or blocker questions. If this route does not create a
   PRD, treat this as the PRD-skip checkpoint; it must be user-visible before
   edits, not only recorded in finish evidence.
3. Source docs: before implementation, search for and open relevant PRD, spec,
   ARD, issue, design note, task doc, or source-of-truth docs. If the change is
   feature-sized and no source exists, stop to create or update a PRD/spec
   unless the user request already contains enough acceptance criteria for the
   slice and the PRD-skip decision is recorded.
4. Agentic run state: record the current state, next transition or resume
   point, and gate/command/check evidence before implementation. Use this
   state as the recovery anchor after interruption, delegation, failed
   verification, or retrospective restart.
5. Scope: name the requested behavior, acceptance criteria, non-goals, and the
   smallest safe slice.
6. Boundary plan: choose state, domain, data, platform, contract, security, and
   ownership boundaries. Name the owned files/modules, caller-facing contracts,
   allowed or forbidden dependency direction when relevant, and the nearest
   verification path before editing.
7. Workspace scope checkpoint: when a product spans multiple repos and
   orientation shows that another repo is the source of truth or must be
   written, stop before that write. State the starting primary repo,
   secondary/source-of-truth repo, selected mode, write scope, session model,
   and cross-repo verification.
8. Slice plan: choose vertical, contract-first, risk-first, test-first, or
   UI-state slicing when the work is non-trivial. Do not broaden beyond the
   first useful slice until it has evidence or an explicit residual-risk note.
9. Implement: change only the scoped files and keep generated, dependency,
   formatting, and release churn separate when possible.
10. Documentation: update the source-of-truth docs affected by the change, or
    record the exact doc path/class checked and why it is intentionally
    unchanged. Documentation evidence must explain the reason, not only say
    "docs checked."
11. Verify: run the narrowest reliable check that proves the changed surface.
12. Side-effect audit: inspect the final diff and affected call paths for behavior
   outside the requested slice.
13. Doubt pass when needed: challenge the weakest assumption before handoff when
   the work touches data, auth, billing, release, migration, external state,
   security, privacy, observability, or architecture.
14. Broaden only if needed: run wider checks when the narrow check cannot cover
   shared contracts, auth, persistence, platform integration, release, or user
   flow risk.
15. Handoff: report changed files, verification evidence, skipped checks, side
   effects considered, and residual risk.

## Parallel Implementation

Use parallelism to reduce waiting, not to blur ownership.

- Parallelize read-only orientation after route selection: selected document
  reads, file searches, stack discovery, git status, and preflight evidence may
  run together when the runtime supports it.
- For code work, record a multi-agent split decision before editing. Use
  subagents or parallel/multi-agent implementation when owned files or modules
  are disjoint and the contract is stable. If the work stays serial, record the
  reason: small scope, same-file edits, unstable shared contract,
  migration/dependency surface, or another concrete overlap risk.
- Split implementation across parallel agents only when each slice has explicit
  owned files or modules, forbidden files or modules, acceptance checks, and
  verification commands.
- Prefer parallel writers for disjoint surfaces such as isolated adapter code
  and separate docs, or independent UI and domain slices after the contract is
  stable.
- For cross-repo product work, keep one primary repo session when the secondary
  repo is read-only or the write is small and bounded. Use separate sessions
  when both repos need meaningful implementation, verification, or commits.
- Serialize edits to shared contracts, route schemas, migrations, generated
  files, dependency config, package manifests, release config, architecture
  boundaries, and any file that two agents would both touch.
- Run integration review or the Review Hook after parallel changes are merged
  before broad verification or handoff.
- When reviewing an implementation in a dirty worktree, make the review scope
  explicit. Use the whole working tree only when all current changes belong to
  the task; otherwise pass task-owned paths to the Review Hook so structure,
  changed-path, and whitespace checks cover the intended slice.
- Before the first Review Hook call, count the task-owned changed paths. When a
  cohesive cross-surface task legitimately exceeds the default changed-path
  budget, pass a bounded `--max-changed-paths` value derived from that observed
  scope instead of discovering the limit through a failed review. Do not use an
  arbitrary large override to combine unrelated changes.
- When the changed scope contains a package with multiple established roles,
  make the structure evidence explicit before review: name the package owner,
  allowed imports, forbidden imports, callers/tests, and verification. A generic
  "no new boundary" statement does not replace those ownership fields.

## Minimum Verification

Pick the closest check to the changed boundary first:

- Docs/config only: formatting, link/path sanity, `git diff --check`, or repo
  docs build when available.
- Pure logic: focused unit test for the changed function, mapper, policy, parser,
  validator, or reducer.
- Boundary mapping: normal, invalid, missing, stale, duplicated, lower bound,
  and upper bound cases for the changed parser, mapper, adapter, or reducer.
- Type/interface changes: compile, typecheck, generated client check, or contract
  test for the changed module.
- UI/state change: focused state test, component/screen test, screenshot/layout
  check, or manual smoke path for the changed state.
- API/route/event change: request/response contract test, route/deep-link test,
  fixture parity check, or affected client compile/typecheck.
- Persistence/migration/sync change: migration, load/save, corrupted data,
  stale-write, retry, and cleanup check closest to the storage boundary.
- Security/auth/permission change: denied access, stale session, revoked
  permission, cross-tenant, and secret/log leak check where applicable.
- Release/deployment change: package, dry run, staging smoke, signing/config
  check, or rollback/forward-fix note.

Minimum verification is acceptable only when it proves the changed boundary. If
it does not, name the gap and either run the next wider check or report the
residual risk explicitly.

## Side-Effect Audit

After verification, inspect the final diff and ask:

- Did any file change outside the scoped owner boundary?
- Did formatting, generated files, lockfiles, dependency updates, or release files
  change unexpectedly?
- Did any public API, DTO, route, event, schema, storage format, or fixture change?
- Did any external, persisted, generated, cached, or user-provided value cross a
  boundary without validation?
- Did auth, permission, tenant, billing, privacy, logging, analytics, or secret
  handling change?
- Did state ownership, cache invalidation, lifecycle, background work, or cleanup
  behavior change?
- Did UI text, accessibility, localization, focus order, empty/error states, or
  responsive layout change?
- Did repo-local commands, build config, environment config, package identity,
  signing, or deployment behavior change?
- Can the change be reverted without removing unrelated behavior?

If the answer is yes, either verify that surface, split the change, or report the
remaining risk.

When side-effect investigation reveals a possible meaning, policy, route, gate,
or pass/fail interpretation change, stop at a meaning checkpoint before editing
unless the fix is mechanical and already covered by explicit tests. The
checkpoint should state:

- the understood intent
- the side-effect candidate
- the proposed direction
- what can be safely auto-fixed
- the specific interpretation that needs confirmation

Record side-effect audit evidence before handoff. Acceptable evidence names the
final diff or checked surfaces and states whether unexpected generated files,
lockfiles, public contracts, external state, formatting churn, or unrelated
behavior were found.

## Route To

- New feature or behavior: `workflows/skills/feature-implementation/SKILL.md`
- Bug, regression, or flaky behavior: `workflows/skills/bugfix-debugging/SKILL.md`
- Behavior-preserving cleanup: `workflows/skills/refactor-cleanup/SKILL.md`
- Release, package, deployment, or migration handoff: `workflows/skills/release-readiness/SKILL.md`
- Final review or commit: `workflows/skills/review-and-commit/SKILL.md`

## Stop If

- The target repo or product contract is ambiguous enough to change the result.
- The requested slice mixes unrelated behavior, refactor, dependency, generated,
  and release work.
- Verification cannot cover a risky change and the residual risk is not
  acceptable to state.
- The side-effect audit finds unrelated changes that should be split before
  handoff or commit.
