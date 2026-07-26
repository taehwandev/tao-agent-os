---
keyflow_id: sys_agent_entrypoint
status: stable
type: human-reviewed
---

# Tao Agent OS Shared Agent Instructions

This file is the entrypoint for agents that consult the shared Tao Agent OS library.

## Purpose

Use this library to prevent repeated mistakes across repositories. It provides
shared operating habits, review criteria, architecture principles, and platform
guidance. Repo-local instructions remain the source of truth for project paths,
commands, naming, domain rules, and product-specific policy.

## Project Discovery Entry

At the start of work, identify the target project from the user's request and
the current working directory. When the runtime starts from `~`, another
non-project directory, or a directory that may not be the requested target, use
the local project entry helpers before project work when they exist:

```text
<TAO_LAUNCHER> agent-entry
<TAO_LAUNCHER> project-discover
```

Continue only when discovery returns `selected`. If it returns `ambiguous` or
`not_found`, ask the user for the target project instead of guessing from the
prompt. Keep discovery cheap by preferring the current directory, explicit
paths, registry aliases, and known search roots over broad home-directory
scans. After selection, read the target project's local instructions before
using shared Tao Agent OS guidance.

When starting or relaunching a runtime, make the selected target project the
primary workspace. For Codex, use `codex -C <TARGET_REPO>`; add
`--add-dir <TAO_ROOT>` only when the current task must include the
shared Tao Agent OS root in the session workspace. Instruction files define agent
behavior; runtime launch roots define filesystem scope and prevent repeated
permission prompts.

When one product spans multiple repositories, keep that product as a local
workspace group in `~/.tao/projects.json`. Treat the first selected
repo as the primary repo for acceptance. If investigation shows that another
repo is the source of truth or must be written, stop before that write and
record a workspace scope checkpoint: starting primary, secondary/source-of-truth
repo, selected mode (`primary-led secondary read`, `primary-led secondary
write`, or `multi-session`), write scope, and cross-repo verification.

## Shared Guidance Boundary

Write Tao Agent OS guidance as a reusable common baseline, not as the operating
model of one product, service, vendor, customer, team, or repository. A rule
belongs in this shared library only when it remains correct after removing
service names, product policy, local paths, command names, account names,
environment names, API names, and domain vocabulary.

When a lesson comes from a specific service, generalize only the recurring risk,
decision rule, load condition, and verification question. Keep service-specific
workflows, permissions, role matrices, provider setup, deployment details, API
shapes, and product policy in the target repo's local instructions or in an
explicitly scoped platform or product-pattern document.

## Project LLM Wiki Boundary

Project-specific LLM wiki content belongs in the target project, not in this
shared library. This includes generated repo wikis, code-derived module
summaries, project runbooks, product decisions, local commands, local paths,
service setup, role matrices, and domain policy for one repo or product.

Tao Agent OS may define reusable rules for creating, reviewing, refreshing, and
reading LLM wiki pages. Those meta-rules live in:

```text
<TAO_ROOT>/common/skills/llm-wiki-documentation/SKILL.md
<TAO_ROOT>/common/skills/llm-wiki-documentation/references/current-guidance.md
```

When applying Tao Agent OS to a target repo, read the target repo's local LLM
wiki only after repo/runtime instructions, the workflow route, and the relevant
skill entrypoints. Treat project LLM wiki pages as navigation or source-derived
summaries unless the target repo explicitly marks a reviewed page as a source of
truth. Generated wiki pages must not override repo instructions, workflow gates,
human-authored design decisions, or source docs.

## Language Policy

Write shared agent library documents in English. This includes `AGENTS.md`,
`index.md`, `common/`, `platforms/`, `product-patterns/`, `workflows/`, and
`templates/`. Public-facing site copy under `docs/` may be localized, but it
must not become the source of truth for agent guidance.

## Metadata Policy

Use frontmatter `status` as the readiness signal and `type` as provenance or
review state. Do not ignore a document only because `type` is `ai-generated`
when `status` is `review` or `stable`; instead, treat `draft` as provisional,
`review` as active, and `stable` as broad-use guidance. The `keyflow_id` field
is retained for metadata compatibility and should not be renamed casually.

## Priority

When instructions conflict, follow this order:

1. System and developer instructions from the active agent runtime.
2. The user's current request.
3. The target repo's local instructions, such as `AGENTS.md`, `CLAUDE.md`,
   `CODEX.md`, `.agents/README.md`, `CONTRIBUTING.md`, or an explicitly
   documented local override file.
4. More specific shared Tao Agent OS documents, such as platform or product-pattern docs.
5. Shared Tao Agent OS common cards.
6. General guidance in `README.md`.

If the conflict changes behavior, verification, security, or data handling, call
it out before or after the work.

## Always Read For Agent Work

For implementation, review, refactoring, debugging, documentation, or planning tasks, first consult:

```text
<TAO_ROOT>/common/skills/agent-operating-skill/SKILL.md
```

Then load only the supporting documents relevant to the task.

## Document Output Conventions

When creating PRDs, specs, or ARDs, follow the path and naming rules in:

```text
<TAO_ROOT>/common/skills/doc-conventions/SKILL.md
```

Repo-local instructions override this guide. Always state the output path in the
handoff.

## Required VibeGuard Gate

VibeGuard is mandatory for Tao Agent OS maintenance and for repos that apply
Tao Agent OS. Before documentation, code, configuration, dependency, data,
deployment, or credential changes, run the VibeGuard audit for the target repo.
When applying Tao Agent OS to another repo, do not run VibeGuard `setup` or
`update` blindly; use the application drill in `docs/skills/agent-bootstrap/SKILL.md` when
the target already has agent instructions or guardrails. Use `update` only when
the user explicitly chooses to refresh an existing managed VibeGuard block;
otherwise run audit with the current guardrails.
For this repo, use the current VibeGuard command policy documented in
`VIBEGUARD.md`. During local maintenance, prefer an installed `vibeguard`
binary when the environment provides one:

