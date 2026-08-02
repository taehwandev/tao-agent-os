---
keyflow_id: sys_scripted_agent_workflow
status: stable
type: human-reviewed-needed
---

# Scripted Agent Workflow

Use when an agent task should be resolved by an executable workflow route instead
of only by reading prose. For multi-step tasks, this route generation is
mandatory when the script is available. The script is the command manifest
generator. The documents remain the source of truth for judgment, constraints,
and verification detail.

## Purpose

Simple or repeated workflows should be represented as a small Python script when
manual routing would create inconsistent behavior across agents. The script
selects the workflow, platform cards, concern cards, and gates for a command.
The agent then reads the generated route and performs the work in the target
repo.

## Agentic Control Plane

The workflow script is the agentic coding control plane for Tao Agent OS. It
gives the active agent a route manifest, required documents, required gates,
run-state expectations, delegation policy, and evidence policy so Codex, Claude
Code, Gemini CLI, GitHub Copilot coding agent, Cursor, Aider, Devin, Replit
Agent, or another coding agent can work with the same operating discipline.

Agentic behavior comes from connecting that manifest to execution: selecting
the right route, recording run state, deciding whether to work serially or
delegate to subagents, collecting evidence, repairing missed gates before
resuming, and turning repeated lesson candidates into verified durable
improvements. When the runtime
supports subagents or launchers, use the split decision and run-state evidence
as the delegation contract.

## Default Script

Run the shared start hook once for every multi-step task when it exists. It
performs request intake, routing, and preflight as one lifecycle entry:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command <command> --request "<USER_REQUEST>" [--platform <platform>] [--concern <concern>]
```

`--rules` must point to the Tao Agent OS root directory, not to an
individual instruction file such as `AGENTS.md`.
The start hook requires the current request with `--request`.
`--request-classified` is a proof-carrying delegation exemption, not a
same-session root override: add it with `--classification-evidence` only when a
ready and valid parent capsule binds the worker to the same exact request and
workflow command from the prior intake. A capsule for another request or route
grants no exemption. Without that matching capsule, the classifier
intentionally evaluates `--request` and free-text evidence cannot wave a vague
request through. For a terse root-session
follow-up, pass a context-complete request that preserves the verbatim follow-up
and names the already-established scope, for example `검증해줘 — continuation
scope: verify the required-document receipt change completed in the immediately
preceding task`. If the scope cannot be carried forward safely, use `triage` or
`ambiguity` instead. Direct `agent-hook.py start --request-classified` without
the current request, evidence, and valid parent capsule is a workflow failure,
and the form with neither a request nor a capsule is rejected outright. A caller
that only needs the document listing and label context and asserts no intake
uses `--advisory`; it satisfies no downstream gate, so work must be re-routed
with a real `--request` before editing, reviewing, or reporting completion.
If the request is a direct question, the script blocks routing so the agent
answers before editing or running project commands. Work routes with a valid
delegation exemption still require evidence that proves the request is
actionable, such as `clear-exact`, `clear-scoped`, `answered ... separate
actionable`, or `blockers resolved`; weak evidence such as `classified` or
`done` is not sufficient. Generic resolution markers such as `clarified` or
`no blockers` are also insufficient unless they name the resolved scope,
decision, blocker-question outcome, or remaining separate action.

An explicit review-only request for a diff, patch, working tree, or changed
files stays on the read-only `review` route even when the inspected subject
contains risk-domain nouns such as permission, security, billing, migration, or
credentials. Those nouns describe what to inspect; they do not authorize
product changes. A request that also asks to implement, refactor, commit,
release, or deploy follows the corresponding work route instead.

A short follow-up approval may continue an already settled discussion. The
classifier recognizes an explicit referential approval such as “그럼 그건
수정해줘” or “Then apply the agreed change” as `clear-scoped` when it has a
clear continuation cue and an action verb. A bare “진행해”/“수정해줘” remains
`vague-action`; without a valid parent capsule, carry the previous scope in the
context-complete `--request` rather than relying on
`--classification-evidence`. A delegated worker with valid capsule proof must
also carry the prior resolved scope in `--classification-evidence` (for
example, `clear-scoped continuation; previous scope resolved; user approval
confirmed; no scope expansion; blockers resolved`); unresolved or
open-question markers continue to block work routes.

Worker evidence reservations use validate-then-claim semantics. Intake first
validates that the opaque token matches the requested worker evidence path, and
consumes it atomically only after request classification and route acceptance
succeed. A rejected request leaves the reservation available for one corrected
retry; accepted intake claims it before writing preflight evidence.

Parent run evidence claims are exclusive per independent `start` invocation,
including two invocations with the same request fingerprint. Request identity
does not prove caller identity. Only the claimant may reuse its active binding,
and only by presenting the opaque run id returned by that claim; a second
caller must wait or receive a conflict before either caller enters preflight.
Run-owner evidence must bind a process expected to span the agent session. If
the host cannot prove that process identity, record no owner and retain the
bounded timestamp-recovery contract rather than substituting the short-lived
hook or its session leader. A binding whose recorded owner is provably gone is
released on the next claim, so waiting applies only to claimants that are alive
or unproven.

When the installed rules root is intentionally not a Git repository, execution
capsules bind it with a bounded, content-free directory fingerprint instead of
requiring callers to initialize another repository. The fingerprint excludes
runtime-generated state and caches, remains stable across those local outputs,
and invalidates the capsule when runtime source or guidance changes.

The start hook classifies the request and records the recommended route,
whether the Grill-Me protocol is needed, response mode, and a short reason. Use
the matching `<command>` in the start call. If `response_mode:
answer_first`, answer the user before routing or editing. When an answer-first
question asks how to start app, product, or feature work, the answer must include
PRD -> ARD -> implementation gates before lower-level coding steps. If
`grill_me: true` or legacy `question_drill: true`, run the recommended route
(typically `triage` or `ambiguity`) with `--request`, run a Grill-Me
`/grilling` session before implementation, and ask only the missing blocker
questions before proceeding. Prefer an installed Grill-Me skill when available;
otherwise use the built-in protocol from `common/skills/task-intake-effort-routing/SKILL.md`
and record its output.

Discover the supported values from the script itself:

```text
python3 <TAO_ROOT>/scripts/workflow.py list
```

Treat the executable `list` output as the only current command, platform, and
concern catalog. Do not maintain a second exhaustive prose list here; it drifts
when routing gains or removes values. Use `--concern` more than once when a task
crosses risk areas, and use `--format json` when another tool should parse the
route.

The router also infers the canonical `seo` concern from explicit public
discovery keywords in `--request`, such as SEO, AI search, AEO, GEO, AI
Overviews, AI Mode, `llms.txt`, sitemap, robots, canonical, Open Graph, and
structured data. Inference is a convenience, not a replacement for adding
specific `--concern` values when local context shows the risk.

Use the `metering`, `usage`, or `telemetry` concern for local runtime usage
metering, workflow label bridges, or Spill-related work. Do not use the
`tokens` concern for usage metering; `tokens` routes design-system token work.

Some concerns are baseline concerns. `stack`, `failure`, and `interaction` are
valid concerns, but their core cards are already loaded by every route through
`CORE_DOCS`; selecting them may add a route note instead of changing the document
list.

Examples:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command product --request "<USER_REQUEST>" --platform android --concern security --concern ui
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command bugfix --request "<USER_REQUEST>" --platform server --concern api
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command docs-review --request "<USER_REQUEST>" --concern wiki
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command product --request "Show me how we build an app feature here" --platform android --concern ui
<TAO_LAUNCHER> workflow validate
```

