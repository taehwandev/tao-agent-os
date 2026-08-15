---
keyflow_id: sys_deprecation_migration
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Deprecation And Migration

Use when removing, renaming, replacing, migrating, or sunsetting code, APIs,
configuration, data shapes, routes, workflows, commands, features, or docs.

The goal is to avoid zombie code, broken callers, unsafe data transitions, and
unclear compatibility promises.

## Use When

- A public or shared contract is removed, renamed, or replaced.
- A migration changes data, storage, cache, configuration, API, route, command,
  package, or runtime behavior.
- A deprecated path remains in the repo and the user asks to clean it up.
- A release needs compatibility or rollback planning.

For purely internal dead code, still inspect callers before deletion.

## Inspect First

- Callers, imports, references, tests, docs, generated artifacts, CI, scripts,
  release config, and runtime entrypoints.
- Compatibility requirements from repo-local policy, product docs, API docs, or
  release notes.
- Usage signals when removal depends on proving zero use.
- Migration, rollback, and forward-fix paths.

## Decision Rule

Choose one mode before editing:

- **Advisory deprecation**: keep the old path working, add guidance, and avoid
  breaking callers.
- **Compulsory migration**: update all callers and fail clearly if old input is
  still used.
- **Removal**: delete only after callers, docs, tests, generated outputs, and
  release risks are accounted for.

If the mode is unclear, stop and ask before changing behavior.

## Process

1. Inventory every caller and public reference.
2. Identify compatibility window and rollback expectations.
3. Choose advisory, compulsory, or removal mode.
4. Add or update tests that prove old and new behavior as required.
5. Migrate callers in small slices.
6. Remove old paths only after usage and references are accounted for.
7. Update docs, examples, release notes, and operational handoff.

## Candidate-By-Candidate Migrations

When replacing one UI technology, SDK, storage shape, routing model, or build
tool with another, migrate one candidate or capability at a time unless the
source guide requires a coordinated cutover. Before replacing it, capture the
old behavior or public contract. After replacing it, compare parity, update
callers, and delete the old path only after imports, docs, examples, generated
artifacts, runtime entrypoints, and tests no longer depend on it.

Do not use a migration as an excuse for a broad rewrite. Keep each slice small
enough to prove compatibility and rollback or forward-fix behavior.

## Copy-First Behavioral Migration

For a behavior-preserving replacement, keep the original path intact while the
new path is introduced. Copy or implement the replacement first, then compare
it with the old behavior or contract. Switch callers in small, reviewable
slices only after parity is established. Delete the old path in a separate
change, after references and callers are gone and the removal has explicit
approval. Do not combine replacement, caller cutover, and legacy deletion into
one unverified diff.

For UI-bearing copy-first migrations, the allowed visual change count is
exactly zero. Design-system unification, code modernization, new-module
dependency constraints, and structural preference are not grounds for visual
change. Only an explicit user request or an approval item in the linked
design/spec document upgrades the work to an approved redesign, and each
approved visual difference must be itemized before implementation.

Copy-first allows only mechanical differences:

- package, import, visibility, and resource-namespace changes
- module dependency, DI, route, manifest, and intent/result wiring
- type adapters needed to compile in the new owner, with rendered values and
  interactions preserved
- resource id or location moves with user-visible values preserved

Without redesign approval, do not change: render tree, component types,
layout, size, spacing, shape, color, elevation, or fonts; user-visible copy,
icons, ordering, or button placement; per-state UI such as loading, empty,
error, disabled, pagination, dialogs, and sheets; gestures, scroll, focus,
back behavior, or accessibility semantics.

After copying, classify every changed line as mechanical or approved visual.
Any unclassifiable UI difference is an equivalence failure that blocks caller
cutover. Do not switch a caller while the visual change count is nonzero or
the approval basis is empty.

## Workspace Root Relocation

Treat a developer workspace root rename as a coordinated migration across all
repositories under that root. Before the move, record each repository's HEAD,
branch, worktree state, and tracked or untracked changes. Preserve historical
evidence that only describes completed runs; update active registries,
launchers, IDE settings, permission rules, hooks, and operator documentation.

Prefer repository-relative references or an overridable environment variable
for maintained files. After a bulk path substitution, parse structured files
and check for duplicate keys because old and new configuration entries can
collapse onto the same key.

Handle generated and runtime state explicitly:

- recreate or repair virtual-environment launchers whose shebangs contain the
  old absolute path;
- regenerate build metadata and textual caches, then remove or quarantine
  compiled module caches that still embed the old root;
- stop and restart live processes or applications launched from the old root;
- inspect linked worktree metadata and report missing or prunable worktrees
  separately from relocation failures.

Finish by rerunning the canonical installer from the new root, validating
structured configuration, rebuilding at least one path-sensitive product, and
proving that the old workspace root is absent except for intentional migration
fixtures or compatibility fallbacks with an explicit owner.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "Nothing imports it anymore." | Search scripts, tests, docs, generated files, runtime config, and external entrypoints too. |
| "The old API is bad, so breaking it is fine." | Check compatibility and release policy before removal. |
| "The migration is obvious." | Add rollback or forward-fix evidence for stateful data or release-sensitive changes. |
| "Docs can be updated later." | Update docs in the same slice when the public contract changes. |

## Red Flags

- A renamed symbol leaves stale docs, examples, scripts, or generated clients.
- A storage or schema change lacks backward compatibility or rollback language.
- A deprecated path remains callable with no owner, warning, or removal plan.
- A release note omits a breaking change or required operator action.
- A cleanup PR changes behavior without acceptance criteria.

## Do Not

- Do not delete public or shared behavior only because local tests pass.
- Do not leave two active sources of truth for the same command, route, API, or
  data shape.
- Do not silently coerce old input into new behavior when callers need an
  explicit migration error.
- Do not combine broad cleanup with unrelated feature work.
- Do not claim zero usage from a narrow import search alone.

## Stop If

- Compatibility mode, migration owner, or release window is unclear.
- Removal can affect persisted data, external clients, user content, billing,
  auth, permissions, or deployment without rollback.
- Required usage evidence is unavailable and the old path could still be active.

## Serialization And Converter Migrations

When a migration moves request or response models onto a different serialization
stack, the converter is part of the contract being migrated.

- Declare on every moved model whatever annotation the target converter requires.
  A reflective converter tolerates a missing annotation; a compile-time converter
  fails only when a real call runs, so the omission survives compilation.
- Do not treat repository-level tests built on fake service doubles as coverage for
  this. Those doubles bypass the converter entirely, so a missing annotation passes
  every such test. Completion requires a check that exercises the real converter,
  or an explicit note that this risk is unverified.
- When moving from a reflective converter to a compile-time one, reproduce every
  default the old mapping applied to absent fields as a nullable field with an
  explicit default. The old stack turned missing fields into nulls that mappers
  defended; the new stack raises instead, so a field-for-field move silently turns
  previously tolerated responses into failures.

## Verification

Use caller-focused tests, contract tests, migration tests, compatibility checks,
release dry runs, and reference searches. For removal, include evidence that
imports, docs, scripts, generated artifacts, and runtime entrypoints no longer
refer to the old path or that remaining references are intentional.

## Report

Report the selected mode, compatibility impact, migrated callers, verification,
docs updated, and any retained deprecated path with owner and cleanup trigger.