```text
vibeguard audit . --rules .
```

Use the published package command only when no trusted installed binary is
available or when a task explicitly needs the latest published package:

```text
npx --yes @taehwandev/vibeguard audit . --rules .
```

When actively developing or validating a local VibeGuard checkout, this fallback
is acceptable:

```text
node <VIBEGUARD_ROOT>/src/cli.js audit . --rules .
```

Run it again before finishing. Use `--fix` only for low-risk safety fixes, and
never print detected secret values. If VibeGuard cannot run, stop and report
the blocker instead of treating it as optional.

## Required Workflow Script

For every multi-step task, run the shared start hook once before selecting
documents manually, editing, reviewing, committing, or reporting completion.
The start hook performs workflow routing and preflight in one lifecycle entry;
do not separately repeat workflow list, classify, route, or preflight after it
succeeds:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <command> --request "<USER_REQUEST>" [--platform <platform>] [--concern <concern>]
```

`--command` accepts a workflow route, not a stage label. For implementation work,
use the closest route such as `bugfix`, `feature`, `build`, or `task`; `implement`
is an execution-stage label and is not a valid route command. When uncertain,
confirm the current route choices with `<TAO_LAUNCHER> workflow list` before
running the hook.

Use the start output as the route, document, and gate manifest, then execute the
task with the target repo's local commands. Read every route `required_docs`
entry directly before work. Direct `<TAO_LAUNCHER> workflow route` and `<TAO_LAUNCHER> agent-preflight`
invocations are lower-level diagnostic or compatibility fallbacks only when the
start hook is unavailable; never run them as a second startup sequence. The
start hook must always receive the current user request. A top-level or
first-touch agent passes `--request "<USER_REQUEST>"` with the real request and
lets the classifier decide; when it returns clarify-first or Grill-Me, run that
protocol rather than routing around it. A delegated worker may add
`--request-classified --classification-evidence "<evidence>"` only when the
ready and valid parent capsule binds that reuse to the earlier intake. Without
that capsule the flag is not honored and the classifier runs on `--request` as
for any other caller; `--request-classified` with neither a request nor a
capsule is rejected. The flag is not a same-session root override: when the user
gives a terse follow-up, pass
a context-complete `--request` that preserves the verbatim follow-up and names
the already-established scope, without `--request-classified` unless the
capsule proof exists. If the established scope cannot be stated safely, route
through `triage` or `ambiguity`. Do not use `--request-classified` to bypass
direct-question, ambiguity, or Grill-Me handling. A caller that only needs the
document listing and label context and is asserting no request intake uses
`--advisory`, which satisfies no downstream gate; work must be re-routed with a
real `--request` before editing, reviewing, or reporting completion.
Classification evidence that still says `vague-action`,
`broad-product`, `risky-unclear`, `direct-question`, `answer_first`,
`clarify_first`, `ambiguous`, `unclear`, `grill_me: true`, or
`question_drill: true` and their obvious hyphen/space variants must route only
to `triage` or `ambiguity` until the evidence states clear scope, a separate
actionable request, or resolved blockers. For work routes, weak evidence such
as `classified`, `done`, or `handled` is not enough; the evidence must contain
a positive resolved-scope signal such as `clear-exact`, `clear-scoped`,
`answered ... separate actionable`, or `blockers resolved`. Evidence that says
`not clarified`, `unresolved`, `open questions`, or equivalent blocker-open
language remains blocked even if it also contains a resolution word. Generic
resolution markers such as `clarified` or `no blockers` are not enough unless
they name the resolved scope, decision, blocker-question outcome, or remaining
separate action. If the request is a direct question,
answer it before editing,
routing, or running project-specific work. If the script is unavailable, cannot
run, or the route is missing a clearly relevant concern, stop and report the gap
before continuing. Use `index.md` as a fallback only for simple answer-only work
or after the user explicitly accepts the fallback.

The workflow router also promotes required docs from
`workflow-doc-surfaces.json` when request intent or known/touched paths reveal a
specific work surface. This is the root-level document routing map for common
agent tasks such as workflow script changes, request classifier work, tests,
skill cards, agent instruction files, UI-capable platform work, and shared
Tao Agent OS docs. Request-intent rules may match the route command, selected
platform, request text, and reusable document sets; for example screen, list,
favorites, or explicit framework choices on Android, Application, Flutter, iOS,
KMP, Swift, and Web surface the matching UI, state, structure, review, visual
verification, and performance guidance, of which the best-matched cards are
promoted and the rest stay reachable in `reference_docs`. `<TAO_LAUNCHER> workflow route`
automatically extracts path-like references from `--request`, and
`<TAO_LAUNCHER> agent-preflight` also adds paths from
`git status --short --untracked-files=all`. Use
`--surface-path <path>` only when a launcher already knows an in-scope path that
does not appear in the request or current git status. Surface promotion may
move a document from `reference_docs` to `required_docs`; it is best-effort
under the selection budget below, and it never replaces repo-local instructions
or the normal route command/profile selection.
The router also builds a local document graph from Markdown links, canonical
skill-bundle entrypoints, and `workflow-doc-surfaces.json` document sets. Natural
language search should find seed docs; the graph then follows nearby relations
so agents see connected guidance without the user naming every keyword. Loose
graph relations become `reference_docs`; only explicit required relations such
as frontmatter `requires_docs` may promote an additional doc to `required_docs`.

`required_docs` names the document that holds a skill's actual rules, not a
pointer to it. Most `<skill>/SKILL.md` entrypoints are generated stubs whose
only content is a link to `references/current-guidance.md`; the router replaces
such an entrypoint with that reference. An entrypoint carrying guidance of its
own is kept alongside its reference, and an entrypoint with no reference on disk
is kept unchanged. Core is the deliberate exception: its entrypoints are never
resolved, because the operating-skill reference is large and identical on every
route while AGENTS.md already states the always-on operating contract. Open
`common/skills/agent-operating-skill/references/current-guidance.md` from
`reference_docs` when the task turns on operating-skill detail.

Required-document selection is bounded. Beyond the always-required core, the
router fills a byte budget and a document cap in priority order: the command's
own skill, then documents matched to this request's text and touched paths, then
the selected platform card set, then the contracts of the gates the route will
enforce, then general code-work discipline. Selection stops at the budget rather
than skipping a document that does not fit, so the most specific match is never
starved by a smaller, less relevant one. Surface and graph promotion are
therefore best-effort: a relevant document may legitimately remain in
`reference_docs`, and it must still be opened when the task touches it. Gates
that reject work, namely the review hook and the multi-agent split decision,
always keep their contract document in `required_docs` and are never dropped by
the budget; a route may not enforce a gate whose contract it withheld.

Natural-language document discovery is a router responsibility, not a hook
responsibility. The router/search layer uses the repository-pinned Wikimap
backend to incrementally index Tao Agent OS guidance without a model or network
call, then overlays explicit workflow facets and the local document graph.
Wikimap matches are candidate/reference seeds; only route policy or an explicit
required-doc relation promotes a required document. Hooks do not run search
logic, read documents for the agent, or mutate the route. The existing `source
docs` finish evidence records the agent's direct `required_docs` reading and
applied task-specific takeaway. When recording this gate through structured
`gate` or `gate-batch` input, include the exact fields `required_docs`, `source`,
and `takeaway`; prose evidence alone does not satisfy the gate. Target-project
code, architecture, and relationship analysis remain Graphify responsibilities.
An empty Wikimap result is a terminal `no_matches` no-source outcome, not a
reason to poll, re-route, or wait; continue with the deterministic
`required_docs` and record the no-source decision. A route that names a missing
required document is instead an `invalid_manifest` failure with concrete repair
paths and must stop once rather than retry search.

Discover valid commands, platforms, and concerns with:

```text
<TAO_LAUNCHER> workflow list
```

When the right document is not obvious from `index.md`, search by keyword:

```text
<TAO_LAUNCHER> workflow query <keyword> [<keyword> ...]
```

The query command uses the pinned Wikimap source to return exact sections and
lines, while preserving the existing `<TAO_LAUNCHER> workflow query` interface. It requires
no separate install, model call, or network access at query time; its disposable
SQLite cache stays under ignored `.wikimap/`. Explicit Tao Agent OS facets
remain a policy overlay for phrases such as code cleanup, change review,
verification, UI feature work, skill docs, or document routing, and the local
document graph surfaces connected skill entrypoints and references. If Wikimap
cannot run or its checksum is invalid, the command falls back to the prior local
scorer and reports that backend in structured output. Use it instead of reading
all of `index.md` when the concern is narrow or the document name is unknown.
Then load only the matched documents relevant to the task.

The route output contains `request_classification`, `docs`, `required_docs`,
`reference_docs`, `gates`, `gate_ledger`, `skill_feedback`, `repair_cycle_limit`,
`repair_policy`, `resume_scope`, `stop_condition`, `notes`, and `missing`.
The recovery contract is `1`, `retrospective_repair_verify_resume`,
`first_failed_checkpoint`, and
`same_failure_after_repair_or_unsafe_repair`. Read `required_docs` in order
before editing or reviewing. Treat `docs` as the full candidate manifest and
`reference_docs` as lazy, on-demand context; open a reference only when the
current task touches that concern, platform, gate, or verification path. Follow
the gates as the task checklist, and stop if `missing` is not empty. Public gate
and hook signals must use only
`🐱🟢 SUCCESS` or `🐱🔴 FAIL`. Do not introduce any third state in human-visible
reports or machine-readable hook status. Completion requires every required
gate to be `🐱🟢 SUCCESS`. If a
required gate fails or lacks evidence, report `🐱🔴 FAIL`, follow missed-gate
recovery, and do not finalize. On a required hook or gate `FAIL`, run the
actionable retrospective, improve the canonical Tao Agent OS guidance, hook,
validator, or test, verify that improvement, and then resume the original task
at `first_failed_checkpoint`. A note or queued candidate alone is not recovery.
Use one repair cycle only. Stop when the same failure signature recurs after
repair, the repair is unsafe or ambiguous, canonical source ownership is
uncertain, or verification fails. See
`workflows/skills/retrospective-learning/SKILL.md` for the canonical decision
rules and `workflows/skills/scripted-agent-workflow/SKILL.md` for route
consumption.

When writing gate evidence, copy each gate name exactly from the active route
manifest, including spaces. Do not invent hyphenated aliases such as
`side-effect-audit` or `retrospective-check`; an extra ledger entry does not
satisfy the route's required gate.

Consume the route's `parallel_execution.delegation_policy` as an execution
contract, not a suggestion. When the runtime exposes subagents or parallel
workers and at least two meaningful slices have disjoint owned/forbidden scopes,
a stable contract, an integration owner, and focused verification, delegate
automatically without waiting for the user to request multi-agent work. Load
`workflows/skills/multi-agent-collaboration/SKILL.md` before making that decision.
If the work stays serial, record the concrete safety or capability reason;
missing explicit user wording is not a serial reason. A model-profile
`dispatch --execute` call is one bounded leaf worker and never substitutes for
the parent agent's split decision or eligible fanout.

Use the lightweight `analysis` route for read-only investigation. It has no
code-work, test, documentation, or review gate; keep it in the current session
and do not launch a Codex child unless the caller explicitly requires isolation.
It retains only the active runtime instruction as a required document.
The detailed review-only classifier precedence, intrinsic analysis read-only
mode, worker reservation claim-on-accept, and non-Git rules-root capsule
contracts are owned by
`workflows/skills/scripted-agent-workflow/references/current-guidance.md`;
callers must not duplicate or override those lifecycle decisions.
For implementation work, keep small tasks serial. Split only when at least two
independent scopes meet the delegation contract, then use two or three workers
at most and keep the parent responsible for one integration review and the
final verification.

Before a parent hands work to any runtime worker, run `<TAO_LAUNCHER> handoff`.
It lazily creates the provider-neutral, content-free execution capsule against
the current route, preflight, required docs, gate ledger, request fingerprint,
and project/rules state immediately before the worker boundary.
A Codex child launch revalidates that capsule immediately before execution, so
an inspect-only manifest cannot reuse a stale decision. A worker may reuse the
parent's route, preflight, required-doc brief, and gate context only when that
handoff reports a ready and valid capsule; it must not rerun route/preflight,
reread the parent's required docs, run VibeGuard, or perform a separate review.
Otherwise the worker follows the normal lifecycle on a newly reserved,
single-use-token worker evidence path. The parent remains the sole gate-ledger
owner. For Codex, keep dispatch inline unless isolation is explicitly required;
record model, reasoning, or sandbox mismatches as a decision input, not as an
automatic reason to nest a Codex process. The detailed cross-runtime contract is owned by
`docs/skills/agent-runtime-integration/SKILL.md`.

The fallback worker evidence root is
`<TARGET_REPO>/.tao/workers/<opaque>/preflight.json`. Handoff reservation,
worker start, execution-capsule identity checks, and finish validation must use
that same root.

After `start`, every lifecycle hook must reuse the exact resolved project root,
rules root, and preflight evidence path recorded by that start. If task setup
creates or switches to a different Git worktree, run a fresh `start` from that
worktree before project work; never combine a main-checkout preflight with
worktree review or finish hooks.

For local commit creation or commit preparation, use the lightweight `commit`
route, or `git_commit` when the runtime labels the task that way. Do not route
a clear commit request through `review`, `task`, or `triage` unless the request
is genuinely unclear. The commit route is intentionally small: read the commit
workflow entrypoints, run the lightweight review hook first, stop before
committing when review finds issues, and record only commit readiness before
creating the local commit.

Before editing, include the review hook's default structural budget in the
boundary plan for every new or substantially expanded development source file.
Keep each file at no more than 300 added lines, no more than four top-level
owners, and no more than one public/exported top-level owner unless a repo-owned
structure rule or an explicit review option sets a stricter limit. Treat a
language-level module-only declaration such as Kotlin/Swift `internal` or Rust
`pub(crate)` as non-private but not public/exported; an internal factory may
remain with its internal owner while the four-owner file budget still applies. Treat a
screen, page, or component with several independently nameable sections as a
split candidate during planning; do not wait for the final review hook to
discover that the file needs purpose-named extraction. Tests retain their
separate wider file-size budget. File-private helpers and preview-only support
that share the primary owner's caller and change reason do not count as
top-level owners. A cohesive Kotlin extension-function family on the same exact
receiver also counts as one owner cluster when the functions share one caller
contract and reason to change; different receivers and unrelated free functions
remain separate owners. Independently importable preview or production support
still counts separately.

Before invoking the review hook, count the task-owned changed paths in the
declared review scope. The default budget is 25 paths. A cohesive mechanical
migration that must update more direct callers may raise `--max-changed-paths`
to that observed count, but the review pathspec must still include only the
owned code/resource scope and the evidence must explain why the change cannot
be reviewed as independent behavioral slices. When the review reports a new
runtime package/folder boundary, write `--structure-review-evidence` as an
explicit five-part contract: `owner: ...; allowed imports: ...; forbidden
imports: ...; callers/tests: ...; verification: ...`. Do not substitute a
general structure summary for any of those named fields.

Treat the changed-path count as a pre-invocation hard check. Do not call the
review hook with its default limit after observing more than 25 owned paths.
For one cohesive caller migration, declare the narrow owned pathspec and pass
the exact observed count through `--max-changed-paths` on the first review
attempt; otherwise split the behavioral slices before review.

When the target is outside Git, the review hook must treat Git status, diff,
and structure source discovery as review-only after `git rev-parse` proves that
no repository owns the path. It must not continue with `git ls-files` commands
that cannot succeed. Require an explicit review pathspec, concrete code-review
evidence, focused verification, and an accepted non-Git VibeGuard reason instead.
A writing finish remains fail-closed unless a current successful review record
binds that explicit scope and its structurally unavailable diff check.

When reviewing subject-specific unit tests, apply the `Test Subject Ownership`
rule from `common/skills/code-structure-ownership/SKILL.md`: mirror the
production owner's logical package or folder and use the subject name, such as
`<Subject>Test`. A broad feature/category test location is reserved for a real
cross-owner contract or integration flow, not as a bucket for owner tests.

## Required Executable Evidence Gate

For multi-step tasks, use the executable wrappers when they are available. The
single start hook creates routing and preflight evidence with the current target
project and selected Tao Agent OS rule source before editing, reviewing,
committing, or reporting completion:

When executing wrapper commands from an agent runtime, replace
`<TAO_ROOT>` with the resolved absolute path first. Do not leave
`$HOME`, `${HOME}`, `~`, or a relative path in the executable command; those
forms can bypass narrow permission-prefix matching and cause repeated approval
prompts. Always register and request command permissions using the parameter-free
script path prefix (e.g., `python3 /absolute/path/to/script.py` or `node /absolute/path/to/script.mjs`)
instead of the full command with changing arguments. If a permission is saved
with arguments, any change to those arguments (e.g., different project paths or
options) will fail prefix matching and trigger repeated prompts.
For Codex `exec_command` escalations, set `prefix_rule` to only the executable
and resolved wrapper path, such as
`["/Users/USER/.tao/bin/tao-hook"]`; never
include `--project`, `--request`, `--gate-record`, `$(pwd)`, `$HOME`, or other runtime
arguments in the saved prefix. AGY (Antigravity) permission allowlists must follow the same
shape with only an absolute wrapper command plus a trailing argument wildcard.
Specifically, for any command, AGY requires registering three concurrent entries
to handle all parameter variations without prompts: `command(executable)`,
`command(executable:*)`, and `command(executable *)`. When implementing new
internal entrypoints under `scripts/`, ensure `<TAO_LAUNCHER> setup-agent-hooks` (via
`permission_entries.py`) automatically generates and updates these wildcard
combinations in settings.json and config.json. Claude managed user-level
hooks must use the stable launcher installed by `<TAO_LAUNCHER> setup-agent-hooks` at
`<TAO_LAUNCHER>`; setup refreshes
`~/.tao/tao-root` after moves or migrations so the Claude
hook command does not point at a stale checkout path.

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <command> --request "<USER_REQUEST>" [--platform <platform>] [--concern <concern>]
```

