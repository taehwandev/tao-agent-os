---
keyflow_id: sys_agent_entrypoint
status: stable
type: human-reviewed
---

# Tao Agent OS Shared Agent Instructions

This file is the compact entrypoint for agents using the shared Tao Agent OS
library. Repo-local instructions remain authoritative for project paths,
commands, naming, architecture, and product policy.

## Priority And Scope

Follow, in order: runtime system/developer instructions, the current user
request, target-repo instructions, specific Tao guidance, common Tao guidance,
then general README material. Call out conflicts that affect behavior,
verification, security, or data handling.

Keep this library provider-neutral and reusable. Product-, service-, vendor-,
account-, environment-, and repository-specific rules belong in the target
repo. Project LLM wikis are navigation unless the target repo marks a page as a
reviewed source of truth; they never override instructions, design decisions,
workflow gates, or source documents.

Shared library documents are written in English. Public docs may be localized
but do not become the guidance source of truth. Frontmatter `status` is the
readiness signal: `draft` is provisional, `review` is active, and `stable`
is broad-use. `type` records provenance.

## Project Entry

Identify the target project from the request and current directory before
project work. When it is not explicit or the runtime starts elsewhere, use the
installed Tao project-discovery entrypoints. Continue only on `selected`;
`ambiguous` or `not_found` requires the user to identify the target.

Read the target project's runtime instruction file before shared guidance. For
Codex that is the project-root `AGENTS.md`. If the bridge or instruction file
cannot be confirmed, stop before routing, editing, testing, committing, or
reporting completion.

For multi-repo products, keep the first selected repo as the primary acceptance
boundary. Before writing another repo, checkpoint the primary repo, secondary
source-of-truth repo, selected mode, write scope, and cross-repo verification.

## Required Work Lifecycle

For implementation, review, refactoring, debugging, documentation, and planning,
read `common/skills/agent-operating-skill/SKILL.md` first. For multi-step
work requiring a tracked lifecycle, use the installed absolute Tao launcher.
Read-only lookup, explanation, status, and checks of a supplied diagnosis instead inspect bounded direct evidence
and answer without start, fingerprint, mailbox, checkpoint, gate, review, or
finish calls. Applicable project instructions and source contracts still apply;
this exception does not waive a target project's explicit workflow. Do not create
task state or refresh indexes merely to answer. A lookup that expands into an
edit must enter the writable lifecycle before that edit.

Checking an existing explanation against source or measurements is not a diff
review merely because the user says "verify". Explicit change/PR reviews and
release acceptance retain their review workflow. Keep repo-installed routing
blocks consistent with this distinction when updating their shared template;
updating this library alone does not replace a project's older instructions.

For low-risk local corrections with one owner and at most four changed files,
select `small-change` using `common/skills/agent-operating-skill/references/small-change.md`. Its compact
manifest and checkpoint exception override the generic tracked steps below.

