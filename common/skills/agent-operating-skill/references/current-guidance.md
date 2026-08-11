---
keyflow_id: sys_agent_operating_skill
status: stable
type: human-reviewed-needed
---

# Agent Operating Skill

Use this before implementation, review, refactoring, debugging, documentation, or verification work. This is the baseline skill for reducing repeated agent mistakes.

## Core Loop

1. Identify the target project and task type.
2. Classify request clarity and effort before loading broad context. If the user asks a direct question, answer it before starting workflow routing, editing, or project-specific commands.
3. Read repo-local instructions before changing files.
4. Discover the project stack before choosing commands or libraries.
5. For multi-step tasks, run `<TAO_LAUNCHER> start ... --request
   "<USER_REQUEST>"` once before selecting task documents, editing, reviewing,
   committing, or reporting completion. It performs routing and preflight; do
   not separately repeat workflow list, classify, route, or preflight after it
   succeeds. Direct `workflow.py route` and `agent-preflight.py` calls are
   lower-level diagnostic or compatibility fallbacks only.
6. After start, read the route's `required_docs` / `Read First` docs before editing,
   reviewing, coding, or running project-specific work. Treat `reference_docs`
   as lazy context and open one only when the current task touches that concern,
   platform, gate, or verification path. The router owns required-document
   selection; agents consume that manifest directly without a second
   confirmation hook, receipt, or finish gate.
   A required gate cannot pass by recording a skip, not-applicable,
   unable-to-run, deferred, or follow-up reason unless that gate explicitly
   allows that outcome. If the evidence names an unresolved, must-fix,
   should-fix, blocking, or deferred issue, report `FAIL`, run missed-gate
   recovery, and use retrospective learning to change the next action path.
   For local commit creation or commit preparation, route to `commit` or
   `git_commit` instead of the general `task`, `review`, or `triage` routes
   when the request is clear. Commit routes are intentionally lightweight:
   read the commit workflow entrypoints, run the review hook first, stop before
   committing when review finds issues, and record commit readiness only after
   the staged diff and verification evidence match the intended commit unit.
7. For feature, product, build, release, or other behavior-changing work, search
   for repo-local PRD, spec, ARD, issue, design note, task doc, or documented
   source of truth before implementation or edits. If one exists, open it and
   use it as the acceptance source. If none exists, record the search evidence
   and decide whether a PRD/spec must be created before code or whether the
   current user request is sufficient for the slice.
8. For requirements analysis or modification work, give the user a compact
   alignment brief before drafting requirements or changing files. State shared
   understanding, possible mismatch, and unsupported assumptions or minimal
   blocker questions. Do this even when the work is not PRD-sized. If no PRD is
   created, this PRD-skip checkpoint is still required and must be visible to
   the user, not only recorded internally.
9. Check preflight's global lesson summary when available. Accepted or promoted
   lessons from `~/.tao/` apply across repos unless repo-local
   instructions conflict.
10. Keep a gate execution ledger for the route and mark each gate with
    evidence when it is executed. Prefer structured
    `.tao/gate-evidence.json` entries for the default
    `preflight.json`, or `<preflight-stem>-gate-evidence.json` entries for a
    custom preflight evidence file, written by executable hooks or one
    `agent-hook.py gate-batch` call over repeated single-gate shell calls or
    reconstructing validator-ready prose at finish. Show a short gate signal
    after each completed gate or task step.
    For a lightweight `analysis` route, do not jump directly from investigation
    to `finish`: compare the active route's exact gate list with the ledger,
    then record `investigate`, the structured `retrospective check`, and
    `report` before calling `finish`. Treat preflight-provided `request intake`
    as complete only when it is already present in that same ledger. `finish`
    never infers gate completion from commands, tests, commentary, or the final
    response draft.
11. For work-producing or delegated tasks, record the agentic run state:
    current state, next transition or resume point, gate/command/check
    evidence, checkpoint or stop condition, and blocker status. Use it as the
    continuation and recovery anchor after interruption, subagent delegation,
    failed verification, or missed-gate recovery.
12. For work-producing routes, record a cycle contract before editing: cycle
    type, input/source scope, allowed and forbidden changes, acceptance or
    verification method, stop condition, and checkpoint or next cycle.