Keep `--output`, `--evidence`, and every custom evidence path inside
`<TARGET_REPO>/.tao/`. For temporary worktrees, use a project-local path
such as `<TARGET_REPO>/.tao/runs/<opaque-id>/preflight.json`; a sibling
temporary directory is outside the execution-capsule trust boundary and will
make the finish check fail even when every route gate passed. The start hook
rejects an explicit `--evidence` path outside the target project's
`.tao/` root so a run cannot begin with a capsule that review, finish, and
handoff must later reject.

`start --evidence <...>/preflight.json` writes the lifecycle evidence that
`gate`, `review`, and `finish` must all read. `start --output <...>/start.json`
writes only the start hook result wrapper. Never name an `--output` file
`preflight.json` or pass it to later lifecycle hooks. When a custom run
directory is used, pass both options with distinct filenames and reuse the
exact `--evidence` path through the complete lifecycle.

After start, read the route's `required_docs` in order before editing or
reviewing. This remains a direct agent responsibility: there is no separate
document-confirmation hook or standalone receipt command. Preflight records the
required-document snapshot, route fingerprint, and request fingerprint in its
parent evidence. The `source docs` finish gate validates that parent snapshot
alongside the direct-reading takeaway. The execution capsule is created only at
the handoff boundary and reuses the snapshot. The route manifest remains the
single source for required-document selection, and `reference_docs` remain
on-demand context. An empty `required_docs` manifest is a valid document-free
route state: record the no-source decision and continue without polling or
forcing the execution capsule back to preflight. Call `<TAO_LAUNCHER> agent-preflight` directly only as a lower-level
diagnostic or compatibility fallback when the start hook is unavailable, and do
not run both for the same startup.