Do not force broad app/product requests through the `feature` route. The router
blocks `feature` when request classification recommends `product`, because that
would skip the PRD and ARD gates.

## Output Contract

The route output is the command manifest for the agent:

- `docs`: read these documents in order before editing or reviewing.
- `request_classification`: classify evidence attached from `--request`, when
  provided.
- `gates`: use these as the task checklist and report against them.
- `gate_ledger`: mark and show each gate as executed when it completes.
- `signal`: public state for completed or failed gates: `SUCCESS` or `FAIL`.
- `parallel_execution`: use this phase manifest to decide what can run in
  parallel and what must stay serial. It is the executable hint for runtimes
  that otherwise treat the gate list as one ordered chain.
- `repair_cycle_limit`: maximum retrospective-repair cycles for one failed
  scope; this must be `1`.
- `repair_policy`: required recovery sequence; this must be
  `retrospective_repair_verify_resume`.
- `resume_scope`: checkpoint where repaired work continues; this must be
  `first_failed_checkpoint`.
- `stop_condition`: terminal recovery condition; this must be
  `same_failure_after_repair_or_unsafe_repair`.
- `notes`: apply these routing hints before choosing commands or edits.
- `missing`: stop if this is not empty; fix the Tao Agent OS reference first.

Markdown output is optimized for direct agent reading. JSON output exposes the
same fields for wrappers, launchers, or CI checks.

## Automatic Gates

Work-producing, documentation, release, review, and retrospective routes must
include the relevant common gates below even when an individual command profile
forgets them:

- Required-document reading is route input rather than a separate finish gate.
  After routing and before work, read the route's `required_docs` / `Read First`
  list directly. Treat `reference_docs` / `Reference On Demand` as lazy context
  and open one only when the task touches that concern, platform, gate, or
  verification path. Do not add a separate confirmation command or receipt;
  the existing `source docs` finish evidence records the direct reading and the
  applied task-specific takeaway. Finish revalidates the required-document
  hash/size snapshot only when the route includes `source docs`; every route
  gate remains bound to the same execution capsule regardless of that scope.
- Treat an empty completed natural-language search as terminal `no_matches`:
  record the no-source result and continue with deterministic `required_docs`.
  Do not poll or retry discovery waiting for a document to appear. A route whose
  deterministic or promoted required path is absent is `invalid_manifest`;
  stop once with the missing paths and repair the manifest or source instead.
- Required gates cannot pass by recording a skip, not-applicable,
  unable-to-run, deferred, or follow-up reason unless that specific gate allows
  the outcome and the evidence names the allowed reason. Evidence that names an
  unresolved, must-fix, should-fix, blocking, or deferred issue must report
  `FAIL`; do not convert it into a successful note. Use missed-gate recovery
  and retrospective learning to make the next action path fix the issue.
- `source docs`: before feature, product, build, bugfix, refactor,
  simplification, workflow-setup, release, shipping, or general task
  implementation, search for repo-local source-of-truth documents that match
  the work type. Sources may be PRD, spec, ARD, issue, design note, task doc,
  ADR/RFC, module README, API contract, runbook, migration note, release note,
  test plan, skill/platform/workflow card, agent instruction, or equivalent
  product/source-of-truth document. Open and read any matching source before
  code or edits. If none exists, record the no-source result and decide whether
  the smallest useful artifact must be created before code or whether the
  current user request is enough for a no-durable-doc slice. Evidence must name
  the discovered source or the no-source result and say how it affected the
  work or documentation artifact decision.
  Treat planning, requirements, scope, acceptance-criteria, workflow-policy,
  public-contract, operator, architecture, API, release, migration, test-plan,
  and generated-public-artifact changes as durable-source signals until evidence
  proves otherwise.
  This is a pre-edit hard gate. Do not start implementation first and
  reconstruct the source-doc search afterward.
