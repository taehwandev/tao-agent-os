---
keyflow_id: sys_documentation_update_workflow
status: stable
type: human-reviewed-needed
---

# Documentation Update Workflow

Use when creating, reviewing, or restructuring docs, guides, specs, READMEs, agent instructions, release notes, or knowledge-base pages.

## Read

- `workflows/skills/agent-task-lifecycle/SKILL.md`
- `common/skills/code-conventions/SKILL.md` for naming and clarity
- `common/skills/llm-wiki-documentation/SKILL.md` for wiki, knowledge-base, runbook, onboarding, durable architecture, or operational docs
- `common/skills/agent-skill-card-anatomy/SKILL.md` when creating or materially updating an
  Tao Agent OS guidance card
- `common/skills/project-naming/SKILL.md` when names, slugs, or product identifiers appear
- `common/skills/verification-policy/SKILL.md` when links, examples, or commands can be checked
- `common/skills/human-authored-writing/SKILL.md` when the task changes prose voice, tone, or AI-writing signals, or repairs a reader-comprehension failure without changing facts
- task-specific architecture, product-pattern, security, or release cards when the docs describe those surfaces

## Steps

 1. Identify the document audience, purpose, source of truth, and expected action.
 2. Check existing docs for overlap before adding a new page or section.
 3. For feature, product, workflow-policy, architecture, module, API, data,
    release, operational, or public-contract changes, search and open the
    relevant source docs before deciding what to write. Source docs may be PRD,
    spec, ARD, issue, design note, task doc, ADR/RFC, module README, API
    contract, runbook, migration note, release note, test plan, skill/platform
    card, workflow card, or agent instruction. If no source exists, record that
    absence and decide which smallest artifact must be created before code.
 4. Apply the commonization test before changing shared docs: the guidance must remain correct after removing one repo, product, service, vendor, customer, team, environment, or account context.
 5. Do not set the shared baseline from a specific service's workflow, API shape, naming scheme, role model, permission policy, deployment model, provider setup, or product policy.
 6. Keep repo-specific commands, paths, role matrices, and domain terms in repo-local docs.
 7. Write shared agent library guidance in English. Localize only public-facing site copy or repo-local docs that intentionally target another locale.
 8. Link to shared cards instead of copying full guidance.
 9. For prose cleanup, preserve the original factual commitments and report when a style edit would change meaning, genre, or voice ownership.
10. Verify examples, links, file paths, commands, and metadata where practical.
11. Report what changed, what was verified, and any stale or missing source material.

## Documentation Impact Checkpoint

Before edits on any work-producing task, select the affected artifact class
below and an intended Documentation Decision. This includes code, install/repair,
tests, hooks and generated-output work, not only prose changes.

| Work Type | Artifact Candidates |
| --- | --- |
| New product behavior, broad feature, or unclear acceptance criteria | PRD, feature spec, acceptance criteria note |
| Architecture, ownership, dependency, or data-flow decision | ARD, ADR, RFC, architecture note |
| New module, package, public component, or reusable boundary | module/package README, component API note, platform card |
| API route, event, DTO, schema, auth, or integration contract | API contract, schema note, integration spec, product-pattern card |
| Persistence, migration, background job, release, deployment, or operator action | migration note, runbook, release note, rollback note |
| Test strategy, scenario coverage, QA workflow, or verification harness | test plan, QA checklist, verification runbook |
| Shared agent behavior, workflow rule, review rule, or platform guidance | Tao Agent OS common card, workflow card, skill card, platform card, repo `AGENTS.md` |
| Local command, repo path, product policy, domain term, or service-specific rule | repo-local `AGENTS.md`, `README.md`, wiki, runbook, or task doc |
| Generated docs, wiki, search index, graph, or public build artifact | generated-files policy, source-doc update, manifest, or publishing note recording source revision, generator, publish boundary and private-data review |

Record the class, affected doc path/class, intended decision and reason. A code
or test-only diff does not excuse a changed contract, acceptance criterion,
definition of done or workflow policy from this check. If durable meaning has
no source, create the smallest useful artifact. Revisit the decision when
implementation changes meaning and finalize its evidence before completion.

## Documentation Decision

For every work-producing task, record one of these decisions before completion:

| Decision | Use When | Evidence Must Name |
| --- | --- | --- |
| `updated` | Existing source-of-truth docs changed because behavior, workflow policy, public contract, operator action, or acceptance criteria changed. | Doc path, changed source, and reason. |
| `created` | No suitable source existed and the work introduced durable product, architecture, workflow, or operational meaning. | New doc path, owner/audience, and reason. |
| `unchanged` | Existing docs were inspected and already covered the change. | Doc path/class inspected and why no edit was needed. |
| `not applicable` | The task was answer-only or purely local/mechanical with no durable behavior, policy, contract, or operator meaning, and the user approved skipping. | Checked doc class, why docs are out of scope, and the recorded user approval for the skip. |

"Updated docs", "checked docs", or "no docs needed" is not enough finish
evidence. The evidence must say which document or document class was considered
and why that decision is correct.

## Documentation Gate Contract (enforced)