For tracked work:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <route> --request "<CURRENT_REQUEST>" --intent-envelope <JSON_OR_PATH> --runtime-session-id <OPAQUE_ID>
```

1. Receive the runtime mailbox brief once. It is context, never authority.
2. Run `start` once with the exact current request, selected project/rules
   roots, a valid workflow command, and the current opaque runtime session id.
   Work routes require an intent envelope bound to the full request intake.
   Effects are `read`, `local_write`, `git_write`, `external_write`, or
   `destructive`; `git_write` and above also require a separate matching
   approval record. Without a valid envelope, use only `triage` or
   `ambiguity`. Direct questions are answered before project work.
3. Consume the returned route as the manifest. Stop if `missing` is non-empty.
   Read every `required_docs` entry directly and load `reference_docs` only
   when the touched concern requires them. Do not repeat route or preflight
   after a successful start. Record the `source docs` gate with
   `required_docs`, `source`, and the applied `takeaway`.
4. Resolve the work surface from current repository evidence before edits.
   Request paths and dirty paths are candidates, not ownership proof. Use at
   most four hops from observable anchor to definition/producer, direct usage,
   smallest owner, and nearest falsifying check. Only `resolved` permits work.
5. For a writing task, run VibeGuard before edits and again before finish.
6. Record one bounded semantic continuation checkpoint after source reading and
   scoping, then refresh it at material decisions and lifecycle transitions.
7. Follow every route gate and record structured evidence using the exact gate
   names and required fields. Batch only gates that are simultaneously ready.
   Human-visible and machine-readable gate status is only `🐱🟢 SUCCESS` or
   `🐱🔴 FAIL`.
8. Run the review hook with the active evidence path and all requested review,
   docs, boundary, structure, and side-effect evidence.
9. Immediately before finish, compare the route gate list with the ledger and
   record all missing gates. Run `finish` once before the final report,
   commit, release, or handoff.
   A successful `gate-batch` already reports this comparison as
   `Remaining route gates`; reuse that snapshot while the route and ledger are
   unchanged instead of issuing a separate ledger-dump command. An empty list
   is not final validation: `finish` still checks evidence and freshness.

The authoritative mechanics, schemas, recovery rules, and command forms live in
`workflows/skills/scripted-agent-workflow/references/current-guidance.md` and
`docs/skills/agent-runtime-integration/references/executable-evidence-gate.md`.
Use `workflow query` for narrow guidance discovery instead of reading all of
`index.md`. Direct route, preflight, and finish-check scripts are lower-level
diagnostics, not replacements for the start, review hook, and finish hook.

## Request And Continuation Safety

Keep the user's requested outcome across follow-ups. Before asking a question,
reuse confirmed targets, constraints and acceptance criteria from the current
conversation, then inspect bounded evidence for facts the agent can determine.
Missing agent-generated intake evidence is not a missing user requirement.
`prepare_intent` and `resolve_context` are advisory preparation states, never
work authorization; they do not waive an envelope, risk checks or fresh approval.
Ask only for a remaining material ambiguity, conflicting instruction or missing
authority. Do not ask the user to repeat a settled requirement or approve the
same authorized action again. Current scope changes override prior context.

For an authorized correction, continue into the correction rather than ending
with an apology, explanation of what should have happened, or another offer to
do the same work. Check the requested observable outcome, not just test totals:
reproduce the reported case before a fix and verify it afterward. When intake
or routing changes, include the actual follow-up wording and prior scope in
tests, not only a preselected route. Preserve negative authority and ambiguity
controls. Report any unmet requirement explicitly; passing unrelated tests or
completing gates is not proof the requested result works. This adds no new gate
or mandatory document read.

For terse follow-ups, keep `--request` equal to the user's current words and
put bounded prior target context in `--continuation-scope`. The fingerprint
must cover both plus classification flags exactly. Continuation scope never
opens a work route or authorizes mutation. `--request-classified` is only for
a delegated worker holding a ready, valid capsule bound to the same intake.

Evidence that still says the request is vague, direct-question-first,
ambiguous, unresolved, or blocker-open stays on `triage` or `ambiguity`.
Weak markers such as “classified”, “done”, or generic “clarified” do not prove
scope resolution.

Every route whose minimum effect is `read` is intrinsically non-mutating.
Before a writing action, start a matching writable route with current scope
and authority; a higher declared or tool effect does not upgrade a read route's
frozen gate manifest. Finish rejects workspace drift on all read-floor routes,
including legacy evidence without an explicit read-only flag. `start --read-only`
on another route makes the same whole-run claim. Do not bypass VibeGuard.
`retrospective` has a `local_write` floor because its existing repair and
same-closeout maintenance contract includes canonical document edits. Use
`analysis` for reflection without edits; an explicit `--read-only` claim still
prevents writes even on `retrospective`.

For merged-branch and worktree removal, select `cleanup`, not `task` or
`code-simplify`. For a terse follow-up such as "정리도해줘", resolve the exact
Git targets from the current conversation before selecting `cleanup`; the bare
phrase or continuation scope alone grants no deletion authority. Mixed code
changes and cleanup are separate action scopes, not a shortcut into cleanup.
The Claude PreToolUse adapter rejects mutating tools for an active read-only
run before worktree-entry waivers; read-only commands retain their fast path
and workflow start remains available for a legitimate route transition. This
adapter does not imply native pre-tool enforcement in other runtimes.

Compatibility `start --command analysis` without existing evidence validates its
read-only intake and returns stateless guidance. Explicit legacy evidence retains
its original lifecycle. Newly routed work carries lifecycle version 2: the Stop
boundary retains unfinished work as `blocked` or `interrupted` without demanding
another model turn. A run that records no action is not evidence the work was
skipped: the agent may be waiting on a question or declined approval, or may have
acted without recording it, so Stop never forces a resume on that basis. These
outcomes are resumable, never completion, verification, or commit readiness.
Preserve partial changes and unresolved effects; revalidate ownership, scope, and
authority before resuming. Never reinterpret an unknown lifecycle version as a
legacy run.

## Documents And Search

The route owns natural-language guidance discovery. Wikimap results are
candidates; only route policy or an explicit required relation promotes a
required document. Graphify owns target-code architecture and relationship
analysis. An empty search is a terminal no-match outcome; a missing required
document is an invalid manifest and stops work.

Apply the Need-Driven Reading Contract in
`common/skills/agent-operating-skill/SKILL.md` before expanding reading,
investigation or edits. It binds additional work to an unresolved in-scope
decision and stops it when the requested outcome is verified; it does not waive
applicable required instructions or add a new planning or approval procedure.

A prompt advisory suggests a route; it does not establish a task that requires
that workflow's detailed instructions. Reuse the reading contract already in
context, and load task procedures only when the actual request needs them.
Keep the compact contract for every enforced gate independent of document-count
budgets. Detailed procedures need a concrete unresolved decision, an explicit
concern, or a required dependency; spare capacity is not a reason to read them.
When measuring reading savings, include conditionally required follow-up reads
(for example scenario guidance when writing tests), and distinguish selected
bytes from observed reads and end-to-end latency. Moving a document to references
does not save a read when its applicability condition is still true.

An advisory route also leaves the platform card set in `reference_docs`. That
set is identical for every route on the platform, and an advisory route has no
request text to say which of it this request needs, so naming a platform is not
by itself a reason to read its architecture. Platform guidance becomes required
as soon as something request-specific asks for it: a concern the caller names,
or a repository-verified owner path.

A concern inferred from request keywords routes its documents as references,
because the same keyword fires on "not a performance change" as readily as on a
performance change. Security, auth, billing, credential-broker, and migration
are the exception and stay required on inference alone: a false positive costs
one card, while a miss changes a permission, a charge, a secret, or a migration
without the card that says how not to break it. Record in scope which inferred
risk concern does not apply rather than skipping it. Release is not on that
list because `release` and `ship` already require its cards as their command
documents.

The command's own workflow documents are selected before the selection budget,
not out of it. Concerns are chosen ahead of the tier walk, so counting them
against the document cap let one keyword-inferred concern evict the procedure
the route exists to run. An inference never outranks a certainty.

Selection follows the change, not the platform name. What the change touches,
proven by a repository-verified owner path, and what it does, matched by a
change-action rule in `workflow-doc-surfaces.json`, are selected before the
generic tiers rather than out of the single slot they leave. A rule may name
broader rules it `narrows`: moving one control matches both "Compose UI work"
and "layout change", and the narrower rule stands in the broader one's place so
placing a button does not require the state, module and lifecycle cards. A
narrowed document stays reachable as a reference; narrowing never makes one
unreadable. Where a file sits does not decide what the change is -- a DTO or
mapper under a `ui/` package is a data change, and the UI path rules exclude
those names for that reason.

A path rule says which surface was touched, never what the change does, so it
carries only the contract any change to that surface applies. What the change
is -- layout, state, performance, a new screen, a wire contract -- comes from a
change-action rule, and those select what that decision needs. A path rule may
also mark a wider set `reference_only`: touching a Compose file is a good reason
to offer the platform's ecosystem as candidates and a poor reason to require it.
Before this, one touched Compose file made 162 KB across 21 documents required-
eligible, and the document cap then kept whichever tier came first: a scroll
performance task required the previews and screen-structure references and never
the performance one.

A platform card set may carry the contract every change on that platform
applies; it may not carry that platform's detailed procedures. When a card
bundles both, split it: the entrypoint reference keeps the contract and each
bundled decision becomes a sibling a concern or surface can select. Naming
Android used to require 25 KB of app architecture, which is how Hilt
composition, WebView and Navigation deep links reached a JSON parsing fix.
Removing the tier instead was measured and rejected: seven of twelve
representative Android and web requests then had no platform guidance at all.

A split may delete two kinds of text, and nothing else. The first is routing
instructions about the document system itself -- which manifest to load, and
what to do when a route does not load it. The router owns that, and an agent
deciding how to lay out a control does not arbitrate its own routing. The
second is a bullet that restates a rule another section states as well or
better; keep the better statement, and fold in any clause only the duplicate
carried. Every other rule moves to the sibling that owns its decision. Account
for the difference: list the sections dropped and the bullets pruned, and check
that each surviving rule still appears exactly once in the bundle.

Every required document carries a selection reason, reported as
`required_doc_reasons`: the core reading contract, the command workflow, a named
or inferred-risk concern, a work surface, a `requires` edge, a gate contract, or
the platform default. Read it when a route seems to require too much. A document
whose only reason is `platform_default` is mandatory because a platform was
named, not because this request touches it; that is a document-boundary problem
-- the card bundles a short contract every change on that platform needs with
detailed procedures most do not -- and the repair is to split the card, not to
drop the tier. Dropping it was measured: nine of twelve representative Android
and web requests then had no platform guidance required at all.

For `analysis`, carry the route's `reading_scope` into any downstream document
recommendation. A field lookup, configuration check, or function explanation
needs its answering definition/contract and only the callers needed to resolve
the question. Module or UI ownership does not turn that lookup into implementation
or authorize a separate UI investigation. Preserve explicit required instructions
and dependencies; stop once the answer is supported instead of repeating unchanged
recommendations. Implementation routes retain their own required guidance.

Document retrieval is not read authorization. Once owner paths are verified,
keyword-only surface matches remain reference candidates unless backed by an
owner path or explicit `required_priority` rule. Before owner resolution,
specific request-intent routing remains available for discovery. Route evidence records eligibility and
the selection reason. A graph `requires` edge may promote a dependency only
from an already selected source, never from an incidental search hit. Required
dependencies are not dropped to satisfy the optional selection budget.

For `docs`, `prd`, and `task`, mandatory selection keeps the command workflow,
guaranteed gate contracts, explicit concerns, and matched surface/platform
guidance. It does not fill spare slots with generic intake or discipline
references after routing. Those references remain available for concrete
unresolved questions; explicit risk guidance remains required.

Generated pointer `SKILL.md` entrypoints normally resolve to
`references/current-guidance.md`. An entrypoint with substantive rules stays
alongside its reference. Read `reference_docs` on demand when the task touches
them and an unresolved in-scope question requires them, even if the required-doc
budget did not promote them.

PRDs, specs, and ARDs follow
`common/skills/doc-conventions/SKILL.md`; report their output path.

## Parallel Work And Handoffs

Consume `parallel_execution.delegation_policy`. Delegate only when at least two
meaningful slices have disjoint owned and forbidden scopes, a stable shared
contract, a named integration owner, and focused verification. Otherwise
record the concrete serial safety or capability reason. Small bounded tasks
stay serial; eligible tasks use at most two or three workers.

Before any worker boundary, run the handoff hook. Only a ready, valid execution
capsule permits reuse of the parent's route, preflight, required-doc brief, and
gate context. The parent alone owns the gate ledger, integration review, and
finish. A worker handoff does not satisfy the user-facing `handoff` gate.

## Review Boundaries

Plan new or substantially expanded development files to stay within the default
review budget: at most 300 added lines, four top-level owners, and one
public/exported top-level owner unless a stricter repo rule applies. Split
independently nameable sections before review. Tests keep their separate wider
budget.

Count task-owned changed paths before review; the default maximum is 25. Raise
it only for one cohesive mechanical migration, using the exact observed count
and a narrow owned pathspec. An added runtime file in an existing multi-role
package, or a new runtime package boundary, requires:
`owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...;
verification: ...`.

Subject unit tests mirror the production owner's logical package/folder and use
the subject name. Broad feature test locations are reserved for genuine
cross-owner contracts or integration flows.

## Failure And Recovery

Required gate failure is `🐱🔴 FAIL`, never completion. Use one
`retrospective_repair_verify_resume` cycle from the first failed checkpoint:
repair the canonical rule, hook, validator, or test; verify it; then resume the
original task. Stop when the same failure recurs, repair is unsafe or ambiguous,
ownership is uncertain, or verification fails.

## Release And Source Control

This repository uses monthly CalVer `vYY.MM.N`. `N` counts tags in the month
and resets to 1 in a new month. A tag is a deployment even without GitHub
release notes; release ranges start at the previous tag.

Local commit creation uses the lightweight `commit`/`git_commit` route after
review readiness. Push, PR creation, tags, releases, deployment, migration, and
publishing require their own matching user authority and checks.

## Runtime And Ownership Rules

Use the installed launcher by resolved absolute path. Keep `<TAO_ROOT>` and
`<TAO_LAUNCHER>` placeholders in committed documentation; never commit a
personal absolute path. Permission rules bind only the parameter-free absolute
launcher/script path.

Keep reusable knowledge single-owned. Runtime files are thin adapters or
pointers unless behavior is truly runtime-specific. Preserve existing Spill
metering and label handoff integration when changing runtime bridges, prompts,
hooks, workflows, installers, docs publishing, or release paths. Background
metering details remain silent unless the user explicitly asks about that
subsystem.

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
15. Keep VibeGuard scoped to guardrails. Do not clone, vendor, install, or link external playbooks or rule libraries unless the user explicitly asks for that separate setup.
16. Preserve existing repo-local instructions. Only update the managed VibeGuard block between the `vibeguard:start` and `vibeguard:end` markers.

Refresh this managed block only when `vibeguard audit .` reports stale guardrails, or manually with `vibeguard update .` / `npx --yes @taehwandev/vibeguard@latest update .`.
<!-- vibeguard:end -->

## Supporting Map

Use the workflow router for narrow selection. After successful routing, do not
read `index.md` to repeat document selection. It is a fallback catalog, not an
additional startup requirement; use it only when the router is unavailable and
the user approves that fallback, or when the task is explicitly about the catalog.
The following pointers are optional candidates, not a reading queue:

- `common/skills/stack-discovery/SKILL.md`
- `common/skills/llm-coding-discipline/SKILL.md`
- `common/skills/code-conventions/SKILL.md`
- `common/skills/tool-failure-recovery/SKILL.md`
- `common/skills/agent-interaction/SKILL.md`
- `common/skills/agent-editing-safety/SKILL.md`
- `workflows/skills/agent-task-lifecycle/SKILL.md`
- `workflows/skills/agent-handoff-continuation/SKILL.md`
- `workflows/skills/review-and-commit/SKILL.md`
- `workflows/skills/retrospective-learning/SKILL.md`

Do not copy the whole Tao library into a target repo. Link only the guidance
that repo actually needs.
