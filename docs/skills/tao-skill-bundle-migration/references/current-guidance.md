---
keyflow_id: sys_tao_skill_bundle_migration
status: review
type: human-reviewed-needed
---

# Tao Agent OS Skill Bundle Migration

Use this as the source of truth for maintaining Tao Agent OS's skill-bundle
layout. The canonical guidance shape is now `SKILL.md` entrypoints with scoped
`references/` files. Flat `.md` paths are not part of the normal target layout.

When the task is about duplicated rules, misplaced topics, flat compatibility
files, index summaries, route summaries, or "which document owns this rule",
also read `source-of-truth-ownership.md`. That reference owns the cleanup drill;
this file owns the bundle layout contract.

## Goal

Tao Agent OS loads like a skill library:

```text
<area>/skills/<skill-name>/SKILL.md
<area>/skills/<skill-name>/references/<focused-detail>.md
```

`SKILL.md` is the small executable entrypoint: when to load, what to read, the
decision rule, stop conditions, and verification. `references/` holds examples,
deep checklists, source coverage, migration notes, and version-sensitive detail.

## Target Layout

Use this shape for new or materially reworked guidance:

```text
common/skills/<skill-name>/SKILL.md
common/skills/<skill-name>/references/*.md

workflows/skills/<workflow-name>/SKILL.md
workflows/skills/<workflow-name>/references/*.md

platforms/<platform>/skills/<skill-name>/SKILL.md
platforms/<platform>/skills/<skill-name>/references/*.md

product-patterns/skills/<pattern-name>/SKILL.md
product-patterns/skills/<pattern-name>/references/*.md

docs/skills/<doc-name>/SKILL.md
docs/skills/<doc-name>/references/*.md
```

Do not keep flat files by default. A flat compatibility stub is a temporary
exception only when downstream repo instructions, runtime bridges, or external
published links still require the exact legacy path. Do not put full guidance
back into flat files; the detailed source should live in the bundle reference.

## Bundle Contract

Each `SKILL.md` should include:

- `Use When`: exact triggers and exclusions.
- `Read`: local instructions, related cards, source manifests, and reference
  files to open before work.
- `Decision Rule` or `Process`: ordered behavior, not background explanation.
- `Do Not` or `Stop If`: concrete actions that block editing, review, release,
  or handoff.
- `Verification`: smallest evidence that proves the changed surface.
- `Report`: source docs, changed cards, validation, and residual risk.

Reference files should be named by the decision they support, not by file type.
Prefer names such as `intent-security.md`, `release-measurement.md`, or
`route-boundaries.md` over `notes.md`, `details.md`, or `misc.md`.

## Source-Of-Truth Cleanup

For duplicate or misplaced guidance, first choose the canonical owner. The owner
is the most specific reusable skill or workflow reference that can answer the
rule without relying on another document's prose. Other files should link to or
route to that owner; keep a compatibility stub only for a named temporary
dependency.

Use `source-of-truth-ownership.md` for the placement decision, duplicate audit,
delete/link policy, and verification checklist. Do not copy that audit procedure
into each skill card.

## Maintenance Order

1. Create or update the canonical `SKILL.md` entrypoint first.
2. Choose and record the canonical owner for any reusable rule being moved,
   merged, or deduplicated.
3. Put detailed rules, examples, source coverage, and long checklists in
   focused files under `references/`.
4. Remove the flat compatibility file after internal links, route surfaces,
   tests, and required-document manifests target the bundle directly.
5. Keep a short compatibility pointer only when a named downstream/runtime
   dependency still requires the old path, and record that dependency.
6. Update `index.md` and workflow routing to prefer bundle entrypoints.
7. Run workflow validation, route smoke, VibeGuard, and review hooks.
8. When splitting a broad `current-guidance.md`, preserve decision rules, stop
   conditions, and verification in either `SKILL.md` or a directly linked
   focused reference.

## Routing Policy

The workflow router should return canonical bundle entrypoints by default.
Catalog constants should name canonical bundle paths. `workflow_route.py` may
continue accepting legacy flat paths through `scripts/workflow_skill_paths.py`
only as an input-compatibility layer.

During specialized migrations, routes may include multiple bundle entrypoints
when one entrypoint owns the manifest and another owns source application, such
as Android source coverage.

Do not route new work to a flat guidance file. Keep a flat alias only as a
documented temporary compatibility exception.

## Stop If

- A path change would break `scripts/workflow.py route`, required-doc manifests, or
  `python3 scripts/workflow.py validate`.
- A flat compatibility stub is proposed without a named downstream/runtime
  dependency that still needs the exact old path.
- A new bundle duplicates detailed guidance instead of using a focused
  reference.
- A reference file becomes the only source of a required stop condition.
- Two canonical docs would continue owning the same reusable rule after the
  cleanup.
- A shared reference copies third-party skill text instead of distilling a
  reusable rule.

## Verification

For each structural change:

1. Run `python3 scripts/workflow.py validate`.
2. Run a route that should include the new bundle and confirm the route output.
3. Read the `VibeGuard overall` line the start and review hooks report, or run
   `vibeguard audit . --rules .` when no hook ran it.
4. Check links and paths touched by the slice.
5. Review the diff for compatibility stubs, stale references, and duplicated
   source-of-truth language.