This section is the source of truth for the `documentation` gate. The
finish-check validators enforce it mechanically, so keep this card and the
validators in sync when either changes. The gate is deliberately not
self-exceptable: an agent cannot grant itself a pass on judgment alone.

Hard rules the finish-check enforces:

- The `documentation` gate always runs on work-producing routes and must carry
  non-empty evidence. A blank or missing decision is 🐱🔴 FAIL.
- `unchanged` is valid only when the evidence names the concrete existing doc
  path (for example `app/README.md`, not just a doc class), proves that doc was
  actually opened/inspected/read this task, and states why the already-read doc
  covers or already contains the change. The validator accepts equivalent
  coverage wording; it must not require one exact English phrase. A bare
  coverage claim, or one without a named path, fails.
- When structured evidence includes `documentation decision:` or
  `impact decision:`, that labeled value is authoritative. Decision-like words
  in the reason explain the change and must not override the recorded decision.
- Skipping documentation (`not applicable`, `no docs`, or `skipped`) is never
  self-approved and a no-durable-doc reason alone is not sufficient. When you
  believe docs should genuinely not be written, ask the user
  "문서를 스킵할까요? / Should I skip the doc?", get explicit approval, and record
  that approval in the evidence — otherwise write the smallest useful doc.
- When a `triage` or `plan` route proposes new product work or an
  implementation roadmap/backlog, the `product route re-entry` gate requires PRD
  coverage (an Accepted PRD link, or explicit product-route re-entry to create
  and accept the PRD, plus an ARD link when structure or module boundaries
  change) before any implementation task or PR.

### Required-document update receipts

A route may require the same workflow card that the current task intentionally
updates. Keep the pre-edit required-document snapshot immutable. Only a route
that itself requires the `documentation` gate may mint or consume this
capability; an extra ledger entry for a gate outside the route grants nothing.
When a successful structured `documentation` record uses `decision=updated`
and names one exact route-relative `required_docs` path, the gate writer
computes a trusted receipt from that snapshot and the current final file. The
receipt records the baseline hash plus the final hash and byte size;
caller-supplied hash values are ignored and overwritten.

Finish accepts the intentional update only while the current file still matches
that recorded final hash and size. Any edit after the documentation evidence
was recorded must be followed by a new successful documentation record for the
same exact path. Missing, malformed, stale, combined, or baseline-mismatched
receipts fail closed. This finish-time exception does not weaken full handoff
capsule worktree checks, repair-cycle fingerprints, or skill-maintenance
verification.

### Where the rules live (do not duplicate per repo)

This card owns the rules; the shared finish-check enforces them for every
project/runtime. Repo-local `AGENTS.md`, `CLAUDE.md`, `CODEX.md` and `.agents/`
docs carry a short pointer, never a copied enforcement block. Replace such
duplicates with a pointer and change rules/exceptions here.

### Making an exception

Per-task skips follow the approval rule above. A recurring exception must be
proposed, documented and reviewed here before it applies across runtimes;
until then it remains a per-task skip. Grill-Me and self-review load this card
and block on a skip without recorded approval or `unchanged` without inspection
proof.

## Review Readiness

For documentation review, do not stop at link and frontmatter validity. Report
the reviewed Markdown scope's readiness distribution:

- frontmatter missing or malformed count
- `status` values such as `draft`, `review`, `stable`, or `deprecated`
- `type` values such as `ai-generated`, `human-reviewed-needed`, or
  `human-reviewed`
- human-review queue count and the highest-risk docs still needing review

This readiness check is required for `docs-review` routes. A large
`human-reviewed-needed` queue is not a broken link, but it is a workflow risk
because agents may treat active guidance as more mature than it is.

## Minimum Card Maturity

Every guidance card must answer when to load it, what to inspect first, its
decision/escalation rule, blocking mistakes, focused and risk-based verification,
and final report evidence. Use `common/skills/agent-skill-card-anatomy/SKILL.md`
as the stricter contract for new, broad-use, recurring-mistake or pre-code/review/
release/handoff cards. Prefer explicit anti-rationalization, red-flag, do-not,
stop-if, verification and report guidance.

For short review cards, include at least findings priority, review checks,
verification focus, and output shape. For platform implementation cards, include
ownership boundaries, forbidden leaks, state/error/data handling, and target
verification. For workflow cards, include entry criteria, steps, stop signals,
and completion evidence.

Name blocking mistakes in an explicit `Do Not`, `Stop If`, `Do Not Approve When`
or equivalent section for implementation/review cards, not only positive prose.

If a card cannot answer these questions yet, mark the gap explicitly instead of
padding with generic advice.

## Promote Local Lessons

Apply the commonization test in Steps: a shared lesson captures reusable risk,
load condition, decision rule and verification question. Product policy, local
commands/paths, service workflows, provider/deployment details, domain vocabulary,
platform-specific APIs/implementation and one-codebase examples stay local.

## Stop If

- The doc would invent product policy, commands, or architecture not present in the repo.
- The same guidance already exists and should be linked or updated instead.
- The requested doc depends on a private source that is unavailable.