13. Use `index.md` to load only relevant Tao Agent OS cards.
14. Use the route manifest's `parallel_execution.phases` before treating gates
    as a serial checklist. Parallelize independent read-only orientation when
    the runtime supports it: selected document reads, file searches, stack
    inspection, git status, and preflight evidence may run together after
    request intake is settled.
15. Inspect existing code, docs, tests, and local conventions.
16. For code or architecture work that crosses files, packages, folders, or
    modules, record a compact structure packet before editing: chosen boundary,
    package/folder map, file split, allowed imports, forbidden imports,
    callers/tests, and nearest verification.
17. When a product alias or investigation crosses repositories, choose the
    primary repo from the acceptance path and stop for a workspace scope
    checkpoint before writing to any secondary repo.
18. Make the smallest change that genuinely addresses the request.
19. For code work, record the multi-agent split decision before editing and use
    parallel agents when scopes are disjoint and stable.
20. Update or create affected docs whenever behavior, workflow policy, public
    contract, durable acceptance criteria, operator action, or source-of-truth
    meaning changes. If no doc file changes, record the exact source-of-truth
    checked and why docs are intentionally unchanged or not applicable.
21. Add/update/run the nearest useful test when code behavior or workflow policy changes.
22. Verify with the narrowest reliable command first.
23. Confirm the route gate ledger before reporting completion.
24. Report what changed, what was verified, and what risk remains.

## Mistake Prevention Checklist

Before editing:

- Confirm target path and project.
- Classify the request as clear-exact, clear-scoped, vague-action, broad-product, risky-unclear, or direct-question before choosing effort.
- If classified as direct-question, answer first and do not start work unless a separate actionable request remains.
- If the direct question asks how to start app, product, or feature work, answer with the PRD -&gt; ARD -&gt; implementation sequence first. Do not give an implementation-only workflow for product delivery.
- If a blocker unknown can change behavior, scope, risk, acceptance criteria, or
  verification and repo context cannot answer it, ask before editing. Do not
  invent product intent or acceptance criteria silently.
- For requirements analysis, feature, bugfix, refactor, docs, workflow setup, or
  other modification routes, give the user an alignment brief before drafting
  or editing. It must be a concise same/different/assumption check, not a full
  Grill-Me `/grilling` session unless blockers require one. Do not treat "no
  PRD" as "no question or checkpoint"; when a PRD is skipped, state the skip
  reason, shared understanding, possible differences, unsupported assumptions,
  and the minimal blocker question or safe default before work starts.
- For writing or documentation changes, do not infer genre, point of view, or
  structure from a style cue such as plain endings, "not honorific", or "my
  style". If multiple writing modes fit, ask a concrete choice question before
  editing the draft.