A fresh start may replace a prior context snapshot whose request, route, or
required-document hashes are stale. This is normal stale-state refresh, not a
repair cycle. The agent must then read the current `required_docs`, and the new
snapshot becomes the finish boundary. Missing, malformed, or unavailable
required documents remain a hard failure and must not be replaced silently.

When the shared rules root may have changed during a long-running task, such as
after concurrent runtime maintenance or a repository sync, compare the current
required-document hashes with `execution_snapshot.required_docs` before calling
`review` or `finish`. On drift, do not run those hooks against the stale
snapshot. Run `start` again with the exact same request and evidence paths,
read every changed required document, and re-record any gate or review evidence
affected by the new guidance. This proactive refresh is not a repair cycle. If
a required hook has already reported the drift as `FAIL`, use the normal single
retrospective repair cycle; a fresh start alone must not erase that failure. If
the repair intentionally edits required documents, reread their current bytes
and record one new `documentation` `SUCCESS` entry per drifted document with
`decision=updated` and that exact route-relative required-doc path as `target`
before `repair-verify`; recording only the repair target does not rebind other
drifted required docs. The bound final-byte documentation receipt is the only
source-doc snapshot exception; the structural repair receipt does not replace
it.

For work-producing tasks, do not wait until final reporting to think about
documentation. Treat `documentation impact` as a pre-code/pre-edit checkpoint:
select the artifact class first, name the affected doc path or doc class, choose
`updated`, `created`, `unchanged`, or `not applicable`, and state why the
changed behavior, workflow policy, public contract, operator action, or
acceptance criteria does or does not require a doc update. Artifact classes can
include PRD/spec/ARD, ADR/RFC, module README, API contract, runbook, migration
note, release note, test plan, skill/platform/workflow card, repo
`AGENTS.md`, or another source-of-truth class that fits the work. Do not treat
PRD as the only documentation shape. `Not applicable` or `no docs` is valid
only when the evidence states a no-durable-doc reason such as answer-only,
purely local, mechanical, no public contract, no operator action, or no
acceptance criteria. `Unchanged` is never a self-granted default: it is valid
only when the evidence names the concrete existing doc path (for example
`app/README.md`, not just a doc class), proves that doc was actually
opened/inspected/read this task, and states why the already-read doc already
covers the change. A bare coverage assertion without the inspection proof, or
without a named doc path, fails the gate. The `documentation` gate must always
run and carry non-empty evidence — it cannot be skipped or left blank — and it
must prove the actual update, or the grounded unchanged decision. Skipping
documentation (a not-applicable/no-docs/skipped decision on the `documentation`
gate) is never self-approved by the agent, and a no-durable-doc reason alone is
not sufficient: when you believe docs should genuinely not be written, ask the
user "문서를 스킵할까요? / Should I skip the doc?", get explicit approval, and
record that approval in the evidence — otherwise write the doc. The full,
updatable gate contract and the exception process are the source of truth in
`workflows/skills/documentation-update/SKILL.md`; add new exceptions there rather
than self-judging, and load that card in Grill-Me or self-review to check the
current work before completion.

