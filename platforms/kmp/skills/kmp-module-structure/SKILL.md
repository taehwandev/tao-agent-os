---
keyflow_id: sys_platforms_kmp_kmp_module_structure_md_skill
status: review
type: ai-generated
---

# KMP Module Structure

Use for multiplatform modules, source sets, Gradle edges, build logic,
`expect`/`actual` placement or package layout, including desktop JVM targets.
Not for Android-only projects or edits inside an existing package.

## Read

- `references/current-guidance.md`; `references/package-layout.md` before
  adding or moving packages.

## Verification

- Compile every affected target and confirm each declared project dependency
  has a matching import.