- Check repo-local `AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, `CONTRIBUTING.md`, or equivalent docs.
- Check stack manifests, lockfiles, and config before running commands, adding dependencies, or using framework-specific APIs.
- Read the route's `Read First` / `required_docs` docs before code,
  implementation, review, or edit work. Do not load `Reference On Demand` docs
  unless the current task touches that concern, platform, gate, or verification
  path. Do not add a duplicate document-confirmation command after routing.
- For feature, product, build, release, or other behavior-changing work, search
  and open repo-local PRD/spec/ARD/source-of-truth docs before implementation.
  Finish evidence must say whether those docs were found and read, or whether
  none were found, and how that source affected the work or documentation
  decision.
- For work-producing and multi-agent routes, record `agentic run state`
  evidence before implementation: current state, next transition or resume
  point, gate/command/check evidence, checkpoint or stop condition, and blocker
  status.
- For work-producing routes, record `cycle contract` evidence before editing:
  cycle type, input/source scope, allowed and forbidden changes, acceptance or
  verification method, stop condition, and checkpoint or next cycle. Keep code
  review as a separate review cycle unless the user explicitly asks for
  review-response implementation.
- When implementation can add or move more than one file, package, folder, or
  module, write the structure packet first. Do not start by dumping all code
  into one feature, `common`, `shared`, `utils`, `helpers`, `services`, or
  `manager` folder.
- Check whether the task touches data, auth, permissions, billing, persistence, filesystem, network, release, or external state.
- Check whether the task touches secrets, client keys, local config, logs, analytics, crash reporting, or open-source-safe setup.
- If a product/workspace alias may map to multiple repos, use local workspace
  group discovery or ask for the primary repo. Do not guess a single repo from
  the alias alone.
- Before writing to a secondary repo, record a workspace scope checkpoint:
  starting primary, secondary/source of truth, selected mode, write scope,
  session model, and cross-repo verification.
- Check for existing user changes in files you may touch.
- After route selection, read `parallel_execution.phases`, then run independent
  route documents and read-only orientation commands in parallel when possible.
  Do not serialize document reads unless one document determines whether
  another is needed.
- The single `agent-hook.py start` call may run alongside independent read-only
  orientation after the request is answered or classified, but no edit, setup,
  update, fix, commit, push, release, migration, or external-state change may
  start until it succeeds. Use `agent-preflight.py` directly only as the
  lower-level fallback when start is unavailable; never run both startup paths.

While editing:

- Follow existing architecture and naming before inventing a new pattern.
- Keep unrelated refactors out of feature or bug-fix work.
- Preserve user-owned changes.
- Do not expose secrets, tokens, private prompts, or credential contents.
- Do not claim mocked, placeholder, or TODO behavior is complete.
- For larger implementation work, split work across parallel agents only when
  the owned files, packages, contracts, and forbidden files are explicit and do
  not overlap, and when acceptance checks plus an integration owner can be
  named before workers start. Serialize shared contracts, generated files,
  migrations, dependency changes, release config, and architecture boundaries.
  When work is actually delegated or parallelized, write
  `.tao/agent-delegation-plan.json` before workers start and keep the
  lead agent responsible for integration review and final verification.

Before finishing:

- Run the route's review hook after meaningful edits, then run
  `<TAO_LAUNCHER> finish` before final report, handoff, commit, or
  release. Use `agent-finish-check.py` directly only as a lower-level diagnostic
  or compatibility fallback when the finish hook is unavailable.
- Confirm every required workflow route gate has structured ledger evidence
  when a scripted route was used. Treat missing fields as missing work or
  missing evidence to complete, not as a prompt to write vague pass-through
  wording at finish. For gates with structured field requirements, ledger
  evidence must provide those fields. Record one-off manual evidence through
  `gate` or `gate-batch` before finish; finish is a read-only validator and
  accepts no inline gate state.
- Prefer one `gate-batch` submission for the route's remaining gates. If any
  gate record is rejected, stop before `finish`, correct every reported field
  or semantic contract, and confirm the complete required-gate set is present
  in the ledger. A rejected `gate`/`gate-batch` call records no checkpoint and
  must never be followed by `finish` as though the rejected evidence existed.
  Exclude hook-owned gates such as `review hook` from every manual `gate` or
  `gate-batch` payload: run the owning hook once, then batch only the still
  missing manual gates (for example, record `handoff` by itself after review).
  Run `gate-batch` and `finish` as separate, observed invocations; never place
  them in one shell command where `finish` can run after a rejected batch.
- Confirm alignment evidence names the user-visible checkpoint, not only an
  internal note reconstructed after the work.
- Confirm documentation evidence names the decision, affected source-of-truth
  doc path or doc class, and the reason for update/create/unchanged/not
  applicable. "Docs checked" or "updated docs" is not enough.
- Run the most relevant test, build, typecheck, lint, or smoke check.
- For code work, include evidence for ambiguity handling, docs freshness,
  tests, and multi-agent split decision when the route requires them.
- If verification cannot run, state why and what risk remains.
- Include file references when explaining non-trivial changes.
- If any required gate is missed or fails, run the retrospective workflow before
  retrying the same scope or reporting completion. The retrospective must record
  an immediate correction plan, apply safe scoped fixes, and the retry must cite
  or apply that plan. Treat the generated global lesson candidate as a prompt to
  promote a recurring lesson into shared docs, tests, validation, or hooks.

## Task Routing

- Request clarity, Grill-Me, model/effort routing, or token reduction: `common/skills/task-intake-effort-routing/SKILL.md` and `workflows/skills/request-triage/SKILL.md`.
- Scripted workflow route: `workflows/skills/scripted-agent-workflow/SKILL.md` and `scripts/workflow.py` are mandatory for multi-step tasks when the script is available. Pass `--request "<USER_REQUEST>"` so the script can block direct questions and unclear work before implementation. If the script cannot run, report the blocker before using `index.md` as a fallback.
- Stack, package manager, framework, runtime, or command discovery: `common/skills/stack-discovery/SKILL.md`.
- Failed commands, compiler errors, lint errors, or broken verification: `common/skills/tool-failure-recovery/SKILL.md`.
- User questions, approval requests, and ambiguity communication: `common/skills/agent-interaction/SKILL.md`.
- Any multi-step agent task: `workflows/skills/agent-task-lifecycle/SKILL.md`.
- Interrupted or transferred work: `workflows/skills/agent-handoff-continuation/SKILL.md`.
- Work-producing cycle contract and stop conditions: `workflows/skills/cycle-contract/SKILL.md`.
- Ambiguous requests or blocker unknowns before PRD, ARD, task breakdown, or implementation: `workflows/skills/ambiguity-gate/SKILL.md`.
- PRD or product requirements note: `workflows/skills/prd-creation/SKILL.md`.
- App, product, or feature delivery that may continue into code: `workflows/skills/product-architecture-delivery/SKILL.md`. Use this before the lower-level feature workflow unless the request is already a trivial, scoped change.
- Multi-step development: `workflows/skills/development-cycle/SKILL.md`.
- Delegated or parallel agent work: `workflows/skills/multi-agent-collaboration/SKILL.md`.
- Non-trivial review or release candidate review: `workflows/skills/multi-perspective-review/SKILL.md`.
- Planning or research: `workflows/skills/planning-research/SKILL.md`.
- Documentation update: `workflows/skills/documentation-update/SKILL.md`.
- Feature work: `workflows/skills/feature-implementation/SKILL.md`.
- Bug or regression: `workflows/skills/bugfix-debugging/SKILL.md`.
- Refactor or cleanup: `workflows/skills/refactor-cleanup/SKILL.md`.
- Release-sensitive work: `workflows/skills/release-readiness/SKILL.md`.
- Final review or commit: `workflows/skills/review-and-commit/SKILL.md`.
- Architecture: `common/skills/architecture-selection/SKILL.md`, `common/skills/architecture-design/SKILL.md`, or `common/skills/app-architecture/SKILL.md`.
- LLM-readable wiki, knowledge-base, runbook, or durable documentation: `common/skills/llm-wiki-documentation/SKILL.md`.
- Code conventions: `common/skills/code-conventions/SKILL.md`.
- File/module layout, ownership, public contracts, `api`/`impl` splits, or
  `assertions`/test-support modules: `common/skills/code-structure-ownership/SKILL.md`,
  `common/skills/solid-design-principles/SKILL.md`, and
  `common/skills/reusable-code-design/SKILL.md`. These cards are a bundle for boundary
  work; do not load only one when the task changes dependency direction,
  caller-facing contracts, reusable fakes, fixtures, recorders, or assertion
  DSLs.
- Reusable code extraction or shared module/package contracts:
  `common/skills/reusable-code-design/SKILL.md`, plus `common/skills/solid-design-principles/SKILL.md`
  when the shared API exposes callbacks, interfaces, adapters, fakes, or
  replaceable implementations. When the task creates packages, folders,
  source sets, modules, or shared/core/common boundaries, include a package
  boundary note that names owner, allowed imports, forbidden imports, callers,
  and focused verification before editing. If the task adds several roles, also
  include the file split and package/folder map before writing code.
- Reusable component, hook, widget, control, or caller-facing API design: `common/skills/component-api-design/SKILL.md`.
- UI, async, reducer, store, ViewModel, hook, cache, or state-machine state design: `common/skills/state-modeling/SKILL.md`.
- Error handling, typed failures, retry classification, or failure UX: `common/skills/error-modeling/SKILL.md`.
- Project, app, repo, package, module, CLI, or service naming: `common/skills/project-naming/SKILL.md`.
- Change size or broad diffs: `common/skills/change-size-policy/SKILL.md`.
- Existing checkout, user-owned changes, or commit preparation: `common/skills/worktree-hygiene/SKILL.md`.
- Dependencies, SDKs, or build plugins: `common/skills/dependency-policy/SKILL.md`.
- Generated files, lockfiles, or snapshots: `common/skills/generated-files-policy/SKILL.md`.
- API, DTO, route, event, webhook, or shared fixture contracts: `common/skills/api-contract-compatibility/SKILL.md`.
- Upload, download, media, attachment, signed URL, public/private asset movement, cleanup, or embedded asset references: `common/skills/asset-lifecycle/SKILL.md`.
- External, persisted, generated, cached, platform, or user-provided values: `common/skills/defensive-boundaries/SKILL.md`.
- Environment-specific runtime URLs, API origins, callback URLs, redirect URIs,
  webhook endpoints, CORS origins, or asset hosts:
  `common/skills/runtime-url-configuration/SKILL.md`.
- Release, deployment, packaging, signing, rollout, rollback, versioning, or tags: `common/skills/release-deployment/SKILL.md` and `common/skills/release-versioning/SKILL.md`.
- User-facing text, forms, controls, dates, numbers, units, measurements,
  display values, or localization: `common/skills/accessibility-i18n/SKILL.md`.
- User-facing prose, documentation tone, release notes, marketing copy, emails, voice fidelity, or AI-writing signal cleanup: `common/skills/human-authored-writing/SKILL.md`.
- Blog posts, articles, essays, publishable long-form prose, or user-author
  writing consistency across agents: `common/skills/writing-workspace/SKILL.md` plus
  `common/skills/human-authored-writing/SKILL.md`.
- SEO, AI search visibility, AEO/GEO claims, sitemap, robots, metadata, Open Graph, short links, canonical URLs, or public discovery feeds: `common/skills/public-discovery/SKILL.md`.
- UI layout, interaction, text overflow, responsive behavior, or accessibility-visible state: `common/skills/ui-visual-verification/SKILL.md`.
- Refactoring: `common/skills/refactoring/SKILL.md`.
- Tests and evidence: `common/skills/testing/SKILL.md` and `common/skills/verification-policy/SKILL.md`.
- Code review: `common/skills/code-review/SKILL.md`.
- Local programs, agent CLIs, or usage telemetry: `common/skills/local-tools/SKILL.md`.
- Secrets, external state, or user-owned changes: `common/skills/agent-editing-safety/SKILL.md`, `common/skills/secure-development-baseline/SKILL.md`, and `common/skills/security-privacy-review/SKILL.md`.
- React, iOS, Android, server, desktop, or application work: load the matching platform card from `index.md`.
- Android Navigation 3, deep links, typed route/back-stack contracts,
  mixed Compose/Activity routing, or route callbacks/events:
  `platforms/android/skills/android-architecture/SKILL.md` and
  `platforms/android/skills/android-module-structure/SKILL.md`, plus the structure/SOLID
  bundle above when route contracts, `api`/`impl`, `assertions`, fixtures,
  recording fakes, or assertion DSLs are added or moved. Add
  `platforms/android/skills/android-security/SKILL.md` when exported components, app links,
  WebView, permissions, or credentials are touched.
- Android Compose performance, stability, lazy lists, side effects, custom
  modifiers, baseline profiles, or measurement claims:
  `platforms/android/skills/android-compose-ui/SKILL.md`,
  `platforms/android/skills/android-review/SKILL.md`,
  `platforms/android/skills/android-external-skill-source-coverage/SKILL.md`, and the
  testing/verification cards. Do not claim a performance fix without the
  repo's relevant measurement evidence or a clear statement that only a
  structural risk was reduced.
- Android platform-surface or SDK work such as AGP upgrades, Android CLI/device
  inspection, R8/keep rules, Perfetto traces, XML-to-Compose migration,
  adaptive layouts, edge-to-edge, Compose Styles, CameraX, Credential Manager,
  Play Billing, Play Engage, Wear Compose, XR/Glimmer, or AppFunctions:
  load the Android architecture/module/Compose/security card that matches the
  surface, then apply the no-omission source manifest in
  `platforms/android/skills/android-external-skill-source-coverage/SKILL.md` before editing.

## Output Contract

Use short evidence-based reporting:

```text
Changed:
- ...

Verified:
- ...

Remaining risk:
- ...
```

For small tasks, a concise paragraph is enough, but verification status still matters.