- `documentation impact`: before code, implementation, install/repair, or other
  edit work, decide whether the requested change affects durable documentation.
  This is the thinking checkpoint, not the final doc-update proof. Evidence
  must name the selected artifact class, affected doc path or doc class, the
  intended decision (`updated`, `created`, `unchanged`, or `not applicable`),
  and why the changed behavior, workflow policy, public contract, operator
  action, or acceptance criteria do or do not require a documentation update.
  `Not applicable` or `no docs` is valid only with a no-durable-doc reason such
  as answer-only, purely local, mechanical, no public contract, no operator
  action, or no acceptance criteria. If source docs are missing and the task
  changes durable behavior, create or update the smallest useful artifact
  instead of treating documentation as absent. Do not wait until finish to
  discover that docs were relevant.
  Use `unchanged` only when the evidence names the existing doc path or doc
  class inspected and why that document already covers the change. Do not use a
  generic `not applicable` or `no docs` decision when the same evidence says
  planning, requirements, acceptance criteria, workflow policy, public contract,
  operator action, architecture, API, release, migration, generated public
  output, or test strategy changed.
- `ambiguity check`: classify unknowns before implementation. If any blocker
  can change behavior, scope, risk, acceptance criteria, or verification, stop
  and ask the maintainer before editing. Do not continue with silent invented
  assumptions.
- `platform selection`: before PRD, ARD, architecture, or product
  implementation work, choose the affected platform card(s) or record why no
  platform is applicable. Do not write ARD or implementation plans while the
  platform surface is only a note.
- `alignment brief`: before requirements analysis, PRD/product delivery, or
  modification work, show the user a compact same/different/assumption summary.
  This is required even when the Grill-Me protocol is not needed. It should
  reduce later rework, not become a long questionnaire.
- `documentation`: update or create the relevant source-of-truth docs, or record
  why docs are not applicable or intentionally unchanged. Evidence must name the
  documentation decision, the affected source-of-truth doc path or doc class,
  and the reason the decision matches the behavior, workflow policy, public
  contract, operator action, or durable acceptance criteria changed.
- `retrospective check` (required gate): after verification and review but
  before finish, inspect the skills actually used and record
  `no_reusable_gap`, `reusable_gap`, or `no_skill_used` with the observation
  disposition.
- `skill-feedback` (optional hook): when the check finds a reusable gap, first
  record the retrospective with `observation: deferred`. The hook queues only
  one reusable content-free observation when its canonical skill id matches the
  current retrospective. Replace the gate with `observation: recorded` only
  after the hook creates or deduplicates that observation; otherwise keep
  `deferred`, which cannot fail finish. A repeated candidate becomes
  separate bounded
  skill-maintenance work rather than an immediate document edit. A failed
  required hook or gate never uses this path; it follows the repair cycle.
- `gate-batch` validates the complete batch before writing any entry. Structured
  fields alone are not enough: each record must also satisfy that gate's
  semantic evidence contract (for example, ambiguity evidence must explicitly
  resolve blockers, and an alignment brief must name shared understanding,
  differences, assumptions, and the user-visible checkpoint). After one batch
  validation failure, correct every reported record before the single retry. If
  the retry still fails, stop batching that scope, preserve this lesson, and
  record gates individually so the failing checkpoint is isolated.
  Before submitting a batch, use these complete evidence shapes for the two
  common semantic gates: `ambiguity check` must say whether blockers are absent
  or resolved and identify any safe assumptions; `alignment brief` must state
  the shared understanding, possible differences, unsupported assumptions or
  unknowns, and that the user-visible checkpoint occurred before edits. A
  merely affirmative phrase such as `scope is clear` or `alignment shared` is
  not complete evidence.
- `tests`: add, update, or run the closest useful test/check for code work. A
  skipped test must include the command skipped, reason, and residual risk.
- `boundary plan`: before code edits, name the owned boundary, file/module
  scope, caller-facing contract, or existing same-file scope, plus the nearest
  verification that will prove the change.
- `multi-agent split decision`: for code work, decide whether to spawn
  subagents/parallel workers. Use them when owned files/modules are disjoint and
  the shared contract is stable. If work stays serial, record why the change is
  too small, same-file, contract-bound, or otherwise not safe to split.
- `agentic run state`: for work-producing or multi-agent routes, record the
  current state, the next transition or resume point, the gate/command
  evidence that justifies that transition, the checkpoint or stop condition,
  and blocker status. This is the workflow's memory for continuation,
  repair-and-resume, review, delegation, and retrospective restart; route
  output alone is not execution evidence.
- `cycle contract`: for work-producing routes, state the current cycle type,
  input/source scope, allowed and forbidden changes, acceptance or verification
  method, stop condition, and next cycle/checkpoint before editing. This turns
  the task into one bounded cycle instead of an open-ended loop. Code review is
  a separate review cycle; implementation work may prepare for review, but must
  not claim that review happened unless a review route actually ran.
- `side-effect audit`: after implementation and before final verification or
  handoff, inspect the final diff for unexpected generated files, lockfiles,
  public-contract changes, external-state surfaces, broad formatting churn, and
  unrelated behavior. If investigation finds a possible meaning, policy, route,
  gate, or pass/fail interpretation change, pause for a meaning checkpoint
  before editing unless the fix is mechanical and already covered by explicit
  tests.
- `review readiness`: for docs-review routes, report the reviewed Markdown
  scope's frontmatter readiness, `status`/`type` distribution, and
  human-review queue. Link/frontmatter validity alone is not enough when the
  review is meant to judge whether guidance is ready for broad agent use.

`agent-finish-check.py` validates evidence for these gates. Missing evidence or
empty phrases such as "done" are not enough.

## Workflow Metering Contract

When changing workflow commands, route profiles, hooks, runtime prompt bridges,
permissions, or local metering setup, preserve the workflow label contract:

