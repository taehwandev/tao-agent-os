---
keyflow_id: sys_docs_tao_skill_bundle_migration_md_skill
status: review
type: ai-generated
---

# Tao Agent OS Skill Bundle Migration

Use when creating, moving, splitting, routing, or reviewing Tao Agent OS
guidance in the `SKILL.md` plus `references/` layout.

## Read

- `references/current-guidance.md` for the canonical layout, routing policy,
  stop conditions, and verification.
- `references/source-of-truth-ownership.md` when the task involves duplicate
  guidance, misplaced topics, compatibility stubs, index/routing summaries, or
  deciding which document owns a reusable rule.
- The affected area entrypoints, such as `common/skills/.../SKILL.md`,
  `workflows/skills/.../SKILL.md`, `platforms/<platform>/skills/.../SKILL.md`,
  or `product-patterns/skills/.../SKILL.md`.

## Process

1. Add or update the small `SKILL.md` entrypoint first.
2. Choose the canonical owner before moving or deduplicating a rule.
3. Move detailed examples, source maps, checklists, and version-sensitive
   material into directly linked reference files.
4. Remove legacy flat `.md` files once routes, links, and tests load the
   canonical bundle directly.
5. Keep a temporary compatibility stub only when a downstream/runtime reference
   still requires that exact path.
6. Update `index.md` and route canonicalization when the load target changes.
7. Validate links, route output, and required-document selection before reporting
   completion.

## Do Not

- Do not put full guidance back into a flat compatibility file.
- Do not keep a flat compatibility stub merely for convenience when it can
  create duplicate retrieval or hallucination risk.
- Do not create a bundle that merely duplicates long prose without reducing the
  default route context.
- Do not hide a required stop condition only in a deep reference.
- Do not leave the same reusable rule restated across multiple canonical docs.

## Verification

- `python3 scripts/workflow.py validate`
- A route smoke that should load the changed bundle and shows `SKILL.md` in
  `Read First` or `Reference On Demand` as appropriate for the task.
- the `VibeGuard overall` line the start and review hooks report, or
  `vibeguard audit . --rules .` when no hook ran it
