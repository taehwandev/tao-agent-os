---
keyflow_id: sys_platforms_kmp_kmp_compose_ui_md_skill
status: review
type: ai-generated
---

# KMP Compose UI

Use for Compose Multiplatform screens, state holders, components, previews,
resources or UI tests in shared or desktop (JVM) source sets. Not for
Android-only modules (`platforms/android/skills/android-compose-ui/SKILL.md`)
or non-Compose UI.

## Read

- `references/current-guidance.md`; `references/design-system.md` for tokens
  and shared components.

## Verification

- Compile the changed source set, then run `runComposeUiTest`, a screenshot or
  a captured-window check for the changed screen.
