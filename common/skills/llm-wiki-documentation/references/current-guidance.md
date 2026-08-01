---
keyflow_id: sys_llm_wiki_documentation
status: stable
type: human-reviewed-needed
---

# LLM Wiki Documentation

Use when creating or reviewing wiki, knowledge-base, runbook, onboarding,
architecture, decision, or operational docs that humans and AI agents will read.

An LLM wiki is not a content dump. It is a durable knowledge layer that helps an
agent retrieve the right facts, distinguish source of truth from commentary, and
act without inventing missing policy.

## Context Layers

From the model's point of view, instructions, skills, workflow cards, repo docs,
and wiki pages all become text context once they are loaded. They are not the
same layer operationally. The difference is how the runtime chooses them, when
the agent must read them, and what authority they have over action.

Use this order when certainty matters:

1. Repo and runtime instructions: `AGENTS.md`, `AGENTS.override.md`,
   `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, or the target repo's local
   equivalent. These define local authority, safety policy, commands, and
   workflow requirements.
2. Workflow route output: the selected command manifest, required docs, gates,
   hooks, and completion evidence for the current task.
3. Skill entrypoint: the relevant `SKILL.md`, such as
   `common/skills/llm-wiki-documentation/SKILL.md`. This is the canonical
   lightweight read target and decides which references are needed.
4. Skill references: focused files under `references/`, such as
   `common/skills/llm-wiki-documentation/references/current-guidance.md`, only
   when the task touches that detail.
5. Repo-local source docs, specs, ADRs, runbooks, tests, and source files that
   prove the current behavior or decision.
6. LLM wiki or generated wiki pages as navigation and summary layers. They help
   retrieval, but they do not override instructions, workflow gates, source
   docs, or reviewed human decisions.

Do not say that an agent "read the docs" just because a wiki, index, or generated
summary was available. Name the exact instruction file, `SKILL.md`, reference
file, source doc, or generated wiki revision that was opened.

For Tao Agent OS itself, prefer these canonical read locations:

- LLM wiki rules: `common/skills/llm-wiki-documentation/SKILL.md`, then
  `common/skills/llm-wiki-documentation/references/current-guidance.md`.
- Skill bundle structure: `common/skills/agent-skill-card-anatomy/SKILL.md`,
  then its selected `references/` file.
- Documentation updates: `workflows/skills/documentation-update/SKILL.md`, then
  its selected `references/` file.
- Task-wide gates: the output of `scripts/workflow.py route ...` plus the
  required route docs it names.

## Page Contract

Each durable wiki page should make these fields obvious, either in frontmatter or
the opening section:

- title
- audience
- purpose
- status: draft, review, stable, or deprecated
- owner or source of truth
- last verified date when commands, links, behavior, or external facts can age
- applies-to scope: repo, app, platform, feature, workflow, or team
- related pages

Use frontmatter when the repo already supports it. Otherwise keep the contract as
a short "At a glance" section near the top.

Shared Tao Agent OS cards may use the smaller `keyflow_id` / `status` / `type`
frontmatter contract. Add owner, source of truth, last verified, applies-to, and
related pages when a page is a durable wiki, runbook, operational procedure, or
runtime-facing integration guide whose facts can age independently.

## Structure

- Start with what the reader can do after reading the page.
- Put canonical facts before examples, history, or discussion.
- Use stable headings that can be linked by agents and search tools.
- Keep one concept per section. Split mixed pages when each section has a
  different owner, lifecycle, or verification path.
- Put procedures in ordered steps and reference material in tables or short
  lists.
- Mark assumptions, decisions, and open questions explicitly.
- Link to source docs instead of copying long policies from another page.
- Keep examples small and current enough to copy safely.

## Actionability

A durable agent-facing page should make the next action hard to miss:

- For a policy page, state the decision rule and what action is blocked.
- For a workflow page, state entry criteria, ordered gates, stop conditions, and
  completion evidence.
- For a platform page, state ownership boundaries, forbidden dependency leaks,
  state/error/data expectations, and target-specific verification.
- For a review page, state severity priority, concrete checks, evidence gaps,
  and output shape.
- For a reference page, state which facts are canonical, which are examples, and
  when the page must be refreshed.

Avoid pages that only describe ideals. Each page should include at least one of:
`Steps`, `Decision Rule`, `Do Not`, `Stop If`, `Review Checklist`,
`Verification`, `Tests`, or `Output`, using the heading that best matches the
page's purpose.

## Retrieval Rules

- Use literal names for APIs, commands, files, routes, events, and products when
  they are the lookup key.
- Add common synonyms only when readers actually search for them.
- Avoid clever titles. Prefer searchable titles over branded wording.
- Do not hide important constraints only in prose. Surface them as bullets,
  tables, "Do not", "Stop if", or "Check" sections.
- Put dates in exact form, such as `2026-05-23`, when time matters.

## Source Boundaries

- Keep repo-local commands, paths, service names, role matrices, and product
  policy in repo-local docs.
- Keep reusable agent behavior, review rules, and platform-neutral guidance in
  shared docs.
- Do not mix marketing copy with operational source-of-truth guidance.
- Do not paste secrets, private prompts, tokens, credential contents, customer
  data, or private incident details into wiki pages.
- Do not present guesses as established behavior. Label inferred or unverified
  content.
- Tracked, team-shared docs must never reference personal absolute paths,
  per-user tool install locations, runtime versions, hook command strings, or
  evidence file paths as if they were shared contracts. Per-user runtime
  details belong in that user's own environment.
- Before writing an improvement down, classify its owner. Per-user runtime or
  environment behavior — hooks, validators, evidence schemas and paths,
  installs, permissions — is fixed only in the user's runtime and must not
  spawn a paired tracked-doc copy. Team product, code, or workflow policy goes
  only to the exact shared owner doc.
- When a shared doc must point at externally owned guidance, keep a thin
  pointer to the canonical owner plus the repo-specific application delta,
  never a synced copy.
- Verification of doc changes includes checking that tracked shared docs gained
  no personal paths, runtime-version contracts, or duplicated runtime rules.

## Per-Module Documentation Catalog

For a large multi-module repo, route module-scoped reading through one
canonical catalog instead of per-module routing files:

- Keep exactly one table with one row per module. Columns: module identity
  summary, always-required docs, situational reference docs, and a
  key-invariants digest that points at the rule's source-of-truth doc.
- Agents identify the touched module from the code or build path and read only
  that module's row plus its listed docs. Reading the repo root instructions
  does not mean reading everything; loading the whole table as context defeats
  the pattern's cost control.
- Required-vs-reference criterion: required docs are the ones defining the
  module's dependency direction and layer boundary — rules whose violation
  still compiles but silently breaks architecture — so they are read on every
  touch regardless of task. Reference docs are keyed to task nature (UI,
  testing, error handling) and may be skipped otherwise. Task-nature docs are
  added on top of the module baseline, never substituted for it.
- Adding a module means adding one row, never a per-module routing file.
- The catalog lives in exactly one file; other entrypoints link to it instead
  of copying it.
- If a touched module has no row, stop and update the catalog first instead of
  guessing its docs.
- Row invariants are digests only; the linked rule doc stays the source of
  truth.

## Language

For agent-facing or cross-repo operational wiki pages, prefer English as the
canonical source. Localized versions can exist for onboarding or distribution,
but they should link back to the canonical page and avoid becoming a separate
policy source.

## Maintenance

- Update the page when behavior, ownership, commands, contracts, or verification
  changes.
- Deprecate stale pages instead of leaving competing guidance active.
- Merge duplicate pages when they answer the same reader question.
- Split pages when a page mixes policy, procedure, reference, and changelog
  content that age at different speeds.
- Record verification evidence for commands, links, screenshots, generated
  output, or external facts when practical.

## Source-Derived Living Wikis

When a wiki is generated from a repository or refreshed by an agent, treat it as
a derived documentation product. It can explain what the current code and docs
show, but it must not become the only source for why a design exists, what
tradeoffs were accepted, or what policy a team chose.

Use this split:

- Generated wiki pages summarize current source behavior, navigation, APIs,
  modules, workflows, and reader-facing usage.
- Human-authored source docs record intent, design rationale, tradeoffs,
  non-obvious constraints, product policy, decisions, and operating rules.
- The generated wiki should cite or link to those human-authored source docs
  instead of inventing rationale from code shape.

For source-derived generation, require a staged pipeline:

1. Build a bounded source inventory and exclude secrets, private runtime files,
   build outputs, caches, generated artifacts, and irrelevant vendor folders.
2. Read high-signal files first: repo instructions, READMEs, package manifests,
   docs indexes, configs, entrypoints, public APIs, tests, and architecture
   notes.
3. Plan a docs-style outline before writing pages. Avoid file-by-file inventory
   pages unless a file is itself the useful public concept.
4. Generate pages with visible source paths or citations for claims about code,
   commands, APIs, configuration, or behavior.
5. Run deterministic checks for source-path validity, citation coverage,
   navigation shape, minimum useful depth, broken links, and excluded-path leaks.
6. Publish the new revision atomically. Keep the previous good wiki visible when
   generation, validation, storage, or publication fails.

Freshness needs explicit state. Track the source revision, generation version,
source inventory scope, and publish timestamp. Regenerate when source revision,
source docs, generator behavior, or validation rules change enough that current
pages may be stale. If refresh is scheduled or event-triggered, apply the
automation guidance for rate limits, cost, retries, permissions, and
operator-visible failure states.

Do not present a source-derived wiki as reviewed documentation unless a human
reviewed the generated revision. Mark generated pages as generated or derived
when the repo's documentation system supports that distinction.

## Check

- Can an agent identify the page's owner, scope, status, and source of truth?
- Is the action path clear without reading unrelated pages?
- Are stale facts, assumptions, and open questions visible?
- Does this page duplicate another page that should be updated instead?
- Are secrets, private data, and repo-specific details kept in the right place?
- If the page is source-derived, can each implementation claim be traced to a
  current source path, source doc, or generated revision manifest?
- Does human-authored documentation still preserve the design intent and
  tradeoffs that generated code summaries cannot infer reliably?

## Tests

For documentation-only changes, verify frontmatter or page contract, internal
links, referenced files, command examples, and duplicate overlap where practical.
For public or localized docs, also verify language switching, missing
translations, long text layout, and that localized copy does not conflict with
the canonical source.