- every route command in `workflow_catalog.COMMANDS` must have a matching
  `SPILL_ROUTE_LABELS` entry;
- every required workflow action must have a matching `SPILL_ACTION_LABELS`
  entry;
- labels must remain reusable safe slugs, not task text, project names, file
  names, branch names, user names, or private content;
- setup, permission, label, hook-load, mock-payload, and diagnostic signals must
  not be reported as proof of real token usage;
- `workflow.py validate` and the routing tests must fail when a route, action,
  or concern change drops the metering contract.

Use `common/skills/local-tools/SKILL.md` for the usage evidence boundary. For actual usage
proof, require exact queued/imported local usage event evidence or the runtime's
approved exact-usage success marker; otherwise record no usage event and avoid
private-content reconstruction.

## Parallel Consumption

After `route` returns a document and gate manifest, read the
`parallel_execution` section before starting work. The `gates` list is the
required checklist; `parallel_execution.phases` is the scheduling hint that
shows which parts can overlap safely.

- Read independent route documents in parallel when the runtime supports it.
  Do not serialize `sed`, `cat`, `rg`, `find`, stack inspection, git status, or
  other read-only commands unless one result decides whether another command is
  needed.
- When unrelated dirty files are present, narrow Review Hook checks to the task
  boundary with `--review-path <path>` after the boundary plan names the owned
  files or modules. Pathspec review narrows git status, diff, structure, and
  VibeGuard file scans; VibeGuard uses changed-only fallback when the installed
  CLI does not yet support explicit path filters. Use the default
  `--review-scope working-tree` only when the whole current diff is part of the
  requested review.
- Treat `mode: parallel` phases as safe opportunities for concurrent read-only
  orientation or independent verification, subject to repo-local tool limits.
- Treat `mode: conditional_parallel` phases as parallel only after the route's
  split-decision, role, owned-scope, forbidden-scope, contract, and verification
  gates are recorded. If those cannot be named, execute that phase serially and
  record the concrete reason.
- Consume `parallel_execution.delegation_policy` before deciding. When its
  preconditions are met and the runtime exposes workers, delegation is
  automatic and does not require explicit user multi-agent wording. A missing
  user request is never a valid serial fallback; use one of the concrete safety
  or runtime-capability reasons from the policy.
- Treat one model-profile dispatch as a leaf worker, not fanout. The parent
  records the split decision first and remains the integration owner.
- At each parent-to-worker boundary, run `agent-hook.py handoff` to refresh the
  provider-neutral execution capsule once. A ready and valid
  capsule lets the worker reuse the parent's route, preflight, and required-doc
  evidence instead of repeating startup. A Codex child launch validates the
  capsule again immediately before it starts; an inspect-only handoff is never
  launch authority. Any mismatch is a successful fallback decision that
  requires the worker's normal lifecycle on a reserved, single-use-token
  evidence path. The parent remains the sole gate-ledger owner. Keep the detailed schema and runtime mapping in
  `docs/skills/agent-runtime-integration/SKILL.md` rather than duplicating it
  per runtime.
- Treat `mode: serial` phases as ordering barriers. Do not cross them with
  writes, generated artifacts, dependency changes, release config, migrations,
  shared contracts, same-file edits, or final reporting.
- The start hook must succeed before read-only orientation fans out. Treat its
  in-process preflight as a gate dependency: implementation, setup, update,
  fix, commit, push, release, migration, and external-state changes must wait
  until start succeeds.
- Do not parallelize commands that write the same evidence file, mutate project
  files, stage or commit changes, install/update guardrails, run fixers, publish
  artifacts, deploy, migrate data, or depend on one another's output.
- If a parallel read-only command fails, classify the failure before editing.
  Do not continue only because the other parallel commands succeeded.

## Gate Execution Ledger

For every scripted route, maintain a gate ledger while working:

```text
- gate: ...
  signal: SUCCESS | FAIL
  status: executed | failed | missed
  evidence: command, file, diff, note, or manual check
  repair_cycle: unused | 1/1
  resume_checkpoint: ...
```

Do not wait until the final response to reconstruct the ledger from memory.
Report a gate only when it succeeds or fails. Do not emit a public third state.

## Run State Ledger

For work-producing and multi-agent routes, keep a compact run-state line beside
the gate ledger:

```text
run_state: scoped
transition: scoped -> acting
evidence: boundary plan + multi-agent split decision recorded
checkpoint: implementation handoff
blockers: no blockers
next: implementation
```

Use these state names unless repo-local workflow defines a stricter model:
`intake`, `oriented`, `scoped`, `acting`, `verifying`, `reviewing`, `done`,
`blocked`, and `retrospective`. Update the state only when the transition has
evidence. After a failed required gate, set the resume point to
`first_failed_checkpoint`, complete the verified improvement required by the
repair cycle, and resume there instead of restarting unrelated work.

Do not use run-state notes to hide missing gate evidence. A run state is valid
only when the named route gates, commands, checks, or manual observations also
exist, and when it names the checkpoint or stop condition plus current blocker
status.

## Gate Signals

Gate signals are part of the workflow gate ledger, not a separate report. Check
them at two points:

1. Immediately after each gate or task step completes.
2. Before final report, commit, release, or handoff.

Use these meanings:

- `🐱🟢 SUCCESS`: the gate was executed and has evidence.
- `🐱🔴 FAIL`: the gate was missed, blocked, failed, or has no evidence after it
  should have run; follow missed-gate recovery.

After each completed gate or task step, emit a short progress signal in the
active conversation or handoff record:

```text
Gate signal: 🐱🟢 SUCCESS | gate: <gate> | evidence: <command, file, diff, note, or manual check> | next: <next gate>
```

