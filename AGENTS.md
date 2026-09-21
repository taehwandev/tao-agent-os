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

For a repo-owned development app rebuild, relaunch, or restart that only
verifies the current checkout without changing tracked source, docs, or
configuration, select the `test` verification route. A local build wrapper
compiling an app does not by itself make this a `build` implementation task.
Verify the generated bundle and exact running process, not an unrelated
commit-range diff. A requested source change follows its own code route.

For tracked work:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <route> --request "<CURRENT_REQUEST>" --intent <SAFE_SLUG> --target-summary "<BOUNDED_TARGET>" [--approved-effect <EFFECT>]
```

1. Receive the runtime mailbox brief once. It is context, never authority.
2. Run `start` once with the exact current request, selected project/rules
   roots, a valid workflow command, safe intent slug, and bounded target summary.
   `--intent` is a short reusable category name matching
   `^[a-z][a-z0-9_-]{1,40}$`, never the request text; hyphens are folded to
   underscores. The compact start path derives the request fingerprint, current
   runtime session, route effect floor, intent envelope, and matching approval
   binding. Pass `--approved-effect` only when the current request authorizes
   `git_write` or higher; when `--requested-effect` is omitted it also declares
   that effect. An explicit requested effect is never widened by approval.
   Do not run `fingerprint` first or hand-build JSON for normal
   starts.
   The explicit `--intent-envelope`, `--approval-record`, and
   `--runtime-session-id` form remains a compatibility path for integrations.
   Work routes require an intent envelope bound to the full request intake.
   Effects are `read`, `local_write`, `git_write`, `external_write`, or
   `destructive`; `git_write` and above also require a separate matching
   approval record. Without a valid envelope, use only `triage` or
   `ambiguity`. Direct questions are answered before project work.
3. Consume the returned route as the manifest. Stop if `missing` is non-empty.
   Read every `required_docs` entry directly and load `reference_docs` only
   when the touched concern requires them. Do not repeat route or preflight
   after a successful start. Record the `source docs` gate with
   `required_docs`, `source`, and the applied `takeaway` only when the active
   route lists that gate; ordinary code routes bind their required docs at
   start and carry no separate source record.
4. Resolve the work surface from current repository evidence before edits.
   Request paths and dirty paths are candidates, not ownership proof. Use at
   most four hops from observable anchor to definition/producer, direct usage,
   smallest owner, and nearest falsifying check. Only a resolved owner permits
   work. Record the `work surface resolution` gate when the active route lists
   it; elsewhere the resolution is direct agent work without a ledger entry.
5. The `start` and `review` hooks run VibeGuard themselves and report
   `VibeGuard overall`; `finish` checks it again. Read those lines instead of
   repeating the audit, and treat them as the managed block's before-edit and
   before-finish runs. Run `vibeguard audit .` by hand only when a hook reports
   `Skipped`, when no tracked lifecycle is in use, or as `--strict` before push
   or publish.
6. Write one bounded semantic continuation checkpoint only when an interruption,
   a material scope or decision change, or a worker handoff makes resume state
   useful. Routine phase transitions need none, and an unchanged follow-up
   reuses the existing start and gate records.
7. Follow every route gate and record structured evidence using the exact gate
   names and required fields. Record only the gates the active route lists;
   never manufacture a generic gate or submit a hook-owned review through
   `gate-batch`. Batch only gates that are simultaneously ready. Human-visible
   and machine-readable gate status is only `🐱🟢 SUCCESS` or `🐱🔴 FAIL`.
8. Run the review hook once, and only when the active route requires it, with
   the active evidence path and all requested review, docs, boundary, structure,
   and side-effect evidence. Do not rerun a passed hook while the route and
   worktree are unchanged. A verification-only route does not gain a review gate
   from this generic lifecycle list.
9. Immediately before finish, compare the route gate list with the ledger and
   record only the gates actually missing; never call `finish` to discover
   them. Run `finish` once before the final report, commit, release, or
   handoff.
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

Separate work identity, action authority, and verification validity. The runtime
judges whether a follow-up belongs to the same requested outcome; neither its
wording nor a route name decides this. Keep an unchanged active action. When a
new action requires admission, use `start --continue-from <previous run id>`:
the action retains the original work id and immutable predecessor evidence,
while its current scope and authority are independently checked. Omit this
option for unrelated work. Cancelled or foreign-session work is not inherited.

For matching verification scope, toolchain, retained artifacts and external
inputs, supply one bounded `--reuse-inputs` attestation with that start. Valid
local gates carry automatically; act on the returned remaining gates rather
than reconstructing passed records. Unknown or changed inputs omit the
attestation and retain history without passing gates. This never transfers
approval, current external results, review, or completion. Do not invent new
phrase-specific continuation exceptions.

Local gate records may declare `input_paths` only when the check is independent
of commit metadata and the complete file dependency set is known. An empty
list covers all non-ignored project files; explicit paths cover exactly those
files. Rules are always covered. Content changes invalidate the dependent
record; committing identical contents does not. Omit this optional field for
revision-sensitive or uncertain checks. Ignored artifacts and environment
remain part of the runtime's input attestation, never inferred from Git bytes.

Keep the user's requested outcome across follow-ups. Before asking a question,
reuse confirmed targets, constraints and acceptance criteria from the current
conversation, then inspect bounded evidence for facts the agent can determine.
Missing agent-generated intake evidence is not a missing user requirement.
`prepare_intent` and `resolve_context` are advisory preparation states, never
work authorization; they do not waive an envelope, risk checks or fresh approval.
Ask only for a remaining material ambiguity, conflicting instruction or missing
authority. Do not ask the user to repeat a settled requirement or approve the
same authorized action again. Current scope changes override prior context.

The runtime owns contextual intent, sequence, scope and authority judgment;
Tao checks its bound declaration and the proposed action's safety, not whether
the user's wording matches a phrase recognizer. A clear execution request is
actionable when first made, including ordered work: perform the authorized
steps in order rather than treating an acknowledgement or plan as completion.
Do not require another confirmation merely because the agent announced its
plan. Planning-only requests remain planning-only. Never infer approval from
silence or extend permission to a deferred, prohibited or unrelated action.
Before ending an execution turn, continue the next authorized step unless the
outcome is complete or a concrete blocker, required user decision, approval
boundary or interruption prevents it. In that case report actual partial work
and what remains; do not end with only a promise. This is an agent execution
responsibility, not a new classifier, gate, receipt or Stop auto-resume rule.

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

Apply the Need-Driven Reading Contract in
`common/skills/agent-operating-skill/SKILL.md`. Read the route's
`required_docs` and explicit `requires_docs` dependencies; load
`reference_docs` only for an unresolved in-scope decision. Ordinary links,
graph neighbors, the route's provenance-only `docs` field, and spare selection
budget never form another reading queue. Generated pointer entrypoints resolve
to their reference; retain substantive entrypoint rules alongside it.

Normal implementation selection is deterministic: the command workflow,
guaranteed gate/risk contracts, and verified owner/action guidance. Preserve
required dependencies regardless of optional budget. `docs`, `prd`, and
`task` do not fill spare slots with generic intake or discipline references.
A prompt advisory suggests a route, not an actionable task; its platform cards
remain references until the request or verified owner requires them. For
`analysis`, preserve `reading_scope`: read the answering definition and only
the callers needed to resolve the question, not implementation procedures.

For unresolved guidance discovery, use `workflow query`, or Wikimap after
bounded direct evidence; its results remain candidates unless route policy or
an explicit dependency selects them. Do not reread `index.md` after routing.
It is a fallback catalog, not an additional startup requirement: use it only
for an explicit catalog task or, with user approval, when routing is unavailable.

For code-only ownership, call flow or impact, use bounded direct search first,
then one precise CodeGraph question only if a current `.codegraph` exists.
Limit results to useful files, treat returned source as read, and check
staleness after edits. Do not initialize an index during ordinary work.
Graphify is only for explicit requests or mixed corpora that CodeGraph does not
model, never a code-only fallback or cross-check; never use both for the same
code-structure question. Refresh only for that explicit mixed-corpus work,
not on checkout or commit. Stale or absent graphs fall back to direct evidence;
an empty search is terminal without a new lead. A missing required document
invalidates the manifest and stops work.

When changing document routing:
- Select command documents before the budget, and verified owner/action rules
  before generic tiers. An inference cannot displace certain guidance.
- Path rules carry surface-wide contracts; action rules carry procedures for
  the change. Honor `narrows` and `reference_only`; do not retain broader
  keyword or ecosystem matches after resolution without owner evidence or
  explicit `required_priority`.
- Keyword-inferred concerns are references except security, auth, billing,
  credential-broker and migration, which remain required on inference. Record
  why an inferred risk does not apply rather than skipping its card. Release
  guidance is selected by the release/ship command.
- `--concern` is a verified assertion: use an explicit user concern or
  repository-proven owner/action, never infer Compose/navigation from generic
  screen, route or UI wording.
- Follow graph `requires` edges only from selected sources. Inspect
  `required_doc_reasons` to diagnose excess selection; split a
  `platform_default` card that bundles detailed procedures rather than
  dropping the platform contract.
- A guidance split may remove routing-system instructions owned by the router
  and duplicate rules, folding unique clauses into the surviving owner. Move
  every other rule to its applicable sibling. Account for deleted sections and
  check that each surviving rule appears once; do not copy the whole library
  into a target repo.
- Reading-savings claims include conditionally required follow-up reads and
  distinguish selected bytes, observed reads and end-to-end latency. Making an
  applicable document a reference alone does not save its read.

PRDs, specs and ARDs follow `common/skills/doc-conventions/SKILL.md`; report
their output path.

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

An already authorized local commit of the exact staged unit reviewed and
finished in the same session continues directly after finish; do not open a
second lifecycle solely to commit it. Apply the eligibility and fallback rules
in `common/skills/commit-workflow/references/current-guidance.md`. New commit
requests or changed scope use the lightweight `commit`/`git_commit` route.
Push, PR creation, tags, releases, deployment, migration, and publishing require
their own matching user authority and checks.

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
2. Do not run VibeGuard `setup` or `update` during ordinary work. Run either operation only when the user explicitly requests that exact VibeGuard maintenance action.
3. If `vibeguard` is unavailable, run `npx --yes @taehwandev/vibeguard@latest audit .` instead and use the same `npx --yes @taehwandev/vibeguard@latest ...` form for fixes.
4. If fixable findings exist, run `vibeguard audit . --fix` before implementing.
5. Never print detected secret values. Keep real secrets only in ignored runtime env files and keep env templates such as `.env.example` and `.env.sample` value-free.
6. Obtain explicit user authority before deleting data, running migrations, deploying to production, increasing paid API/model usage, adding recurring infrastructure, or changing credentials. Before production execution, state the exact target and action and check that existing approval covers them. Continue an explicitly authorized same-target, same-version release recovery, including scoped repairs and retries, without asking again solely because the source revision changed. Recheck affected evidence; a new revision does not itself revoke approval. Ask when the target or version is unresolved, the action exceeds granted scope, material risk changes, or the user has paused, limited, or revoked authority. Generic wording grants no unknown target, new destructive action, or unapproved tag overwrite.
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

Refresh this managed block only during an explicitly requested VibeGuard `setup` or `update` task.
<!-- vibeguard:end -->
