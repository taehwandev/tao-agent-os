---
keyflow_id: sys_platforms_kmp_kmp_platform_integration_md_skill
status: review
type: ai-generated
---

# KMP Platform Integration

Use when Kotlin Multiplatform work touches source sets, `expect`/`actual`,
native interop, platform services, files, shell/process execution, clipboard,
notifications, permissions, secure storage, background work, app lifecycle, or
desktop (JVM) packaging and distribution.

Do not use when the change stays in platform-neutral `commonMain` logic with no
adapter or target API, or when the app is Android-only (use the Android
background-work and architecture cards).

## Read

- `references/current-guidance.md` for adapter choice, app wiring, adapter
  patterns, release and packaging checks, stop conditions, and verification.
- For desktop shells, also read
  `platforms/application/skills/application-system-integration/SKILL.md`.
- For source-set hierarchy and module splits, read
  `platforms/kmp/skills/kmp-module-structure/SKILL.md`.

## Verification

- Run compile/test tasks for the affected source sets and app targets, and
  exercise unsupported-target, permission-denied, cancellation, and cleanup
  paths when they are reachable.