Before finish on every route, run the required lightweight `retrospective
check`: inspect the skills actually loaded and applied, then record
the exact fields `skills_checked`, `outcome`, and `observation`. `outcome` is
`no_reusable_gap`, `reusable_gap`, or `no_skill_used`; `observation` is
`not_needed`, `recorded`, or `deferred`. Pair `no_reusable_gap` and
`no_skill_used` with `not_needed`, and pair `reusable_gap` with `recorded` or
`deferred`. The check is required finish evidence; the follow-up skill-learning
side channel is non-blocking. If there is no reusable gap, do not create a
ceremonial observation record. If there is one, the optional
`skill-feedback` hook records only a
content-free observation for a skill actually used; it does not let the task
agent declare a patch candidate. Deterministic curation queues review only after
the same structured signal recurs in distinct opaque runs. A separate bounded
reviewer chooses `no_change` or `staged_patch`, and canonical guidance changes
only during later verified maintenance. Missing storage, tokens, reviewers, or
maintenance capacity never changes a successful finish result. Default review
to one capable agent and use additional reviewers only when impact and available
budget justify them. The detailed decision and privacy rules are owned by
`workflows/skills/retrospective-learning/SKILL.md`.

Before final report, commit, release, or handoff, record every remaining route
gate with explicit structured status, then run the read-only finish hook:

Treat a successful review as an intermediate checkpoint, not finish readiness:
record `retrospective check`, then every remaining closeout gate including the
user-facing `handoff`, and only then invoke the finish hook.

Treat the exact `Route: ... gates=[...]` list returned by the current `start`
run as the completion checklist. Never reuse a gate list from another run,
route, or example; immediately before `finish`, compare the current ledger with
that exact list and record every missing gate through `gate` or `gate-batch`.

`<TAO_LAUNCHER> handoff` refreshes the optional parent-to-worker execution
capsule only. It does not record the route's user-facing `handoff` gate. Record
that gate explicitly with `gate` or `gate-batch` and concrete final handoff
evidence before `finish`; do not invoke the worker handoff hook merely to satisfy
the route gate.

For structured `ambiguity check` evidence, record `blocker_status`,
`assumptions`, and `decision`; only `none` or `resolved` plus `proceed` may
pass. For structured `alignment brief` evidence, record
`shared_understanding`, `possible_differences`, `assumptions`, and
`checkpoint=user_visible_before_edits`. Existing finish-valid prose remains
compatible. The canonical decision rules live in
`workflows/skills/ambiguity-gate/SKILL.md`.

```text
<TAO_LAUNCHER> gate-batch --project <TARGET_REPO> --rules <TAO_ROOT> --gate-record '[{"gate":"orient","status":"SUCCESS","evidence":"<evidence>"},{"gate":"scope","status":"SUCCESS","evidence":"<evidence>"},{"gate":"act","status":"SUCCESS","evidence":"<evidence>"},{"gate":"verify","status":"SUCCESS","evidence":"<evidence>"},{"gate":"report","status":"SUCCESS","evidence":"<evidence>"}]'
<TAO_LAUNCHER> finish --project <TARGET_REPO> --rules <TAO_ROOT>
```

Structured gate fields must be passed in the record's `fields` object; putting
JSON-shaped text inside `evidence` does not populate them. For example:

```json
{"gate":"retrospective check","status":"SUCCESS","evidence":"closeout checked","fields":{"skills_checked":"graphify","outcome":"no_reusable_gap","observation":"not_needed"}}
```

`finish` must not create or override gate evidence. A later structured `FAIL`
for a gate invalidates an earlier `SUCCESS` until a later verified `SUCCESS` is
recorded through `gate` or `gate-batch`.

Call `<TAO_LAUNCHER> agent-finish-check` directly only as a lower-level diagnostic or
compatibility fallback when the finish hook is unavailable.

The wrappers write local JSON evidence under `<TARGET_REPO>/.tao/`.
The gate ledger is `<TARGET_REPO>/.tao/gate-evidence.json` for the
default `preflight.json`; custom preflight evidence files use
`<preflight-stem>-gate-evidence.json` so concurrent or delegated runs do not
overwrite one another.
That directory is local runtime evidence and should usually be gitignored.
Generated runtime caches and copied local skill caches also belong under the
ignored `<TARGET_REPO>/.tao/` boundary. Workflow document validation must
exclude that boundary, and review-time checks must not create legacy sibling
state directories that appear as source changes.
The wrappers may also read or write safe cross-agent lessons under
`~/.tao/`. That user-global store is for content-free lesson metadata
only: missed gate slugs, failure types, root-cause categories, next actions, and
promotion status. It must not contain prompts, responses, commands, file paths,
repo names, branch names, diffs, logs, source content, environment values,
secrets, or project-specific display names.