Keep the signal short. It exists so humans and later agents can notice missed
gates immediately instead of discovering them only in the final report. Use only
`🐱🟢 SUCCESS` or `🐱🔴 FAIL` in human-visible text. Keep the plain `SUCCESS` or
`FAIL` value inside machine-readable fields so automation can still parse the
ledger.

Before finalizing, compare the route's `gates` with the ledger:

- Every required gate must be marked `executed` with evidence.
- Every required gate must be `🐱🟢 SUCCESS` before completion is reported.
- If the route includes a `review hook` gate, run
  `python3 <TAO_ROOT>/scripts/agent-hook.py review --review-outcome <pass|findings> ...`
  and record
  the hook result as that gate's evidence. Do not replace it with a memory-only
  manual review unless the hook is unavailable and the fallback is reported.
- If any required gate is missing, do not continue finalization.
- Treat a missing gate as an execution error even when the final code or docs
  look correct.
- If a route gate is truly irrelevant, stop and correct the route before
  editing; do not silently skip the gate inside a completion report.

## Executable Evidence Wrappers

When available, use the wrapper scripts to make the route and gate ledger
auditable instead of relying on memory.

The route output also contains a `Required Hooks` section. Treat it as the
workflow's executable checklist:

- `start` runs preflight before edits, reviews, commits, or completion reports.
- `review` runs after meaningful edits and before finish, commit, release, or
  handoff when the route marks it required.
- `finish` runs before final report, commit, release, or handoff and verifies
  route gate evidence.

Before editing, reviewing, committing, or reporting completion:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command <command> --request "<USER_REQUEST>" [--platform <platform>] [--concern <concern>]
```

The route may promote additional `required_docs` from the root
`workflow-doc-surfaces.json` map when the request text or known/touched paths
show a specific work surface. Rules may match route command, selected platform,
request text, request path references, explicit `--surface-path` values, and
paths from `git status --short --untracked-files=all`. UI-capable platform
work must be covered as a matrix, not as a one-off Android rule: Android
Compose, Application desktop UI, Flutter widgets, iOS SwiftUI/UIKit, KMP
Compose, Swift design-system UI, and Web React UI should each promote the
matching UI, state, structure, review, visual verification, and performance
guidance. This surface routing is for document selection only: it does not
replace request classification, command/profile selection, repo-local
instructions, or the requirement to read every routed `required_docs` entry
before edits.

The route/search layer uses the repository-pinned Wikimap source for
deterministic, incremental section retrieval over Tao Agent OS guidance. It
runs only `update --no-map` and `search --json`; do not wire Wikimap install,
hook, migration, semantic-note, source-editing, or Graphify-import commands into
the workflow. The ignored `.wikimap/` SQLite index is disposable. The pinned
source checksum is verified by the local adapter; provenance and license are
covered by the vendor manifest and integration tests. The previous in-process
scorer remains a reported recovery path when Wikimap cannot run.

Wikimap candidates are natural-language seed documents, not automatic policy.
Explicit task facets and `workflow-doc-surfaces.json` continue to select
deterministic required guidance. The local document graph, derived from
Markdown links, canonical skill-bundle entrypoints, and surface document sets,
expands the combined seeds into connected skill entrypoints, detailed
references, and explicit dependencies. Treat Wikimap seeds and ordinary graph
links as `reference_docs` so broad surfaces do not overload required reading.
Promote a result to `required_docs` only through deterministic route policy or
an explicit required relation such as frontmatter `requires_docs`.

Natural-language document discovery belongs in the routing/search layer, not in
the hook body. Hooks do not select or read documents for the agent. The
existing `source docs` gate validates evidence that the routed required docs
were read directly and applied. The router and `workflow.py query` carry
retrieval through Wikimap, then apply reusable policy facets such
as cleanup, review, verification, UI feature work, skill docs, or document
routing and use the local document graph to add connected candidates. Target
projects continue to use Graphify for code symbols, architecture, and
relationships; Wikimap does not replace the project graph or its readiness
gate.

Wikimap completion is explicit: `no_matches` is a terminal no-source result,
while `invalid_manifest` names route paths that are actually missing. Neither
state may enter an unbounded discovery retry loop. The first continues with
deterministic guidance; the second stops for a source or routing repair.

The command includes task-specific arguments, but persistent runtime permission
prefixes must not. For Codex escalation, request only
`["python3", "/absolute/path/to/tao-agent-os/scripts/agent-hook.py"]` as the
saved `prefix_rule`; for Claude and AGY, allow only the equivalent absolute
wrapper command plus the runtime's trailing argument wildcard. Never save
`--project`, `--request`, `--gate-record`, `$HOME`, `$(pwd)`, or user text in the
permission prefix.

`agent-hook.py start` runs the preflight logic in-process and writes the same
preflight evidence. Calling `agent-preflight.py` directly is acceptable only as
a lower-level wrapper path when the start hook is unavailable.

After preflight, read every route `required_docs` entry directly before edits or
review. There is no separate document-confirmation command, receipt artifact,
or standalone document-reading gate. The existing execution capsule records the
preflight fingerprint, route fingerprint, and hashes of that required-doc set;
the `source docs` finish gate validates this binding without reintroducing a
read hook. Its structured record is populated with the exact routed
`required_docs` manifest, not an agent-supplied count or empty-manifest claim;
finish rejects an empty claim for a non-empty route. Record the direct reading
and applied takeaway in finish evidence.
`reference_docs` remain on-demand context. An empty `required_docs` list is a
valid document-free route state; record the no-source decision and continue
once rather than retrying discovery or holding the capsule in preflight.
When the task intentionally updates one of its own `required_docs`, the final
structured `documentation` record must use `decision=updated` and name that
exact route-relative path as `target`. Finish preserves the original capsule
snapshot and permits only that declared path to differ; an undeclared required
document change still fails the source-doc binding instead of creating a
finish/handoff deadlock.
When more than one routed required doc changes, record one `documentation`
`SUCCESS` entry per exact path. Do not combine required-doc paths in one
`target` string; the gate hook rejects that shape before finish.

Before invoking the review hook, compare the current ledger with the gates that
precede `review hook` in the active route. When any prerequisite gate is
missing, `FAIL`, or structurally incomplete, the hook rejects the invocation
before review begins. This rejection must not record a failed review checkpoint,
start a repair cycle, or request a repair receipt; record the current facts
through `gate` or `gate-batch`, then rerun the same review hook. Only a review
that starts after all prerequisites are complete can enter failure repair. Gates
that follow `review hook`, such as `retrospective check` and `report`, remain
closeout work and are not review prerequisites.

Treat a package-role boundary as an evidence requirement even when the task did
not create a new folder. When the reviewed package contains multiple roles,
write `--structure-review-evidence` with all five literal labels:
`owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...;
verification: ...`. “No new package boundary” or a general structure summary
does not replace any field.

Before invoking the finish hook, compare the current ledger with the complete
route gate list. If the route ends in `handoff`, record that gate as a
`SUCCESS` readiness checkpoint after verification, review, and retrospective
work are complete. This route gate means the final handoff target, artifacts,
and blocker state are ready; it is distinct from `agent-hook.py handoff`, which
only prepares a parent-to-worker execution capsule. Because finish validates
every route gate, waiting until after finish to record this readiness creates a
finish/handoff deadlock and is not a valid ordering.

Immediately before every `finish` invocation, read the current route gate list
and the current ledger together. Do not infer closeout readiness from a
successful review alone. When `handoff` is the final route gate, record its
user-facing readiness evidence in the ledger first, then invoke `finish`.

Treat a successful review as an intermediate checkpoint, not finish readiness:
record `retrospective check`, then every remaining closeout gate including the
user-facing `handoff`, and only then invoke the finish hook.

Before final report, commit, release, or handoff:

```text
python3 <TAO_ROOT>/scripts/agent-hook.py finish --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE>
```

Do not wait until finish to write all gate evidence by hand. The only gate-state
writers are the `gate` and `gate-batch` hooks, which require an explicit
`SUCCESS` or `FAIL` status. The default path is a structured gate ledger at
`<TARGET_REPO>/.tao/gate-evidence.json`, bound to the current
preflight evidence hash, route fingerprint, and stable execution-capsule
fingerprint (the preflight, route, and required-document snapshot). Custom preflight evidence files
use `<preflight-stem>-gate-evidence.json` so parallel jobs do not overwrite one
another's ledger. `agent-hook.py finish` is read-only: it accepts no inline gate
evidence and never infers state from prose or mutates the ledger while it
validates completion. Removed inline input receives a migration error directing
the caller to `gate` or `gate-batch` first.

The `start` and `review` hooks record their own successful gate evidence in the
ledger. `review hook` is a hook-owned gate: generic `gate` and `gate-batch`
input must reject it regardless of the caller-supplied `source` value. The
review command additionally writes an atomic run-local review attestation bound
to the current run id, preflight hash, route fingerprint, complete worktree
fingerprint, exact review pathspec, and changed-path count. Finish must validate
that attestation and its ledger binding before accepting `review hook`; a
missing, copied, stale, or scope-mismatched attestation makes the gate missing.
Finish must revalidate the attestation after all final checks and immediately
before it reports completion. Its earlier validation only establishes that the
final checks may start; bytes changed while those checks run must fail closed.
This does not prohibit a legitimate pathspec review of an explicitly owned
slice—the exact scope is attested and may not later be widened by prose.
For gates that only the active agent can prove, batch
structured records instead of spawning one shell process per gate:

```text
python3 <TAO_ROOT>/scripts/agent-hook.py gate-batch --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --gate-record '[{"gate":"cycle contract","fields":{"cycle_type":"workflow_setup","input_scope":"<safe-source-scope>","allowed_changes":"<safe-scope>","forbidden_changes":"<safe-boundary>","acceptance_criteria":"<safe-criteria>","verification":"<check>","stop_condition":"<condition>","checkpoint":"<handoff-or-next-cycle>"}},{"gate":"agentic run state","fields":{"state":"scoped","transition":"scoped -> acting","evidence":"<gate-or-command>","checkpoint":"<resume-or-handoff>","blockers":"<none-or-current-blocker>"}},{"gate":"boundary plan","fields":{"scope":"<owned-scope>","verification":"<nearest-check>"}}]'
```

Every mutating ledger path revalidates the run claim the registry holds for the
evidence file being written. Registry claim validation and ledger mutation must
share one atomic transaction. The global lock order is
`project-state -> run-registry -> gate-ledger`; all append, reset, resync, and
capsule-bind paths use
that same order. A second unlocked claim check narrows a race but is not atomic
evidence that the claim still exists when the ledger changes. The project is
derived from that file's own `.tao`
root, never from a preflight field, so a caller cannot redirect the check at a
registry that holds no claim. Writability is wider than liveness: a run that a
failed finish left `failed`, or that a repair cycle parked at
`reconcile_required`, stays writable precisely so its owner can record the
missing gate facts and rerun finish, while `completed` and `cancelled` are
closed because a settled run must not gain new evidence. When launcher-anchored
owner evidence exists, only that same process owner may append, reset, resync,
or capsule-bind the ledger; another live session is refused before it can
replace a later `FAIL` with its own `SUCCESS`. A run recording no owner keeps
its compatibility path only inside the registry's shared stale window, since
recency is the sole identity left. New top-level starts without an explicit
evidence path allocate a
run-local `.tao/runs/<opaque>/preflight.json` even when the runtime exposes no
session id, so independent ledgers are physically separated by default.
An ownership or worker-boundary refusal happens before ledger mutation. The
`gate` and `gate-batch` hooks report it as `fix_invocation_and_rerun`; no
checkpoint failed, so the caller must correct its evidence or run ownership and
must not enter `repair-verify` for that rejection.

Use this ledger to capture what happened, not to craft magic validator prose.
Finish rejects a required ledger record whose capsule fingerprint does not
match the current validated capsule. This applies to every required gate, not
only `source docs`. Ledger order is authoritative per checkpoint: a later
`FAIL` invalidates an earlier `SUCCESS`, and only a later verified `SUCCESS`
restores that gate. A later incomplete `SUCCESS` cannot fall back to an older
complete record.
If a structured entry is missing required fields, finish-check should fail and
the recovery is to complete or record the missing gate fact, not to add a vague
sentence. Use `agent-hook.py gate` for a single immediate gate and
`agent-hook.py gate-batch` for a bounded set. Keep the evidence machine-clear
instead of relying on equivalent prose or alternate key spellings. Use the
Graphify readiness fields exactly as `cli`, `skill_doc`, `runtime_links`,
`runtime_ownership`, `project_integration`, `graph`, and `query_smoke`, with
every value exactly `success`; keep
descriptive facts in separate gate evidence rather than keyword-parsing the
status. For `source docs`, say which
source-of-truth class was searched and opened before implementation and how it
affected the decision. For `documentation`, include the literal decision
(`updated`, `created`, `unchanged`, or `not applicable`), the doc path or class,
and the durable-contract reason. Add or improve structured ledger fields when
the same semantic evidence repeatedly fails manual parsing; do not keep
retrying paraphrases.

For explicit `commit` or `git_commit` routes, dirty-path surface documents stay
in `reference_docs` by default. The commit workflow's small required set and
freshness checks are sufficient unless an explicit concern, repo-local policy,
or review finding escalates a surface. This prevents an already-implemented
diff from reopening the full implementation reading and verification lifecycle.

For structured `gate-batch` records, use the field names consumed by the
ledger synthesizer. Parallel `multi-agent split decision` records require
`mode`, `reason`, `owned_scope`, `forbidden_scope`, `contract`, `acceptance`,
`integration_owner`, and `verification`; do not rename `contract` to
`contract_brief` or `acceptance` to `acceptance_checks`. `side-effect audit`
requires `scope` and `result`. A successful record-write message proves only
that the ledger entry was stored; finish-check remains the authority on whether
its fields satisfy the gate contract.

Gate and gate-batch hooks validate structured `SUCCESS` fields before writing
the ledger. Parallel multi-agent validation returns the base and parallel-only
missing fields together, rejects alias keys, and validates the structured
delegation plan before worker execution. Existing incomplete ledgers remain a
finish failure, but finish reports their full missing-field set at once so the
single repair cycle does not uncover a second hidden layer.

A later complete record for the same gate is a valid correction for a legacy
incomplete ledger entry. Once merge selects that complete replacement, it must
clear the older missing-field diagnostic; obsolete omissions must not consume
the repair cycle after the gate has actually been corrected.

Structured evidence synthesis preserves the original evidence note alongside
the canonical fields for `source docs`, `documentation impact`, and
`documentation`. This prevents an inspected/read or coverage explanation from
being lost when the ledger renders fields into validator text. Collaboration
validators treat equivalent Korean and English terms (for example `병렬` /
`parallel`, `워커` / `worker`, `소유 범위` / `owned scope`, and `검증` /
`verification`) the same way, while explicit negation such as `워커 불필요` or
`병렬 안 함` remains a serial decision and does not create a false delegation
plan requirement.

`agent-hook.py finish` runs the finish-check logic in-process. Calling
`agent-finish-check.py` directly is acceptable only as a lower-level wrapper path
when the finish hook is unavailable.

`agent-preflight.py` records the route manifest, current git status, and
VibeGuard audit result in `<TARGET_REPO>/.tao/preflight.json`.
It also records a content-free summary of accepted and promoted global lessons
from `~/.tao/` when that local store exists.
When `--request-classified` is used, it must also record
`--classification-evidence`; otherwise request intake is treated as skipped.
That evidence alone does not honor the flag: a ready and valid parent execution
capsule must back it, or the classifier evaluates `--request` as usual.
For work routes, that evidence must include a resolved-scope signal rather than
a generic `classified`, `done`, `handled`, `clarified`, or `no blockers`
marker.
`agent-finish-check.py` requires evidence for every route gate. It reuses a
current successful review's workflow validation and scoped `git diff --check`
result; otherwise it runs those checks itself. Read-only work against a path
outside Git skips the structurally unavailable diff check, while a writing task
outside Git still fails closed. It uses the task-local VibeGuard audit cache
when both the target project git state and Tao Agent OS rules git state are
unchanged. Failed VibeGuard invocations must not be cached; rerun the tool after
transient failures. Finish-check writes
`<TARGET_REPO>/.tao/finish.json`.
It also writes `gate_signals`, `missed_gates`, and
`retrospective_required`. When `retrospective_required` is true, it writes a
safe lesson candidate under `~/.tao/lessons/inbox/` when permitted.
If the route classification or stored request text requires Grill-Me, the finish
check must receive Grill-Me protocol evidence through a gate such as
`grill-me if needed=</grilling session/output evidence>`. Legacy
`question drill if needed=<evidence>` is accepted only when it still names the
Grill-Me protocol, skill, or `/grilling` session and output. Missing Grill-Me
evidence is a `🐱🔴 FAIL` signal and blocks completion until missed-gate
recovery and retrospective learning run.
Human-visible wrapper output uses only `🐱🟢 SUCCESS` and `🐱🔴 FAIL`.

Treat missing wrapper evidence as non-compliant. If the wrappers are unavailable,
the agent must still run the same underlying checks manually and report the
fallback explicitly. VibeGuard `Needs review` cannot be called complete unless
the state is reported and an explicit `--allow-vibeguard-review` reason is
recorded. Command failure, `🐱🔴 FAIL`, missing route evidence, or missing
VibeGuard output remains a blocker.

## Missed Gate Recovery

If the agent missed any required gate:

1. Stop finalization before final report, commit, release, or handoff.
2. Identify the exact gate that was skipped and what work happened after it.
3. Preserve `first_failed_checkpoint` as the resume point; do not restart the
   whole route.
4. Roll back only dependent agent-made changes after that checkpoint when safe.
   Preserve pre-existing user changes and ask before destructive cleanup.
5. If finish-check sets `retrospective_required` or the hook/gate returns
   `FAIL`, run the canonical
   `workflows/skills/retrospective-learning/SKILL.md` repair cycle. Improve the
   owning Tao Agent OS guidance, hook, validator, or test and verify that
   improvement. A lesson candidate or correction-plan note alone is
   insufficient. For finish-check evidence failures, the improvement must make
   the validator's required evidence fields clear and testable.
6. Resume the original task at `first_failed_checkpoint`, cite the verified
   improvement, and refresh downstream evidence that depended on the failed
   scope. This is continuation after repair, not an unchanged retry.
7. Stop if the same failure signature recurs, the repair is unsafe or
   ambiguous, canonical source ownership is uncertain, verification fails, or
   the single repair cycle would be exceeded.

The route enforces `repair_cycle_limit=1`,
`repair_policy=retrospective_repair_verify_resume`,
`resume_scope=first_failed_checkpoint`, and
`stop_condition=same_failure_after_repair_or_unsafe_repair`. The complete
failure-repair decision rules remain owned by the retrospective workflow.
Successful-task candidate deduplication is a separate non-blocking policy in the
same skill bundle.

## Command Profiles

The current script exposes these stable command profiles:

- `triage`: request clarity, effort routing, and Grill-Me blocker questions.
- `workflow-setup`: local agent prompt, hook, workflow label bridge, or metering setup.
- `docs-review`: documentation review with wiki/doc-maintenance checks.
- `task`: general multi-step agent work.
- `ambiguity`: classify blockers, researchable unknowns, assumptions, and
  out-of-scope items before planning or implementation.
- `prd`: produce or update a PRD/product requirements note before ARD or code.
- `product`: PRD -> ARD -> review -> code -> review -> tests -> UI tests ->
  commit readiness.
- `feature`: scoped feature implementation.
- `bugfix`: reproduce, isolate, fix, and regression-check.
- `refactor`: behavior-preserving cleanup.
- `docs`: documentation-only update.
- `planning`: research, compare, and recommend before implementation.
- `review`: review and commit-readiness check.
- `commit` / `git_commit`: lightweight local commit preparation. Run review
  first, stop on findings, then record commit readiness for the staged diff.
- `multi-agent`: delegated or parallel agent work with explicit write scopes.
- `release`: packaging, deployment, migration, or rollback-sensitive work.
- `retrospective`: apply the canonical failure-repair workflow after a failed
  required hook or gate, or run a separately scoped skill-maintenance review for
  queued successful-task feedback.

## Agent Consumption Rule

For a multi-step task:

1. Identify the target repo and repo-local instructions.
2. Run `agent-hook.py start` once before selecting task documents, editing,
   reviewing, committing, or reporting completion. Do not separately rerun
   classify, route, or preflight after it succeeds.
3. Read the route stored by start as the task command manifest.
4. Load `required_docs` / `Read First` in order; load `reference_docs` only
   when the task touches that concern, platform, gate, or verification path.
5. Follow the listed gates before editing, reviewing, testing, or committing.
6. Execute project commands only from trusted repo-local instructions.
7. Report verification and residual risk against the route gates.

If the script output conflicts with repo-local instructions, repo-local
instructions win. If the route is missing a concern that the task clearly touches,
add the concern manually and report the gap.

If the workflow router is unavailable, rejects a route, or cannot run, stop and
report the blocker before continuing. Use prose-only routing from `index.md`
only for simple answer-only work or after the user explicitly accepts the
fallback.

## Script Creation Rule

Create or update a Python workflow script when all of these are true:

- The workflow is repeated across projects or agent runtimes.
- The steps can be represented as command profiles, document routes, gates, or
  checklists.
- The script can run without network access and without project-specific secrets.
- The script improves consistency without hiding judgment from the agent.

Do not put product-specific paths, credentials, private service names, local
branch names, or repo-only commands in a shared workflow script. Keep those in
repo-local instructions or repo-local scripts.

## Script Safety

Shared workflow scripts should default to route generation and validation. They
should not execute arbitrary project commands, mutate a repo, install
dependencies, or call external services unless a repo-local trusted wrapper asks
for that behavior explicitly.

Every shared workflow script should support a validation mode that checks its
referenced documents or profiles. Agents should run validation after changing the
script or adding/removing routed documents.

## Handoff Output

When a scripted route was used, include this in the final report:

```text
Workflow route:
- command: ...
- platform: ...
- concerns: ...

Verified:
- python3 <TAO_ROOT>/scripts/workflow.py validate
- ...task-specific checks...

Gate ledger:
- signal: SUCCESS / gate: ... / evidence: ...
```

## Stop If

- The script references missing documents or stale command profiles.
- The script route conflicts with repo-local instructions on security, data,
  release, cost, or verification.
- The route omits a platform or concern that the task clearly touches.
- The script would need to mutate the target repo, execute project commands,
  install dependencies, deploy, spend money, or access credentials.