Missing preflight evidence, missing finish-check evidence, or missing gate
evidence is non-compliant even when the final code or documentation appears
correct. `<TAO_LAUNCHER> agent-preflight --request-classified` must include
`--classification-evidence`; otherwise request intake is treated as skipped.
Evidence alone is not sufficient: the flag is honored only when a ready and
valid parent execution capsule backs it, and the requestless form is rejected.
Otherwise the classifier runs on `--request` as for any other caller.
For required gates, a skip, not-applicable, unable-to-run, deferred, or
follow-up reason is not completion unless that gate explicitly allows that
outcome and the evidence names the allowed reason. Evidence that names an
unresolved, must-fix, should-fix, blocking, or deferred issue must fail the gate
instead of passing with a note; use missed-gate recovery and retrospective
learning to fix the process.
If route classification or stored request text says `grill_me: true`, legacy
`question_drill: true`, or explicitly asks for Grill-Me, `<TAO_LAUNCHER> agent-finish-check`
must receive Grill-Me protocol evidence such as
`grill-me if needed=</grilling session/output evidence>`. Legacy
`question drill if needed=<evidence>` or `ask blockers=<evidence>` is accepted
only when the evidence still names the Grill-Me protocol, skill, or
`/grilling` session and output.
Missing Grill-Me evidence is `🐱🔴 FAIL` and sets
`retrospective_required: true`.

If the wrappers are unavailable, the fallback is still strict: run the
workflow router, `git status --short --untracked-files=all`, VibeGuard before
work, VibeGuard again before finishing, and report each required gate with
concrete evidence. Do not claim wrapper evidence exists unless the wrapper was
actually run.

When `<TAO_LAUNCHER> agent-finish-check` marks `retrospective_required`, run the
canonical retrospective repair cycle before reporting completion. Improve and
verify the owning Tao Agent OS guidance, hook, validator, or test, apply safe
scoped fixes, then resume at `first_failed_checkpoint`. Stop instead of
continuing when the same failure recurs after repair, the repair is unsafe or
ambiguous, source ownership is uncertain, verification fails, or the single
repair cycle is exhausted.

Do not merge this failure path with successful-task skill feedback. Required
hook or gate failure remains blocking and must use the repair-and-resume
contract; skill feedback remains a non-blocking future-maintenance signal.

VibeGuard `Needs review` is not completion unless the agent explicitly reports
the review state and passes `--allow-vibeguard-review "<reason>"` to every
required lifecycle hook that evaluates that state, including both `review` and
`finish`. Route-generated review commands must advertise this optional argument.
`🐱🔴 FAIL`, command failure, or missing VibeGuard output remains a blocker.
Human-visible finish-check output must include only `🐱🟢 SUCCESS` and
`🐱🔴 FAIL`; the machine-readable JSON keeps the same stable `SUCCESS` and
`FAIL` values.

## Supporting Documents

Use `index.md` as the full document map. Do not duplicate the full index in
repo-local instructions. Start with these direct routes, then load only the
specific cards selected by `index.md`.

Release, versioning, platform, product-pattern, and other task-specific cards
are intentionally selected through `index.md` or `<TAO_LAUNCHER> workflow` instead
of being listed as baseline direct routes here.

```text
<TAO_ROOT>/index.md
<TAO_ROOT>/common/skills/stack-discovery/SKILL.md
<TAO_ROOT>/common/skills/llm-coding-discipline/SKILL.md
<TAO_ROOT>/common/skills/code-conventions/SKILL.md
<TAO_ROOT>/common/skills/tool-failure-recovery/SKILL.md
<TAO_ROOT>/common/skills/agent-interaction/SKILL.md
<TAO_ROOT>/common/skills/agent-editing-safety/SKILL.md
```

## Workflow Documents

```text
<TAO_ROOT>/workflows/skills/agent-task-lifecycle/SKILL.md
<TAO_ROOT>/workflows/skills/agent-handoff-continuation/SKILL.md
<TAO_ROOT>/workflows/skills/scripted-agent-workflow/SKILL.md
<TAO_ROOT>/workflows/skills/ambiguity-gate/SKILL.md
<TAO_ROOT>/workflows/skills/product-architecture-delivery/SKILL.md
<TAO_ROOT>/workflows/skills/development-cycle/SKILL.md
<TAO_ROOT>/workflows/skills/multi-agent-collaboration/SKILL.md
<TAO_ROOT>/workflows/skills/multi-perspective-review/SKILL.md
<TAO_ROOT>/workflows/skills/retrospective-learning/SKILL.md
<TAO_ROOT>/workflows/skills/planning-research/SKILL.md
<TAO_ROOT>/workflows/skills/documentation-update/SKILL.md
<TAO_ROOT>/workflows/skills/feature-implementation/SKILL.md
<TAO_ROOT>/workflows/skills/bugfix-debugging/SKILL.md
<TAO_ROOT>/workflows/skills/refactor-cleanup/SKILL.md
<TAO_ROOT>/workflows/skills/release-readiness/SKILL.md
<TAO_ROOT>/workflows/skills/review-and-commit/SKILL.md
```

## Operating Rule

Do not copy this whole library into a repo. Link only the documents relevant to
that repo. Keep repo-specific paths, commands, role matrices, API names, and
domain language in the repo-local instructions.

Keep reusable agent knowledge single-owned and provider-neutral. Runtime files
are thin adapters or pointers unless behavior is genuinely runtime-specific;
do not maintain parallel Codex, Claude, or Gemini/Antigravity/AGY copies of the
same operational rule or skill. Follow
`docs/skills/tao-skill-bundle-migration/references/source-of-truth-ownership.md`
for the canonical ownership and duplicate-audit rule.

When applying Tao Agent OS to another repo, reuse an existing usable local or
repo-pinned Tao Agent OS root by default. Do not download, clone, vendor, copy,
overwrite, or add a second root while one exists unless the user explicitly
approves after being told the found path.

When adding Tao Agent OS routing to a target repo, keep `AGENTS.md` as the
canonical instruction file when that runtime reads it. If existing
runtime-specific files such as `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, or
Antigravity CLI docs are present, update their Tao Agent OS pointer in the same
pass or point them back to `AGENTS.md`; do not create extra runtime-specific
files only for duplication.

User-level runtime bridges must be fail-closed. If a bridge cannot confirm the
current project root, the project-root instruction file for the active runtime,
or the required Tao Agent OS/VibeGuard evidence gates, the agent must stop
before routing, editing, testing, committing, or reporting completion and ask
for bridge repair. Generated or managed runtime bridges must also enforce
silent background behavior: do not mention setup helpers, hook commands,
permission allowlists, label commands, or background metering status in normal
conversation unless the user explicitly asks about that subsystem. Runtime
bridges must distinguish setup or diagnostic evidence from usage evidence: a
label command, permission prompt, hook configuration, hook process start, command
log, or mock payload is not proof that real token usage was recorded. When exact
runtime usage is unavailable, the compliant action is to skip usage event
creation or record content-free diagnostics according to the local product
contract, not to estimate or infer from private content. A bridge that only
apologizes after exposing those details is non-compliant; it must change the
next action path or stop.

`<TAO_LAUNCHER>` means the installed stable launcher, which lives
outside the checkout at `~/.tao/bin/tao-hook`. It is a
separate user-global directory, not a path under `<TAO_ROOT>`; the
`~/.tao/tao-root` pointer file is what links the two.
Before executing it, resolve the placeholder to that machine's absolute path.
Do not run it as `~/...`, `$HOME/...`, or `${HOME}/...`: setup installs one
resolved absolute permission entry per runtime, so a home-relative spelling is
not in the allowlist and produces an approval prompt. Committed documents keep
the placeholder rather than a personal absolute path, for the same reason
`<TAO_ROOT>` is never written out as `/Users/...`.

`<TAO_ROOT>` means the directory containing this shared library. In
committed or shared repo-local instructions, do not replace it with a personal
absolute path such as `/Users/.../tao-agent-os`. Use `${TAO_HOME}`
when each machine can set the variable, or a repo-relative pinned path such as
`.agents/tao-agent-os` when the root is committed or pinned with the target
repo. Personal absolute paths are acceptable only in uncommitted local runtime
bridges, one-shot prompts, or shell environment setup for a specific user.
`${KEYFLOW_AGENT_ROOT}` is accepted only as a legacy local alias when already
configured.

<!-- vibeguard:start version=1 -->
## VibeGuard

For every task that may change code, configuration, dependencies, data,
deployment, or credentials:

1. Run `vibeguard audit .` before editing.
2. If the audit reports stale VibeGuard guardrails, run `npx --yes @taehwandev/vibeguard@latest update .` once, then rerun `vibeguard audit .`. The default refresh interval is 7 days; do not update more often unless the user asks or the audit reports stale guardrails.
3. If `vibeguard` is unavailable, run `npx --yes @taehwandev/vibeguard@latest audit .` instead and use the same `npx --yes @taehwandev/vibeguard@latest ...` form for fixes.
4. If fixable findings exist, run `vibeguard audit . --fix` before implementing.
5. Never print detected secret values. Keep real secrets only in ignored runtime env files and keep env templates such as `.env.example` and `.env.sample` value-free.
6. Ask before deleting data, running migrations, deploying to production, increasing paid API/model usage, adding recurring infrastructure, or changing credentials. For every real external production deployment, and any deployment whose target is unknown, immediately before execution state the exact target and action and wait for fresh user confirmation. Never infer, reuse, or bypass approval from earlier wording such as "deploy it" or "handle it yourself".
7. Prefer cost-aware architecture. Before adding a paid service, database, queue, background worker, model call, analytics SDK, or cloud resource, explain why existing code or a simpler local/server-side design is insufficient.
8. For web apps, commonize repeated API/model/provider calls behind shared server-side helpers or endpoints. Prefer server-side caching, batching, and rate limits before adding new client-side call paths.
9. Before commit or push, verify `git remote -v`, repository visibility, and changed files. If the repository is public or visibility is unknown, stop before pushing secrets, env files, credentials, deployment, infrastructure, or paid-service changes.
10. After editing, run relevant tests and `vibeguard audit .` again before finishing.
11. Before creating a commit, run `vibeguard audit .`; before pushing or publishing, run `vibeguard audit . --strict`.
12. If execution evidence is available, run `vibeguard evidence .` before the final response and do not claim tests or audits ran unless they were observed.
13. Keep secrets server-side. Do not expose provider keys, database URLs, signing secrets, service-role keys, or webhook secrets to client code.
14. If the user pastes a secret in chat, treat it as exposed. Do not repeat it, put it in commands/logs/files/GitHub secrets/deployment settings/servers, or continue with deployment using that value. Guide the user to rotate it and enter a new value only through a local provider UI or secret-store prompt.
15. Keep VibeGuard scoped to guardrails. Do not clone, vendor, install, or link external agent-guidance bundles or rule libraries unless the user explicitly asks for that separate setup.
16. Preserve existing repo-local instructions. Only update the managed VibeGuard block between the `vibeguard:start` and `vibeguard:end` markers.

Refresh this managed block only when `vibeguard audit .` reports stale guardrails, or manually with `vibeguard update .` / `npx --yes @taehwandev/vibeguard@latest update .`.
<!-- vibeguard:end -->
